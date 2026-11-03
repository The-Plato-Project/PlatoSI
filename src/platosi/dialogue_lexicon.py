"""Persistent canonical dialogue tokens for lemma-form and relationship lookups."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import unicodedata

from platosi.canonical_text import CanonicalCorpus
from platosi.unicode_search import key


DATABASE = Path("data/dialogue-lexicon-v1.sqlite")
SCHEMA_VERSION = 2
POLICY_VERSION = "dialogue-tokens-v1"
CANONICAL_FINGERPRINT = "canonical-only"


def greek_letter(char):
    return unicodedata.category(char).startswith("L") and "GREEK" in unicodedata.name(char, "")


def utf16_offset(text, offset):
    return len(text[:offset].encode("utf-16-le")) // 2


def tokens(text):
    start = None
    for offset, char in enumerate(text):
        category = unicodedata.category(char)
        if greek_letter(char):
            if start is None:
                start = offset
        elif start is not None and category.startswith("M"):
            continue
        elif start is not None:
            yield start, offset, text[start:offset]
            start = None
    if start is not None:
        yield start, len(text), text[start:]


class DialogueLexiconIndex:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / DATABASE

    def ensure_dialogue(self, dialogue, text_version=None):
        work = CanonicalCorpus(self.root).work(dialogue, text_version)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            self.initialize(db)
            with db:
                row = db.execute(
                    "SELECT id FROM index_builds WHERE dialogue = ? AND text_version = ? "
                    "AND policy_version = ? AND provider_fingerprint = ? AND state = 'ready'",
                    (dialogue, work["text_version"], POLICY_VERSION, CANONICAL_FINGERPRINT),
                ).fetchone()
                if row is not None:
                    return row["id"]
                row = db.execute(
                    "SELECT id FROM index_builds WHERE dialogue = ? AND text_version = ? "
                    "AND policy_version = ? AND provider_fingerprint = ?",
                    (dialogue, work["text_version"], POLICY_VERSION, CANONICAL_FINGERPRINT),
                ).fetchone()
                if row is None:
                    cursor = db.execute(
                        "INSERT INTO index_builds "
                        "(dialogue, text_version, policy_version, provider_fingerprint, state) "
                        "VALUES (?, ?, ?, ?, 'building')",
                        (dialogue, work["text_version"], POLICY_VERSION, CANONICAL_FINGERPRINT),
                    )
                    build_id = cursor.lastrowid
                else:
                    build_id = row["id"]
                    db.execute("DELETE FROM tokens WHERE build_id = ?", (build_id,))
                    db.execute(
                        "UPDATE index_builds SET state = 'building', completed_at = NULL WHERE id = ?",
                        (build_id,),
                    )
                for section in work["sections"]:
                    passage = "\n".join(segment["text"] for segment in section["segments"])
                    for start, end, surface in tokens(passage):
                        db.execute(
                            "INSERT INTO tokens "
                            "(build_id, surface, lookup_key, accentless_key, stephanus, "
                            "start_offset, end_offset, passage) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                build_id,
                                surface,
                                key(surface),
                                key(surface, "accent-insensitive"),
                                section["stephanus"],
                                utf16_offset(passage, start),
                                utf16_offset(passage, end),
                                passage,
                            ),
                        )
                db.execute(
                    "UPDATE index_builds SET state = 'ready', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (build_id,),
                )
                return build_id

    def form_counts(self, dialogue, text_version=None):
        build_id = self.ensure_dialogue(dialogue, text_version)
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT surface, COUNT(*) AS count FROM tokens WHERE build_id = ? "
                "GROUP BY surface ORDER BY surface",
                (build_id,),
            )
            return [{"form": row["surface"], "count": row["count"]} for row in rows]

    def occurrences(self, dialogue, text_version, forms):
        if not isinstance(forms, (list, tuple)) or not forms:
            raise ValueError("forms must be a nonempty sequence")
        build_id = self.ensure_dialogue(dialogue, text_version)
        normalized = list(dict.fromkeys(key(form) for form in forms))
        placeholders = ",".join("?" for _ in normalized)
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT surface, stephanus, start_offset, end_offset, passage FROM tokens "
                f"WHERE build_id = ? AND lookup_key IN ({placeholders}) "
                "ORDER BY id",
                [build_id, *normalized],
            )
            return [
                {
                    "form": row["surface"],
                    "location": {
                        "dialogue": dialogue,
                        "text_version": text_version,
                        "start": {"stephanus": row["stephanus"], "offset": row["start_offset"]},
                        "end": {"stephanus": row["stephanus"], "offset": row["end_offset"]},
                    },
                    "passage": row["passage"],
                }
                for row in rows
            ]

    def cached_lemma_forms(self, dialogue, text_version, lemma, provider_fingerprint):
        build_id = self.ensure_dialogue(dialogue, text_version)
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT id FROM lemma_builds WHERE token_build_id = ? AND lemma_key = ? "
                "AND policy_version = ? AND provider_fingerprint = ? AND state = 'ready'",
                (build_id, key(lemma), POLICY_VERSION, provider_fingerprint),
            ).fetchone()
            if row is None:
                return None
            records = db.execute(
                "SELECT record FROM lemma_forms WHERE lemma_build_id = ? ORDER BY id",
                (row["id"],),
            )
            return [json.loads(record["record"]) for record in records]

    def store_lemma_forms(self, dialogue, text_version, lemma, provider_fingerprint, records):
        build_id = self.ensure_dialogue(dialogue, text_version)
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            self.initialize(db)
            with db:
                row = db.execute(
                    "SELECT id FROM lemma_builds WHERE token_build_id = ? AND lemma_key = ? "
                    "AND policy_version = ? AND provider_fingerprint = ?",
                    (build_id, key(lemma), POLICY_VERSION, provider_fingerprint),
                ).fetchone()
                if row is None:
                    cursor = db.execute(
                        "INSERT INTO lemma_builds "
                        "(token_build_id, lemma_key, policy_version, provider_fingerprint, state) "
                        "VALUES (?, ?, ?, ?, 'building')",
                        (build_id, key(lemma), POLICY_VERSION, provider_fingerprint),
                    )
                    lemma_build_id = cursor.lastrowid
                else:
                    lemma_build_id = row["id"]
                    db.execute("DELETE FROM lemma_forms WHERE lemma_build_id = ?", (lemma_build_id,))
                    db.execute(
                        "UPDATE lemma_builds SET state = 'building', completed_at = NULL WHERE id = ?",
                        (lemma_build_id,),
                    )
                seen = set()
                for record in records:
                    form = record.get("form")
                    if not isinstance(form, str) or not form:
                        raise ValueError("Lemma form record is missing its form")
                    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    identity = (record.get("provider"), key(form), encoded)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    db.execute(
                        "INSERT INTO lemma_forms "
                        "(lemma_build_id, form, lookup_key, provider, evidence_class, record) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            lemma_build_id,
                            form,
                            key(form),
                            str(record.get("provider") or ""),
                            str(record.get("classification") or "direct_lookup"),
                            encoded,
                        ),
                    )
                db.execute(
                    "UPDATE lemma_builds SET state = 'ready', completed_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (lemma_build_id,),
                )
        return self.cached_lemma_forms(dialogue, text_version, lemma, provider_fingerprint)

    def observed_lemma_forms(self, dialogue, text_version, lemma, provider_fingerprint):
        build_id = self.ensure_dialogue(dialogue, text_version)
        work = CanonicalCorpus(self.root).work(dialogue, text_version)
        divisions = {
            section["stephanus"]: section.get("division")
            for section in work["sections"]
        }
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            lemma_build = db.execute(
                "SELECT id FROM lemma_builds WHERE token_build_id = ? AND lemma_key = ? "
                "AND policy_version = ? AND provider_fingerprint = ? AND state = 'ready'",
                (build_id, key(lemma), POLICY_VERSION, provider_fingerprint),
            ).fetchone()
            if lemma_build is None:
                return []
            evidence_rows = db.execute(
                "SELECT lookup_key, record FROM lemma_forms WHERE lemma_build_id = ? ORDER BY id",
                (lemma_build["id"],),
            )
            evidence = {}
            for row in evidence_rows:
                evidence.setdefault(row["lookup_key"], []).append(json.loads(row["record"]))
            token_rows = db.execute(
                "SELECT DISTINCT tokens.id, tokens.surface, tokens.lookup_key, tokens.stephanus, "
                "tokens.start_offset, tokens.end_offset, tokens.passage "
                "FROM tokens JOIN lemma_forms ON lemma_forms.lookup_key = tokens.lookup_key "
                "WHERE tokens.build_id = ? AND lemma_forms.lemma_build_id = ? ORDER BY tokens.id",
                (build_id, lemma_build["id"]),
            )
            grouped = {}
            for row in token_rows:
                item = grouped.setdefault(row["surface"], {
                    "form": row["surface"],
                    "count": 0,
                    "evidence": evidence.get(row["lookup_key"], []),
                    "occurrences": [],
                })
                item["count"] += 1
                item["occurrences"].append({
                    "location": {
                        "dialogue": dialogue,
                        "text_version": text_version,
                        "start": {"stephanus": row["stephanus"], "offset": row["start_offset"]},
                        "end": {"stephanus": row["stephanus"], "offset": row["end_offset"]},
                    },
                    "division": divisions.get(row["stephanus"]),
                    "passage": row["passage"],
                })
            return sorted(grouped.values(), key=lambda item: (-item["count"], key(item["form"])))

    def cached_lemma_relations(self, dialogue, text_version, lemma, provider_fingerprint):
        build_id = self.ensure_dialogue(dialogue, text_version)
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT id FROM relation_builds WHERE token_build_id = ? AND lemma_key = ? "
                "AND policy_version = ? AND provider_fingerprint = ? AND state = 'ready'",
                (build_id, key(lemma), POLICY_VERSION, provider_fingerprint),
            ).fetchone()
            if row is None:
                return None
            records = db.execute(
                "SELECT record FROM lemma_relations WHERE relation_build_id = ? ORDER BY id",
                (row["id"],),
            )
            return [json.loads(record["record"]) for record in records]

    def store_lemma_relations(self, dialogue, text_version, lemma, provider_fingerprint, records):
        build_id = self.ensure_dialogue(dialogue, text_version)
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            self.initialize(db)
            with db:
                row = db.execute(
                    "SELECT id FROM relation_builds WHERE token_build_id = ? AND lemma_key = ? "
                    "AND policy_version = ? AND provider_fingerprint = ?",
                    (build_id, key(lemma), POLICY_VERSION, provider_fingerprint),
                ).fetchone()
                if row is None:
                    cursor = db.execute(
                        "INSERT INTO relation_builds "
                        "(token_build_id, lemma_key, policy_version, provider_fingerprint, state) "
                        "VALUES (?, ?, ?, ?, 'building')",
                        (build_id, key(lemma), POLICY_VERSION, provider_fingerprint),
                    )
                    relation_build_id = cursor.lastrowid
                else:
                    relation_build_id = row["id"]
                    db.execute(
                        "DELETE FROM lemma_relations WHERE relation_build_id = ?",
                        (relation_build_id,),
                    )
                    db.execute(
                        "UPDATE relation_builds SET state = 'building', completed_at = NULL "
                        "WHERE id = ?",
                        (relation_build_id,),
                    )
                seen = set()
                for record in records:
                    target = record.get("target_lemma")
                    relation_type = record.get("relation_type")
                    if not isinstance(target, str) or not target:
                        raise ValueError("Lemma relation record is missing its target lemma")
                    if not isinstance(relation_type, str) or not relation_type:
                        raise ValueError("Lemma relation record is missing its relation type")
                    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    identity = (record.get("provider"), key(target), relation_type, encoded)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    db.execute(
                        "INSERT INTO lemma_relations "
                        "(relation_build_id, target_lemma, target_key, relation_type, provider, record) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            relation_build_id,
                            target,
                            key(target),
                            relation_type,
                            str(record.get("provider") or ""),
                            encoded,
                        ),
                    )
                db.execute(
                    "UPDATE relation_builds SET state = 'ready', completed_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (relation_build_id,),
                )
        return self.cached_lemma_relations(dialogue, text_version, lemma, provider_fingerprint)

    @staticmethod
    def initialize(db):
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS index_metadata (
                schema_version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS index_builds (
                id INTEGER PRIMARY KEY,
                dialogue TEXT NOT NULL,
                text_version TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                provider_fingerprint TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('building', 'ready', 'failed')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                UNIQUE (dialogue, text_version, policy_version, provider_fingerprint)
            );
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY,
                build_id INTEGER NOT NULL REFERENCES index_builds(id) ON DELETE CASCADE,
                surface TEXT NOT NULL,
                lookup_key TEXT NOT NULL,
                accentless_key TEXT NOT NULL,
                stephanus TEXT NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                passage TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tokens_build_lookup
                ON tokens(build_id, lookup_key);
            CREATE INDEX IF NOT EXISTS tokens_build_accentless
                ON tokens(build_id, accentless_key);
            CREATE TABLE IF NOT EXISTS lemma_builds (
                id INTEGER PRIMARY KEY,
                token_build_id INTEGER NOT NULL REFERENCES index_builds(id) ON DELETE CASCADE,
                lemma_key TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                provider_fingerprint TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('building', 'ready', 'failed')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                UNIQUE (token_build_id, lemma_key, policy_version, provider_fingerprint)
            );
            CREATE TABLE IF NOT EXISTS lemma_forms (
                id INTEGER PRIMARY KEY,
                lemma_build_id INTEGER NOT NULL REFERENCES lemma_builds(id) ON DELETE CASCADE,
                form TEXT NOT NULL,
                lookup_key TEXT NOT NULL,
                provider TEXT NOT NULL,
                evidence_class TEXT NOT NULL,
                record TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS lemma_forms_build_lookup
                ON lemma_forms(lemma_build_id, lookup_key);
            CREATE TABLE IF NOT EXISTS relation_builds (
                id INTEGER PRIMARY KEY,
                token_build_id INTEGER NOT NULL REFERENCES index_builds(id) ON DELETE CASCADE,
                lemma_key TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                provider_fingerprint TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('building', 'ready', 'failed')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                UNIQUE (token_build_id, lemma_key, policy_version, provider_fingerprint)
            );
            CREATE TABLE IF NOT EXISTS lemma_relations (
                id INTEGER PRIMARY KEY,
                relation_build_id INTEGER NOT NULL REFERENCES relation_builds(id) ON DELETE CASCADE,
                target_lemma TEXT NOT NULL,
                target_key TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                record TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS lemma_relations_build_target
                ON lemma_relations(relation_build_id, target_key);
            """
        )
        row = db.execute("SELECT schema_version FROM index_metadata").fetchone()
        if row is None:
            db.execute("INSERT INTO index_metadata VALUES (?)", (SCHEMA_VERSION,))
        elif row["schema_version"] == 1:
            db.execute("UPDATE index_metadata SET schema_version = ?", (SCHEMA_VERSION,))
        elif row["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Dialogue lexicon index schema is incompatible; rebuild the generated index")
