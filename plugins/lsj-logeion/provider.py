"""Logeion LSJ XML adapter, preserving distinct source entries."""
import json
import xml.etree.ElementTree as ET

from platosi.storage import current, new_index, read_index, stamp, verify_blob
from platosi.unicode_search import key


class LSJProvider:
    def __init__(self, manifest, root):
        self.manifest = manifest
        self.root = root
        self.source = root / manifest["config"]["source"]
        self.index = root / manifest["config"]["index"]

    def available(self):
        return self.source.is_dir() and current(self.index, self.manifest)

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
        with new_index(self.index) as db:
            stamp(db, self.manifest)
            db.execute("CREATE TABLE entries (source_path TEXT, ordinal INTEGER, upstream_id TEXT, headword TEXT, exact TEXT, accent TEXT, attributes TEXT, entry_xml TEXT, PRIMARY KEY(source_path,ordinal))")
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
            db.execute("CREATE INDEX entries_exact ON entries(exact)")
            db.execute("CREATE INDEX entries_accent ON entries(accent)")
        return {"provider": self.manifest["id"], "entries": count, "files": len(files), "index": str(self.index)}

    def lookup(self, headword, mode, limit):
        needle = key(headword, mode).strip()
        if not needle:
            raise ValueError("Headword is empty after normalization")
        column = "exact" if mode == "exact" else "accent"
        with read_index(self.index) as db:
            rows = db.execute(f"SELECT * FROM entries WHERE {column} = ? ORDER BY source_path, ordinal LIMIT ?", (needle, limit))
            return [{
                "evidence_type": "scholarly_classification", "provider": self.manifest["id"],
                "provider_version": self.manifest["version"], "source": self.manifest["source"],
                "license": self.manifest["license"], "source_path": row["source_path"],
                "entry_ordinal": row["ordinal"], "entry_id": row["upstream_id"],
                "headword": row["headword"], "attributes": json.loads(row["attributes"]),
                "entry_xml": row["entry_xml"], "search_mode": mode,
            } for row in rows]


def create_provider(manifest, root):
    return LSJProvider(manifest, root)
