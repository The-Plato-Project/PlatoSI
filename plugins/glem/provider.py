"""Optional GLEM candidate-list adapter; no contextual disambiguation."""
import json

from platosi.storage import current, new_index, read_index, stamp, verify_blob
from platosi.unicode_search import key


class GlemProvider:
    def __init__(self, manifest, root):
        self.manifest = manifest
        self.root = root
        self.source = root / manifest["config"]["source"]
        self.index = root / manifest["config"]["index"]

    def available(self):
        return self.source.is_file() and current(self.index, self.manifest)

    def build(self):
        count = 0
        inventory_path = self.manifest["config"].get("inventory")
        if inventory_path:
            inventory = json.loads((self.root / inventory_path).read_text(encoding="utf-8-sig"))
            source = next(s for s in inventory["sources"] if s["id"] == "glem")
            if source["revision"] != self.manifest["source"]["revision"]:
                raise ValueError("GLEM inventory and provider revisions differ")
            entry = next(f for f in source["files"] if f["source_path"] == "glem/list_proiel_perseus_merged_word_lemma_POS_nofreq")
            verify_blob(self.source, entry["size"], entry["git_blob_sha1"])
        with new_index(self.index) as db, self.source.open(encoding="utf-8", errors="strict") as source:
            stamp(db, self.manifest)
            db.execute("CREATE TABLE mappings (line INTEGER PRIMARY KEY, form TEXT, lemma TEXT, tag TEXT, exact TEXT, accent TEXT)")
            for count, line in enumerate(source, 1):
                fields = line.split()
                if len(fields) != 3:
                    raise ValueError(f"Invalid GLEM row {count} in {self.source}")
                form, lemma, tag = fields
                db.execute("INSERT INTO mappings VALUES (?,?,?,?,?,?)",
                           (count, form, lemma, tag, key(form), key(form, "accent-insensitive")))
            db.execute("CREATE INDEX mappings_exact ON mappings(exact)")
            db.execute("CREATE INDEX mappings_accent ON mappings(accent)")
        return {"provider": self.manifest["id"], "mappings": count, "index": str(self.index),
                "licensing_warning": self.manifest["license"]["status"]}

    def analyze(self, form, mode, limit):
        needle = key(form, mode).strip()
        if not needle:
            raise ValueError("Form is empty after normalization")
        column = "exact" if mode == "exact" else "accent"
        with read_index(self.index) as db:
            rows = db.execute(f"SELECT * FROM mappings WHERE {column} = ? ORDER BY line LIMIT ?", (needle, limit))
            return [{
                "evidence_type": "candidate_analysis", "provider": self.manifest["id"],
                "provider_version": self.manifest["version"], "source": self.manifest["source"],
                "license": self.manifest["license"], "source_path": self.manifest["config"]["source"],
                "source_line": row["line"], "form": row["form"], "lemma": row["lemma"],
                "tag": row["tag"], "search_mode": mode,
            } for row in rows]

    def match_forms(self, lemma, forms):
        lemma = key(lemma)
        result = []
        with read_index(self.index) as db:
            for start in range(0, len(forms), 400):
                group = forms[start:start + 400]
                if not group:
                    continue
                placeholders = ",".join("?" for _ in group)
                sql = f"SELECT * FROM mappings WHERE exact IN ({placeholders}) AND lemma = ? ORDER BY line"
                for row in db.execute(sql, [*(key(form) for form in group), lemma]):
                    result.append({
                        "evidence_type": "candidate_analysis", "provider": self.manifest["id"],
                        "provider_version": self.manifest["version"], "source": self.manifest["source"],
                        "license": self.manifest["license"], "source_path": self.manifest["config"]["source"],
                        "source_line": row["line"], "form": row["form"], "lemma": row["lemma"],
                        "tag": row["tag"], "search_mode": "exact",
                    })
        return result

    def lemma_forms(self, lemma, limit):
        lemma = key(lemma)
        with read_index(self.index) as db:
            rows = db.execute(
                "SELECT * FROM mappings WHERE lemma = ? ORDER BY line LIMIT ?",
                (lemma, limit + 1),
            ).fetchall()
        if len(rows) > limit:
            raise ValueError(f"GLEM lemma form inventory exceeds {limit} records")
        return [{
            "evidence_type": "candidate_analysis",
            "provider": self.manifest["id"],
            "provider_version": self.manifest["version"],
            "source": self.manifest["source"],
            "license": self.manifest["license"],
            "source_path": self.manifest["config"]["source"],
            "source_line": row["line"],
            "form": row["form"],
            "lemma": row["lemma"],
            "tag": row["tag"],
            "method": "lookup",
            "classification": "direct_lookup",
            "search_mode": "exact",
        } for row in rows]


def create_provider(manifest, root):
    return GlemProvider(manifest, root)
