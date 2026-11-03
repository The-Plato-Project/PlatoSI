"""Perseus TEI adapter; indexes the XML body text and its citation offsets."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from platosi.storage import current, new_index, read_index, stamp, verify_blob
from platosi.unicode_search import key, matches, normalize

NS = "{http://www.tei-c.org/ns/1.0}"
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"


def extract(body):
    parts = []
    length = 0
    divisions = []
    milestones = []
    markup = []

    def append(text):
        nonlocal length
        if text:
            parts.append(text)
            length += len(text)

    def walk(node, path):
        start = length
        is_div = node.tag == NS + "div" and node.get("type") == "textpart"
        if is_div:
            path = path + [{"unit": node.get("subtype"), "n": node.get("n")}]
        if node.tag == NS + "milestone" and node.get("resp") == "Stephanus":
            milestones.append({"offset": length, "unit": node.get("unit"), "n": node.get("n")})
        append(node.text)
        for child in node:
            walk(child, path)
            append(child.tail)
        if is_div:
            divisions.append({"start": start, "end": length, "path": path})
        if node.tag in {NS + tag for tag in ("del", "add", "label", "bibl", "sic", "corr", "head", "gap")}:
            markup.append({"start": start, "end": length, "tag": node.tag.removeprefix(NS), "attributes": node.attrib})

    walk(body, [])
    return "".join(parts), divisions, milestones, markup


class PlatoProvider:
    def __init__(self, manifest, root):
        self.manifest = manifest
        self.root = root
        self.source = root / manifest["config"]["source"]
        self.index = root / manifest["config"]["index"]

    def available(self):
        return self.source.is_dir() and current(self.index, self.manifest)

    def build(self):
        files = sorted(self.source.glob("*/*perseus-grc*.xml"))
        if not files:
            raise FileNotFoundError(f"No Perseus Greek edition XML found in {self.source}")
        inventory_path = self.manifest["config"].get("inventory")
        if inventory_path:
            inventory = json.loads((self.root / inventory_path).read_text(encoding="utf-8-sig"))
            if inventory["revision"] != self.manifest["source"]["revision"]:
                raise ValueError("Corpus inventory and provider revisions differ")
            entries = [f for f in inventory["files"] if "perseus-grc" in f["source_path"]]
            expected = {self.source / Path(f["source_path"]).relative_to("data/tlg0059"): f for f in entries}
            if set(files) != set(expected):
                raise ValueError("Corpus files do not match the pinned inventory")
            for path, entry in expected.items():
                verify_blob(path, entry["size"], entry["git_blob_sha1"])
        with new_index(self.index) as db:
            stamp(db, self.manifest)
            db.execute("CREATE TABLE editions (urn TEXT PRIMARY KEY, work TEXT, source_path TEXT, text TEXT, exact TEXT, accent TEXT, divisions TEXT, milestones TEXT, declarations TEXT, markup TEXT)")
            for path in files:
                root = ET.parse(path).getroot()
                body = root.find(f"{NS}text/{NS}body")
                if body is None or not body.get(XML_BASE):
                    raise ValueError(f"Missing body or edition identifier: {path}")
                edition = body.get(XML_BASE)
                text, divisions, milestones, markup = extract(body)
                declarations = [ET.tostring(x, encoding="unicode") for x in root.findall(f".//{NS}refsDecl")]
                db.execute("INSERT INTO editions VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    edition, edition.rsplit(".", 1)[0], str(path),
                    text, key(text), key(text, "accent-insensitive"),
                    json.dumps(divisions, ensure_ascii=False), json.dumps(milestones, ensure_ascii=False),
                    json.dumps(declarations, ensure_ascii=False), json.dumps(markup, ensure_ascii=False)))
        return {"provider": self.manifest["id"], "editions": len(files), "index": str(self.index)}

    def record(self, row, start, end, mode=None):
        divisions = json.loads(row["divisions"])
        milestones = json.loads(row["milestones"])
        markup = json.loads(row["markup"])
        containing = [d for d in divisions if d["start"] <= start < d["end"]]
        leaf = max(containing, key=lambda d: len(d["path"]), default=None)
        if leaf:
            selected = [d for d in divisions if len(d["path"]) == len(leaf["path"]) and d["start"] < end and d["end"] > start]
            left = min([d["start"] for d in selected] + [start])
            right = max([d["end"] for d in selected] + [end])
        else:
            left, right = max(0, start - 100), min(len(row["text"]), end + 100)
        refs = []
        for d in sorted(divisions, key=lambda d: d["start"]):
            if d["start"] < end and d["end"] > start:
                refs.append({"path": d["path"], "citation": ".".join(str(p["n"]) for p in d["path"])})
        stephanus = {}
        for milestone in milestones:
            if milestone["offset"] > start:
                break
            stephanus[milestone["unit"]] = milestone["n"]
        overlapping = [m for m in markup if m["start"] < end and m["end"] > start]
        visible_markup = [{**m, "start": m["start"] - left, "end": m["end"] - left}
                          for m in markup if m["start"] <= right and m["end"] >= left]
        return {
            "evidence_type": "editorial_text" if mode and overlapping else "primary_text", "provider": self.manifest["id"],
            "provider_version": self.manifest["version"], "source": self.manifest["source"],
            "license": self.manifest["license"], "source_path": row["source_path"],
            "work": row["work"], "edition": row["urn"], "citations": refs,
            "stephanus_at_match": stephanus, "citation_declarations_xml": json.loads(row["declarations"]),
            "text": row["text"][left:right], "match": row["text"][start:end],
            "match_start": start - left, "match_end": end - left, "search_mode": mode,
            "source_markup": visible_markup,
        }

    def search(self, query, mode, limit):
        needle = key(query, mode).strip()
        if not needle:
            raise ValueError("Query is empty after normalization")
        column = "exact" if mode == "exact" else "accent"
        result = []
        with read_index(self.index) as db:
            for row in db.execute(f"SELECT * FROM editions WHERE instr({column}, ?) > 0 ORDER BY urn", (needle,)):
                normalized, offsets = normalize(row["text"], mode)
                for start, end in matches(normalized, needle):
                    result.append(self.record(row, offsets[start][0], offsets[end - 1][1], mode))
                    if len(result) >= limit:
                        return result
        return result

    def passage(self, edition, citation):
        results = []
        with read_index(self.index) as db:
            row = db.execute("SELECT * FROM editions WHERE urn = ?", (edition,)).fetchone()
            if row is None:
                return results

            divisions = json.loads(row["divisions"])
            for d in divisions:
                path = ".".join(str(p["n"]) for p in d["path"])
                if path == citation:
                    results.append(self.record(row, d["start"], d["end"]))
            if not results:
                milestones = json.loads(row["milestones"])
                for i, marker in enumerate(milestones):
                    if marker["unit"] == "section" and marker["n"] == citation:
                        end = next((m["offset"] for m in milestones[i + 1:] if m["unit"] == "section"), len(row["text"]))
                        results.append(self.record(row, marker["offset"], end))
        return results

    def reading(self, edition, citation):
        with read_index(self.index) as db:
            row = db.execute("SELECT * FROM editions WHERE urn = ?", (edition,)).fetchone()
            if row is None:
                return []
            scope = next((d for d in json.loads(row["divisions"])
                          if ".".join(str(p["n"]) for p in d["path"]) == citation), None)
            if scope is None:
                return []
            start, end = scope["start"], scope["end"]
            milestones = json.loads(row["milestones"])
            before = {}
            for milestone in milestones:
                if milestone["offset"] > start:
                    break
                before[milestone["unit"]] = milestone["n"]
            return [{
                "provider": self.manifest["id"], "provider_version": self.manifest["version"],
                "source": self.manifest["source"], "license": self.manifest["license"],
                "source_path": row["source_path"], "work": row["work"], "edition": row["urn"],
                "scope": citation, "text": row["text"][start:end],
                "initial_citation": before,
                "milestones": [{**m, "offset": m["offset"] - start} for m in milestones
                               if start < m["offset"] < end],
                "source_markup": [{**m, "start": max(m["start"], start) - start,
                                   "end": min(m["end"], end) - start}
                                  for m in json.loads(row["markup"])
                                  if m["start"] < end and m["end"] > start],
            }]


def create_provider(manifest, root):
    return PlatoProvider(manifest, root)
