"""Logeion LSJ XML adapter, preserving distinct source entries."""
import copy
import json
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET

from platosi.storage import current, new_index, read_index, stamp, verify_blob
from platosi.unicode_search import key


def greek_headword(text):
    value = text.strip().strip(".,;:··()[]")
    if not value or any(char.isspace() for char in value):
        return None
    has_letter = False
    for char in value:
        category = unicodedata.category(char)
        if category.startswith("M"):
            continue
        if category.startswith("L") and "GREEK" in unicodedata.name(char, ""):
            has_letter = True
            continue
        if char not in "-'’᾽":
            return None
    return value if has_letter else None


def orthographic_aliases(entry):
    aliases = []
    for orth in entry.findall("orth"):
        source_text = "".join(orth.itertext()).strip()
        if not source_text or source_text.startswith("-") or source_text.endswith("-"):
            continue
        alias = greek_headword(source_text.replace("-", ""))
        if alias is None:
            continue
        fragment = copy.copy(orth)
        fragment.tail = None
        aliases.append({
            "alias": alias,
            "classification": "explicit_orthographic_variant",
            "source_fragment": ET.tostring(fragment, encoding="unicode"),
        })
    return aliases


class LSJProvider:
    def __init__(self, manifest, root):
        self.manifest = manifest
        self.root = root
        self.source = root / manifest["config"]["source"]
        self.index = root / manifest["config"]["index"]

    def available(self):
        if not self.source.is_dir() or not current(self.index, self.manifest):
            return False
        try:
            with read_index(self.index) as db:
                db.execute("SELECT 1 FROM aliases LIMIT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def build(self):
        files = sorted(self.source.glob("greatscott*.xml"))
        if not files:
            raise FileNotFoundError(f"No LSJ XML found in {self.source}")
        inventory_path = self.manifest["config"].get("inventory")
        if inventory_path:
            inventory = json.loads((self.root / inventory_path).read_text(encoding="utf-8-sig"))
            if inventory["revision"] != self.manifest["source"]["revision"]:
                raise ValueError("LSJ inventory and provider revisions differ")
            entries = [f for f in inventory["files"] if f["source_path"].startswith("greatscott") and f["source_path"].endswith(".xml")]
            expected = {self.source / f["source_path"]: f for f in entries}
            if set(files) != set(expected):
                raise ValueError("LSJ files do not match the pinned inventory")
            for path, entry in expected.items():
                verify_blob(path, entry["size"], entry["git_blob_sha1"])
        count = 0
        alias_count = 0
        with new_index(self.index) as db:
            stamp(db, self.manifest)
            db.execute("CREATE TABLE entries (source_path TEXT, ordinal INTEGER, upstream_id TEXT, headword TEXT, exact TEXT, accent TEXT, attributes TEXT, entry_xml TEXT, PRIMARY KEY(source_path,ordinal))")
            db.execute("CREATE TABLE aliases (source_path TEXT, ordinal INTEGER, alias TEXT, exact TEXT, accent TEXT, classification TEXT, source_fragment TEXT, PRIMARY KEY(source_path,ordinal,alias), FOREIGN KEY(source_path,ordinal) REFERENCES entries(source_path,ordinal))")
            for path in files:
                root = ET.parse(path).getroot()
                for ordinal, entry in enumerate(root.findall("./text/div1/div2"), 1):
                    head = entry.find("head")
                    if head is None:
                        raise ValueError(f"Entry without head in {path}, ordinal {ordinal}")
                    headword = "".join(head.itertext())
                    db.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?)", (
                        str(path), ordinal, entry.get("id"), headword,
                        key(headword), key(headword, "accent-insensitive"),
                        json.dumps(entry.attrib, ensure_ascii=False), ET.tostring(entry, encoding="unicode")))
                    count += 1
                    for alias_record in orthographic_aliases(entry):
                        alias = alias_record["alias"]
                        if key(alias) == key(headword):
                            continue
                        db.execute("INSERT OR IGNORE INTO aliases VALUES (?,?,?,?,?,?,?)", (
                            str(path), ordinal, alias, key(alias), key(alias, "accent-insensitive"),
                            alias_record["classification"], alias_record["source_fragment"]))
                        alias_count += db.execute("SELECT changes()").fetchone()[0]
            db.execute("CREATE INDEX entries_exact ON entries(exact)")
            db.execute("CREATE INDEX entries_accent ON entries(accent)")
            db.execute("CREATE INDEX aliases_exact ON aliases(exact)")
            db.execute("CREATE INDEX aliases_accent ON aliases(accent)")
        return {"provider": self.manifest["id"], "entries": count, "aliases": alias_count,
                "files": len(files), "index": str(self.index)}

    def lookup(self, headword, mode, limit):
        needle = key(headword, mode).strip()
        if not needle:
            raise ValueError("Headword is empty after normalization")
        column = "exact" if mode == "exact" else "accent"
        with read_index(self.index) as db:
            rows = db.execute(
                f"SELECT * FROM entries WHERE {column} = ? "
                "ORDER BY source_path, ordinal LIMIT ?", (needle, limit)
            ).fetchall()
            matches = [(row, row["headword"], "headword", None) for row in rows]
            if len(matches) < limit:
                alias_rows = db.execute(
                    f"SELECT entries.*, aliases.alias AS matched_term, "
                    "aliases.classification AS match_kind, aliases.source_fragment AS match_fragment "
                    "FROM aliases JOIN entries USING (source_path, ordinal) "
                    f"WHERE aliases.{column} = ? ORDER BY entries.source_path, entries.ordinal",
                    (needle,),
                ).fetchall()
                identities = {(row["source_path"], row["ordinal"]) for row in rows}
                for row in alias_rows:
                    identity = (row["source_path"], row["ordinal"])
                    if identity in identities:
                        continue
                    identities.add(identity)
                    matches.append(
                        (row, row["matched_term"], row["match_kind"], row["match_fragment"])
                    )
                    if len(matches) >= limit:
                        break
            return [{
                "evidence_type": "scholarly_classification", "provider": self.manifest["id"],
                "provider_version": self.manifest["version"], "source": self.manifest["source"],
                "license": self.manifest["license"], "source_path": row["source_path"],
                "entry_ordinal": row["ordinal"], "entry_id": row["upstream_id"],
                "headword": row["headword"], "attributes": json.loads(row["attributes"]),
                "entry_xml": row["entry_xml"], "search_mode": mode,
                "matched_term": matched_term, "match_kind": match_kind,
                "match_fragment": match_fragment,
            } for row, matched_term, match_kind, match_fragment in matches]

    def lemma_relations(self, lemma, limit):
        lemma_key = key(lemma).strip()
        if not lemma_key:
            raise ValueError("Lemma is empty after normalization")
        records = []
        with read_index(self.index) as db:
            entries = db.execute(
                "SELECT * FROM entries WHERE exact = ? ORDER BY source_path, ordinal",
                (lemma_key,),
            ).fetchall()
            for entry in entries:
                root = ET.fromstring(entry["entry_xml"])
                for node in root.findall(".//etym"):
                    if node.get("lang") != "grc":
                        continue
                    target = greek_headword("".join(node.itertext()))
                    if target is None or key(target) == lemma_key:
                        continue
                    target_row = db.execute(
                        "SELECT headword FROM entries WHERE exact = ? "
                        "ORDER BY source_path, ordinal LIMIT 1",
                        (key(target),),
                    ).fetchone()
                    if target_row is None:
                        continue
                    fragment = copy.copy(node)
                    fragment.tail = None
                    records.append({
                        "evidence_type": "lexical_relation",
                        "provider": self.manifest["id"],
                        "provider_version": self.manifest["version"],
                        "source": self.manifest["source"],
                        "license": self.manifest["license"],
                        "source_lemma": entry["headword"],
                        "target_lemma": target_row["headword"],
                        "relation_type": "etymological_relation",
                        "direction": "directed",
                        "source_reference": {
                            "source_path": entry["source_path"],
                            "entry_ordinal": entry["ordinal"],
                            "entry_id": entry["upstream_id"],
                        },
                        "source_fragment": ET.tostring(fragment, encoding="unicode"),
                        "classification": "explicit_dictionary_markup",
                    })
                    if len(records) > limit:
                        raise ValueError(f"LSJ lemma relation inventory exceeds {limit} records")
        return records


def create_provider(manifest, root):
    return LSJProvider(manifest, root)
