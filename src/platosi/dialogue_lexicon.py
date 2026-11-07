"""Persistent canonical dialogue tokens for lemma-form and relationship lookups."""

from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import unicodedata

from platosi.canonical_text import CanonicalCorpus
from platosi.evidence_database import database_path
from platosi.unicode_search import key


SCHEMA_VERSION = 5
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


@dataclass(frozen=True)
class DialogueLexiconContext:
    dialogue: str
    text_version: str
    work: dict
    build_id: int
    db: sqlite3.Connection


class DialogueLexiconIndex:
    def __init__(self, root):
        self.root = Path(root)
        self.path = database_path(self.root)

    @contextmanager
    def _database(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            self.initialize(db)
            yield db

    @contextmanager
    def request_context(self, dialogue, text_version=None):
        work = CanonicalCorpus(self.root).work(dialogue, text_version)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            self.initialize(db)
            with db:
                build_id = self._ensure_dialogue(db, dialogue, work)
            yield DialogueLexiconContext(
                dialogue=dialogue,
                text_version=work["text_version"],
                work=work,
                build_id=build_id,
                db=db,
            )

    def ensure_dialogue(self, dialogue, text_version=None):
        with self.request_context(dialogue, text_version) as context:
            return context.build_id

    @staticmethod
    def _ensure_dialogue(db, dialogue, work):
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
            db.execute(
                "DELETE FROM canonical_sections WHERE build_id = ?",
                (build_id,),
            )
            db.execute(
                "UPDATE index_builds SET state = 'building', completed_at = NULL WHERE id = ?",
                (build_id,),
            )
        token_rows = []
        section_ids = {}
        for ordinal, section in enumerate(work["sections"]):
            passage = "\n".join(segment["text"] for segment in section["segments"])
            cursor = db.execute(
                "INSERT INTO canonical_sections "
                "(build_id, ordinal, stephanus, division, passage) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    build_id,
                    ordinal,
                    section["stephanus"],
                    json.dumps(
                        section.get("division"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    passage,
                ),
            )
            section_ids[section["stephanus"]] = cursor.lastrowid
            for start, end, surface in tokens(passage):
                token_rows.append(
                    (
                        section["stephanus"],
                        surface,
                        utf16_offset(passage, start),
                        utf16_offset(passage, end),
                    )
                )
        surfaces = list(dict.fromkeys(row[1] for row in token_rows))
        db.executemany(
            "INSERT OR IGNORE INTO canonical_forms "
            "(surface, lookup_key, accentless_key) VALUES (?, ?, ?)",
            [
                (surface, key(surface), key(surface, "accent-insensitive"))
                for surface in surfaces
            ],
        )
        form_ids = {}
        for start in range(0, len(surfaces), 400):
            group = surfaces[start:start + 400]
            placeholders = ",".join("?" for _ in group)
            form_ids.update(
                {
                    row["surface"]: row["id"]
                    for row in db.execute(
                        "SELECT id, surface FROM canonical_forms "
                        f"WHERE surface IN ({placeholders})",
                        group,
                    )
                }
            )
        db.executemany(
            "INSERT INTO tokens "
            "(build_id, section_id, form_id, start_offset, end_offset) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    build_id,
                    section_ids[stephanus],
                    form_ids[surface],
                    start_offset,
                    end_offset,
                )
                for stephanus, surface, start_offset, end_offset in token_rows
            ],
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
                "SELECT canonical_forms.surface, COUNT(*) AS count FROM tokens "
                "JOIN canonical_forms ON canonical_forms.id = tokens.form_id "
                "WHERE tokens.build_id = ? "
                "GROUP BY canonical_forms.surface ORDER BY canonical_forms.surface",
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
                "SELECT canonical_forms.surface, canonical_sections.stephanus, "
                "tokens.start_offset, tokens.end_offset, canonical_sections.passage "
                "FROM tokens "
                "JOIN canonical_forms ON canonical_forms.id = tokens.form_id "
                "JOIN canonical_sections ON canonical_sections.id = tokens.section_id "
                f"WHERE tokens.build_id = ? AND canonical_forms.lookup_key IN ({placeholders}) "
                "ORDER BY tokens.id",
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

    def cached_lemma_forms(
        self, dialogue, text_version, lemma, provider_fingerprint, context=None
    ):
        del dialogue, text_version
        manager = nullcontext(context.db) if context is not None else self._database()
        with manager as db:
            row = db.execute(
                "SELECT id FROM provider_lemma_builds WHERE lemma_key = ? "
                "AND policy_version = ? AND provider_fingerprint = ? AND state = 'ready'",
                (key(lemma), POLICY_VERSION, provider_fingerprint),
            ).fetchone()
            if row is None:
                return None
            records = db.execute(
                "SELECT record FROM provider_lemma_forms WHERE lemma_build_id = ? ORDER BY id",
                (row["id"],),
            )
            return [json.loads(record["record"]) for record in records]

    def store_lemma_forms(
        self, dialogue, text_version, lemma, provider_fingerprint, records, context=None
    ):
        manager = nullcontext(context.db) if context is not None else self._database()
        with manager as db:
            with db:
                row = db.execute(
                    "SELECT id FROM provider_lemma_builds WHERE lemma_key = ? "
                    "AND policy_version = ? AND provider_fingerprint = ?",
                    (key(lemma), POLICY_VERSION, provider_fingerprint),
                ).fetchone()
                if row is None:
                    cursor = db.execute(
                        "INSERT INTO provider_lemma_builds "
                        "(lemma_key, policy_version, provider_fingerprint, state) "
                        "VALUES (?, ?, ?, 'building')",
                        (key(lemma), POLICY_VERSION, provider_fingerprint),
                    )
                    lemma_build_id = cursor.lastrowid
                else:
                    lemma_build_id = row["id"]
                    db.execute(
                        "DELETE FROM provider_lemma_forms WHERE lemma_build_id = ?",
                        (lemma_build_id,),
                    )
                    db.execute(
                        "UPDATE provider_lemma_builds "
                        "SET state = 'building', completed_at = NULL WHERE id = ?",
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
                        "INSERT INTO provider_lemma_forms "
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
                    "UPDATE provider_lemma_builds "
                    "SET state = 'ready', completed_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (lemma_build_id,),
                )
        return self.cached_lemma_forms(
            dialogue, text_version, lemma, provider_fingerprint, context=context
        )

    def observed_lemma_forms(
        self, dialogue, text_version, lemma, provider_fingerprint, context=None
    ):
        if context is None:
            with self.request_context(dialogue, text_version) as request_context:
                return self.observed_lemma_forms(
                    dialogue,
                    text_version,
                    lemma,
                    provider_fingerprint,
                    context=request_context,
                )
        records = self.cached_lemma_forms(
            dialogue,
            text_version,
            lemma,
            provider_fingerprint,
            context=context,
        )
        return self.observed_records(
            dialogue, text_version, records or [], context=context
        )

    def observed_records(self, dialogue, text_version, records, context=None):
        if context is None:
            with self.request_context(dialogue, text_version) as request_context:
                return self.observed_records(
                    dialogue, text_version, records, context=request_context
                )
        divisions = {
            section["stephanus"]: section.get("division")
            for section in context.work["sections"]
        }
        evidence = {}
        for record in records:
            form = record.get("form")
            if not isinstance(form, str) or not form:
                raise ValueError("Lemma form record is missing its form")
            evidence.setdefault(key(form), []).append(record)
        if not evidence:
            return []
        with nullcontext(context.db) as db:
            token_rows = []
            lookup_keys = sorted(evidence)
            for start in range(0, len(lookup_keys), 400):
                group = lookup_keys[start:start + 400]
                placeholders = ",".join("?" for _ in group)
                token_rows.extend(db.execute(
                    "SELECT tokens.id, canonical_forms.surface, "
                    "canonical_forms.lookup_key, canonical_sections.stephanus, "
                    "tokens.start_offset, tokens.end_offset, "
                    "canonical_sections.passage FROM tokens "
                    "JOIN canonical_forms ON canonical_forms.id = tokens.form_id "
                    "JOIN canonical_sections "
                    "ON canonical_sections.id = tokens.section_id "
                    f"WHERE tokens.build_id = ? "
                    f"AND canonical_forms.lookup_key IN ({placeholders})",
                    [context.build_id, *group],
                ))
            token_rows.sort(key=lambda row: row["id"])
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
                        "text_version": context.text_version,
                        "start": {"stephanus": row["stephanus"], "offset": row["start_offset"]},
                        "end": {"stephanus": row["stephanus"], "offset": row["end_offset"]},
                    },
                    "division": divisions.get(row["stephanus"]),
                    "passage": row["passage"],
                })
            return sorted(grouped.values(), key=lambda item: (-item["count"], key(item["form"])))

    def cached_lemma_relations(
        self, dialogue, text_version, lemma, provider_fingerprint, context=None
    ):
        if context is None:
            with self.request_context(dialogue, text_version) as request_context:
                return self.cached_lemma_relations(
                    dialogue,
                    text_version,
                    lemma,
                    provider_fingerprint,
                    context=request_context,
                )
        build_id = context.build_id
        with nullcontext(context.db) as db:
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

    def store_lemma_relations(
        self, dialogue, text_version, lemma, provider_fingerprint, records, context=None
    ):
        if context is None:
            with self.request_context(dialogue, text_version) as request_context:
                return self.store_lemma_relations(
                    dialogue,
                    text_version,
                    lemma,
                    provider_fingerprint,
                    records,
                    context=request_context,
                )
        build_id = context.build_id
        with nullcontext(context.db) as db:
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
        return self.cached_lemma_relations(
            dialogue, text_version, lemma, provider_fingerprint, context=context
        )

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
            CREATE TABLE IF NOT EXISTS canonical_sections (
                id INTEGER PRIMARY KEY,
                build_id INTEGER NOT NULL
                    REFERENCES index_builds(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                stephanus TEXT NOT NULL,
                division TEXT NOT NULL,
                passage TEXT NOT NULL,
                UNIQUE (build_id, ordinal),
                UNIQUE (build_id, stephanus)
            );
            CREATE TABLE IF NOT EXISTS canonical_forms (
                id INTEGER PRIMARY KEY,
                surface TEXT NOT NULL UNIQUE,
                lookup_key TEXT NOT NULL,
                accentless_key TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS canonical_forms_lookup
                ON canonical_forms(lookup_key);
            CREATE INDEX IF NOT EXISTS canonical_forms_accentless
                ON canonical_forms(accentless_key);
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY,
                build_id INTEGER NOT NULL REFERENCES index_builds(id) ON DELETE CASCADE,
                section_id INTEGER NOT NULL
                    REFERENCES canonical_sections(id) ON DELETE CASCADE,
                form_id INTEGER NOT NULL REFERENCES canonical_forms(id),
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tokens_build_lookup
                ON tokens(build_id, form_id);
            CREATE INDEX IF NOT EXISTS tokens_section
                ON tokens(section_id, start_offset);
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
            CREATE TABLE IF NOT EXISTS provider_lemma_builds (
                id INTEGER PRIMARY KEY,
                lemma_key TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                provider_fingerprint TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('building', 'ready', 'failed')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                UNIQUE (lemma_key, policy_version, provider_fingerprint)
            );
            CREATE TABLE IF NOT EXISTS provider_lemma_forms (
                id INTEGER PRIMARY KEY,
                lemma_build_id INTEGER NOT NULL
                    REFERENCES provider_lemma_builds(id) ON DELETE CASCADE,
                form TEXT NOT NULL,
                lookup_key TEXT NOT NULL,
                provider TEXT NOT NULL,
                evidence_class TEXT NOT NULL,
                record TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS provider_lemma_forms_build_lookup
                ON provider_lemma_forms(lemma_build_id, lookup_key);
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
        elif row["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Dialogue lexicon index schema is incompatible; rebuild the generated index")
