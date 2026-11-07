"""Build and read the compact, dialogue-scoped Plato morphology database."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from platosi.dialogue_lexicon import DialogueLexiconIndex
from platosi.evidence_database import DATABASE, database_path
from platosi.unicode_search import key


SCHEMA_VERSION = 2
POLICY_VERSION = "plato-morphology-v1"
PROVIDER_ERRORS = (OSError, RuntimeError, ValueError, ImportError, sqlite3.Error)


class MorphologyBuildError(RuntimeError):
    pass


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_identity(record):
    return hashlib.sha256(_encoded(record).encode("utf-8")).hexdigest()


def provider_identity(registration, provider):
    identity = getattr(provider, "index_identity", None)
    if not callable(identity):
        raise ValueError(
            f"{registration.manifest['id']} does not expose a reproducible index identity"
        )
    value = identity()
    if not isinstance(value, dict) or not value:
        raise ValueError(
            f"{registration.manifest['id']} returned an invalid index identity"
        )
    return value, hashlib.sha256(_encoded(value).encode("utf-8")).hexdigest()


class DialogueMorphologyIndex:
    def __init__(self, root):
        self.root = Path(root)
        self.path = database_path(self.root)
        self.dialogues = DialogueLexiconIndex(root)

    def build(
        self,
        registry,
        dialogue,
        text_version=None,
        provider_id="morpheus",
        rebuild=False,
        progress=None,
    ):
        registration = registry.providers.get(provider_id)
        if registration is None:
            raise ValueError(f"Unknown morphology provider: {provider_id}")
        if "analyze" not in registration.manifest["capabilities"]:
            raise ValueError(f"Provider does not support morphology analysis: {provider_id}")
        provider = registration.load()
        analyze_complete = getattr(provider, "analyze_complete", None)
        if not callable(analyze_complete):
            raise ValueError(
                f"{provider_id} cannot build a complete dialogue morphology index"
            )
        identity, fingerprint = provider_identity(registration, provider)
        metadata = {
            "id": provider_id,
            "version": registration.manifest["version"],
            "source": registration.manifest["source"],
            "license": registration.manifest["license"],
            "identity": identity,
        }

        with self.dialogues.request_context(dialogue, text_version) as context:
            with closing(self._connect(create=True)) as db:
                build_id = self._prepare_build(
                    db,
                    context,
                    provider_id,
                    registration.manifest["version"],
                    fingerprint,
                    metadata,
                    rebuild,
                )
                existing = self._snapshot(db, context, build_id)
                if existing["state"] == "ready" and not rebuild:
                    return existing
                pending = db.execute(
                    "SELECT morphology_forms.id, morphology_forms.form, "
                    "morphology_forms.lookup_key FROM morphology_build_forms "
                    "JOIN morphology_forms "
                    "ON morphology_forms.id = morphology_build_forms.morphology_form_id "
                    "WHERE morphology_build_forms.morphology_build_id = ? "
                    "AND morphology_forms.status IN ('pending', 'failed') "
                    "ORDER BY morphology_build_forms.ordinal",
                    (build_id,),
                ).fetchall()
                for position, row in enumerate(pending, 1):
                    try:
                        records = analyze_complete(row["form"])
                        self._validate_records(records, row["lookup_key"], provider_id)
                    except PROVIDER_ERRORS as error:
                        with db:
                            db.execute(
                                "UPDATE morphology_forms SET status = 'failed', error = ?, "
                                "analyzed_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (f"{type(error).__name__}: {error}", row["id"]),
                            )
                            db.execute(
                                "UPDATE morphology_builds SET state = 'failed', "
                                "completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (build_id,),
                            )
                        raise MorphologyBuildError(
                            f"{provider_id} failed while analyzing {row['form']}: "
                            f"{type(error).__name__}: {error}"
                        ) from error
                    with db:
                        db.execute(
                            "DELETE FROM morphology_analyses WHERE morphology_form_id = ?",
                            (row["id"],),
                        )
                        for record in records:
                            analysis = record["analysis"]
                            db.execute(
                                "INSERT INTO morphology_analyses "
                                "(morphology_form_id, lemma_key, headword, homograph, "
                                "record_identity, record) VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    row["id"],
                                    key(record["lemma"]),
                                    analysis["headword"],
                                    analysis.get("homograph"),
                                    _record_identity(record),
                                    _encoded(record),
                                ),
                            )
                        db.execute(
                            "UPDATE morphology_forms SET status = ?, error = NULL, "
                            "analyzed_at = CURRENT_TIMESTAMP WHERE id = ?",
                            ("analyzed" if records else "unresolved", row["id"]),
                        )
                    if progress is not None:
                        progress(position, len(pending), row["form"], bool(records))

                snapshot = self._snapshot(db, context, build_id)
                state = (
                    "ready"
                    if snapshot["pending_forms"] == 0
                    and snapshot["failed_forms"] == 0
                    else "failed"
                )
                with db:
                    db.execute(
                        "UPDATE morphology_builds SET state = ?, "
                        "completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (state, build_id),
                    )
                return self._snapshot(db, context, build_id)

    def _connect(self, create=False):
        if not self.path.exists() and not create:
            return None
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        if create:
            self._ensure_schema(db)
        elif db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'morphology_builds'"
        ).fetchone() is None:
            db.close()
            return None
        return db

    @staticmethod
    def _ensure_schema(db):
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS morphology_builds (
                id INTEGER PRIMARY KEY,
                dialogue TEXT NOT NULL,
                text_version TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                provider_version TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                provider_fingerprint TEXT NOT NULL,
                provider_metadata TEXT NOT NULL,
                state TEXT NOT NULL
                    CHECK (state IN ('building', 'ready', 'failed')),
                total_forms INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                UNIQUE (
                    dialogue, text_version, policy_version, provider_fingerprint
                )
            );
            CREATE INDEX IF NOT EXISTS morphology_builds_ready
                ON morphology_builds(
                    dialogue, text_version, provider_id, state, completed_at
                );
            CREATE TABLE IF NOT EXISTS morphology_forms (
                id INTEGER PRIMARY KEY,
                provider_id TEXT NOT NULL,
                provider_version TEXT NOT NULL,
                provider_fingerprint TEXT NOT NULL,
                form TEXT NOT NULL,
                lookup_key TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK (status IN ('pending', 'analyzed', 'unresolved', 'failed')),
                error TEXT,
                analyzed_at TEXT,
                UNIQUE (provider_fingerprint, lookup_key)
            );
            CREATE INDEX IF NOT EXISTS morphology_forms_lookup
                ON morphology_forms(provider_fingerprint, lookup_key);
            CREATE TABLE IF NOT EXISTS morphology_build_forms (
                morphology_build_id INTEGER NOT NULL
                    REFERENCES morphology_builds(id) ON DELETE CASCADE,
                morphology_form_id INTEGER NOT NULL
                    REFERENCES morphology_forms(id),
                ordinal INTEGER NOT NULL,
                PRIMARY KEY (morphology_build_id, morphology_form_id),
                UNIQUE (morphology_build_id, ordinal)
            );
            CREATE INDEX IF NOT EXISTS morphology_build_forms_form
                ON morphology_build_forms(morphology_form_id, morphology_build_id);
            CREATE TABLE IF NOT EXISTS morphology_analyses (
                id INTEGER PRIMARY KEY,
                morphology_form_id INTEGER NOT NULL
                    REFERENCES morphology_forms(id) ON DELETE CASCADE,
                lemma_key TEXT NOT NULL,
                headword TEXT NOT NULL,
                homograph TEXT,
                record_identity TEXT NOT NULL,
                record TEXT NOT NULL,
                UNIQUE (morphology_form_id, record_identity)
            );
            CREATE INDEX IF NOT EXISTS morphology_analyses_lemma
                ON morphology_analyses(lemma_key, morphology_form_id);
            CREATE TABLE IF NOT EXISTS morphology_corrections (
                id INTEGER PRIMARY KEY,
                dialogue TEXT NOT NULL,
                text_version TEXT NOT NULL,
                form_key TEXT NOT NULL,
                lemma_key TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('add', 'exclude')),
                analysis_identity TEXT,
                record TEXT,
                reason TEXT NOT NULL,
                source TEXT NOT NULL,
                reviewed_by TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (
                    (action = 'add' AND analysis_identity IS NULL AND record IS NOT NULL)
                    OR
                    (action = 'exclude' AND analysis_identity IS NOT NULL AND record IS NULL)
                )
            );
            CREATE INDEX IF NOT EXISTS morphology_corrections_lookup
                ON morphology_corrections(dialogue, text_version, form_key, lemma_key);
            """
        )
        current = db.execute(
            "SELECT value FROM metadata WHERE name = 'schema_version'"
        ).fetchone()
        if current is not None and int(current["value"]) != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported morphology database schema: {current['value']}"
            )
        policy = db.execute(
            "SELECT value FROM metadata WHERE name = 'policy_version'"
        ).fetchone()
        if policy is not None and policy["value"] != POLICY_VERSION:
            raise ValueError(
                f"Unsupported morphology database policy: {policy['value']}"
            )
        with db:
            db.execute(
                "INSERT OR IGNORE INTO metadata(name, value) VALUES "
                "('schema_version', ?), ('policy_version', ?)",
                (str(SCHEMA_VERSION), POLICY_VERSION),
            )

    @staticmethod
    def _prepare_build(
        db,
        context,
        provider_id,
        provider_version,
        fingerprint,
        metadata,
        rebuild,
    ):
        row = db.execute(
            "SELECT id, state FROM morphology_builds WHERE dialogue = ? "
            "AND text_version = ? AND policy_version = ? "
            "AND provider_fingerprint = ?",
            (
                context.dialogue,
                context.text_version,
                POLICY_VERSION,
                fingerprint,
            ),
        ).fetchone()
        if row is not None and row["state"] == "ready" and not rebuild:
            return row["id"]
        with db:
            if row is not None and rebuild:
                db.execute("DELETE FROM morphology_builds WHERE id = ?", (row["id"],))
                row = None
            if row is None:
                cursor = db.execute(
                    "INSERT INTO morphology_builds "
                    "(dialogue, text_version, provider_id, provider_version, "
                    "policy_version, provider_fingerprint, provider_metadata, "
                    "state, total_forms) VALUES (?, ?, ?, ?, ?, ?, ?, 'building', 0)",
                    (
                        context.dialogue,
                        context.text_version,
                        provider_id,
                        provider_version,
                        POLICY_VERSION,
                        fingerprint,
                        _encoded(metadata),
                    ),
                )
                build_id = cursor.lastrowid
                forms = context.db.execute(
                    "SELECT canonical_forms.surface, canonical_forms.lookup_key "
                    "FROM tokens "
                    "JOIN canonical_forms ON canonical_forms.id = tokens.form_id "
                    "JOIN ("
                    "SELECT canonical_forms.lookup_key, MIN(tokens.id) AS first_id "
                    "FROM tokens "
                    "JOIN canonical_forms ON canonical_forms.id = tokens.form_id "
                    "WHERE tokens.build_id = ? "
                    "GROUP BY canonical_forms.lookup_key"
                    ") distinct_forms ON tokens.id = distinct_forms.first_id "
                    "ORDER BY tokens.id",
                    (context.build_id,),
                ).fetchall()
                db.executemany(
                    "INSERT OR IGNORE INTO morphology_forms "
                    "(provider_id, provider_version, provider_fingerprint, "
                    "form, lookup_key, status) "
                    "VALUES (?, ?, ?, ?, ?, 'pending')",
                    [
                        (
                            provider_id,
                            provider_version,
                            fingerprint,
                            form["surface"],
                            form["lookup_key"],
                        )
                        for form in forms
                    ],
                )
                form_ids = {}
                lookup_keys = [form["lookup_key"] for form in forms]
                for start in range(0, len(lookup_keys), 400):
                    group = lookup_keys[start:start + 400]
                    placeholders = ",".join("?" for _ in group)
                    form_ids.update(
                        {
                            form["lookup_key"]: form["id"]
                            for form in db.execute(
                                "SELECT id, lookup_key FROM morphology_forms "
                                "WHERE provider_fingerprint = ? "
                                f"AND lookup_key IN ({placeholders})",
                                [fingerprint, *group],
                            )
                        }
                    )
                db.executemany(
                    "INSERT INTO morphology_build_forms "
                    "(morphology_build_id, morphology_form_id, ordinal) "
                    "VALUES (?, ?, ?)",
                    [
                        (build_id, form_ids[form["lookup_key"]], ordinal)
                        for ordinal, form in enumerate(forms)
                    ],
                )
                db.execute(
                    "UPDATE morphology_builds SET total_forms = ? WHERE id = ?",
                    (len(forms), build_id),
                )
            else:
                build_id = row["id"]
                db.execute(
                    "UPDATE morphology_builds SET state = 'building', completed_at = NULL "
                    "WHERE id = ?",
                    (build_id,),
                )
        return build_id

    @staticmethod
    def _validate_records(records, lookup_key, provider_id):
        if not isinstance(records, list):
            raise ValueError("Provider returned an invalid complete analysis")
        for record in records:
            if (
                not isinstance(record, dict)
                or record.get("provider") != provider_id
                or not isinstance(record.get("form"), str)
                or key(record.get("form", "")) != lookup_key
                or not isinstance(record.get("lemma"), str)
                or not record["lemma"]
                or not isinstance(record.get("analysis"), dict)
                or not isinstance(record["analysis"].get("headword"), str)
                or not record["analysis"]["headword"]
            ):
                raise ValueError("Provider returned an invalid morphology record")

    def latest(self, context, provider_id=None):
        db = self._connect()
        if db is None:
            return None
        with closing(db):
            parameters = [
                context.dialogue,
                context.text_version,
                POLICY_VERSION,
            ]
            provider_clause = ""
            if provider_id is not None:
                provider_clause = " AND provider_id = ?"
                parameters.append(provider_id)
            row = db.execute(
                "SELECT id FROM morphology_builds WHERE dialogue = ? "
                "AND text_version = ? AND policy_version = ? AND state = 'ready'"
                + provider_clause
                + " ORDER BY completed_at DESC, id DESC LIMIT 1",
                parameters,
            ).fetchone()
            return None if row is None else self._snapshot(db, context, row["id"])

    def snapshot(self, context, build_id):
        db = self._connect()
        if db is None:
            raise ValueError("Morphology database does not exist")
        with closing(db):
            return self._snapshot(db, context, build_id)

    @staticmethod
    def _snapshot(db, context, build_id):
        row = db.execute(
            "SELECT * FROM morphology_builds WHERE id = ? AND dialogue = ? "
            "AND text_version = ?",
            (build_id, context.dialogue, context.text_version),
        ).fetchone()
        if row is None:
            raise ValueError("Morphology build does not belong to this dialogue text")
        counts = dict(
            db.execute(
                "SELECT morphology_forms.status, COUNT(*) "
                "FROM morphology_build_forms "
                "JOIN morphology_forms "
                "ON morphology_forms.id = morphology_build_forms.morphology_form_id "
                "WHERE morphology_build_forms.morphology_build_id = ? "
                "GROUP BY morphology_forms.status",
                (build_id,),
            ).fetchall()
        )
        analyzed = counts.get("analyzed", 0)
        unresolved = counts.get("unresolved", 0)
        failed = counts.get("failed", 0)
        pending = counts.get("pending", 0)
        return {
            "build_id": build_id,
            "provider": row["provider_id"],
            "provider_version": row["provider_version"],
            "provider_fingerprint": row["provider_fingerprint"],
            "provider_metadata": json.loads(row["provider_metadata"]),
            "state": row["state"],
            "total_forms": row["total_forms"],
            "checked_forms": analyzed + unresolved,
            "analyzed_forms": analyzed,
            "unresolved_forms": unresolved,
            "failed_forms": failed,
            "pending_forms": pending,
            "whole_dialogue_complete": (
                row["state"] == "ready"
                and analyzed + unresolved == row["total_forms"]
                and failed == 0
                and pending == 0
            ),
            "context_reviewed": False,
            "storage": "shipped_morphology_database",
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }

    def form_records(self, context, build_id, form):
        db = self._connect()
        if db is None:
            return []
        form_key = key(form)
        with closing(db):
            rows = db.execute(
                "SELECT morphology_analyses.record_identity, "
                "morphology_analyses.record FROM morphology_analyses "
                "JOIN morphology_build_forms "
                "ON morphology_build_forms.morphology_form_id = "
                "morphology_analyses.morphology_form_id "
                "JOIN morphology_forms "
                "ON morphology_forms.id = morphology_build_forms.morphology_form_id "
                "WHERE morphology_build_forms.morphology_build_id = ? "
                "AND morphology_forms.lookup_key = ? ORDER BY morphology_analyses.id",
                (build_id, form_key),
            ).fetchall()
            return self._apply_corrections(
                db, context, rows, form_key=form_key
            )

    def lemma_records(self, context, build_id, lemma, identities=None):
        db = self._connect()
        if db is None:
            return []
        lemma_key = key(lemma)
        with closing(db):
            rows = db.execute(
                "SELECT morphology_analyses.record_identity, "
                "morphology_analyses.record FROM morphology_analyses "
                "JOIN morphology_build_forms "
                "ON morphology_build_forms.morphology_form_id = "
                "morphology_analyses.morphology_form_id "
                "WHERE morphology_build_forms.morphology_build_id = ? "
                "AND morphology_analyses.lemma_key = ? "
                "ORDER BY morphology_build_forms.ordinal, "
                "morphology_analyses.id",
                (build_id, lemma_key),
            ).fetchall()
            records = self._apply_corrections(
                db, context, rows, lemma_key=lemma_key
            )
            return [
                record
                for record in records
                if identities is None
                or (
                    record["analysis"]["headword"],
                    record["analysis"].get("homograph"),
                )
                in identities
            ]

    @staticmethod
    def _apply_corrections(db, context, rows, form_key=None, lemma_key=None):
        clauses = ["dialogue = ?", "text_version = ?"]
        parameters = [context.dialogue, context.text_version]
        if form_key is not None:
            clauses.append("form_key = ?")
            parameters.append(form_key)
        if lemma_key is not None:
            clauses.append("lemma_key = ?")
            parameters.append(lemma_key)
        corrections = db.execute(
            "SELECT action, analysis_identity, record FROM morphology_corrections "
            f"WHERE {' AND '.join(clauses)} ORDER BY id",
            parameters,
        ).fetchall()
        excluded = {
            row["analysis_identity"]
            for row in corrections
            if row["action"] == "exclude"
        }
        records = [
            json.loads(row["record"])
            for row in rows
            if row["record_identity"] not in excluded
        ]
        records.extend(
            json.loads(row["record"])
            for row in corrections
            if row["action"] == "add"
        )
        return records

    def add_correction(
        self,
        dialogue,
        text_version,
        form,
        action,
        reason,
        source,
        reviewed_by,
        record=None,
        analysis_identity=None,
    ):
        if action not in {"add", "exclude"}:
            raise ValueError("Correction action must be add or exclude")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (reason, source, reviewed_by)
        ):
            raise ValueError("Correction review fields must be nonempty text")
        if action == "add":
            if not isinstance(record, dict):
                raise ValueError("Added correction requires a morphology record")
            self._validate_records([record], key(form), record.get("provider", ""))
            lemma_key = key(record["lemma"])
            stored_record = _encoded(record)
            stored_identity = None
        else:
            if not isinstance(analysis_identity, str) or not analysis_identity:
                raise ValueError("Excluded analysis requires an identity")
            if record is not None:
                raise ValueError("Excluded analysis cannot include a replacement record")
            stored_record = None
            stored_identity = analysis_identity
        with closing(self._connect(create=True)) as db:
            if action == "exclude":
                row = db.execute(
                    "SELECT morphology_analyses.lemma_key FROM morphology_analyses "
                    "JOIN morphology_build_forms "
                    "ON morphology_build_forms.morphology_form_id = "
                    "morphology_analyses.morphology_form_id "
                    "JOIN morphology_builds "
                    "ON morphology_builds.id = "
                    "morphology_build_forms.morphology_build_id "
                    "JOIN morphology_forms "
                    "ON morphology_forms.id = morphology_build_forms.morphology_form_id "
                    "WHERE morphology_builds.dialogue = ? "
                    "AND morphology_builds.text_version = ? "
                    "AND morphology_forms.lookup_key = ? "
                    "AND morphology_analyses.record_identity = ?",
                    (dialogue, text_version, key(form), analysis_identity),
                ).fetchone()
                if row is None:
                    raise ValueError("Excluded analysis does not exist in this dialogue")
                lemma_key = row["lemma_key"]
            with db:
                db.execute(
                    "INSERT INTO morphology_corrections "
                    "(dialogue, text_version, form_key, lemma_key, action, "
                    "analysis_identity, record, reason, source, reviewed_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        dialogue,
                        text_version,
                        key(form),
                        lemma_key,
                        action,
                        stored_identity,
                        stored_record,
                        reason.strip(),
                        source.strip(),
                        reviewed_by.strip(),
                    ),
                )

    def compact(self):
        db = self._connect()
        if db is not None:
            with closing(db) as db:
                db.execute("VACUUM")
