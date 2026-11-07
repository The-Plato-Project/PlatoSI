"""Bounded source-specific morphology checks at exact canonical occurrences."""

import sqlite3
import unicodedata

from platosi.canonical_text import CanonicalCorpus, LocationError
from platosi.dialogue_lexicon import DialogueLexiconIndex
from platosi.unicode_search import key


MAX_FORMS = 50
MAX_NEW_FORMS = 20
MAX_TOKENS = 500


class OccurrenceCheckRequestError(ValueError):
    pass


def greek_form(value):
    return (isinstance(value, str) and 0 < len(value) <= 200
            and any(unicodedata.category(char).startswith("L") for char in value)
            and all(unicodedata.category(char).startswith("M")
                    or (unicodedata.category(char).startswith("L") and "GREEK" in unicodedata.name(char, ""))
                    for char in value))


def validate_analyses(records, form, provider_id):
    if not isinstance(records, list):
        raise ValueError("Provider returned invalid analyses")
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get("provider") != provider_id
            or key(record.get("form", "")) != form
            or not greek_form(record.get("lemma"))
        ):
            raise ValueError(
                "Provider returned an analysis outside the requested word or provider"
            )
        analysis = record.get("analysis")
        if (
            not isinstance(analysis, dict)
            or not isinstance(analysis.get("headword"), str)
            or not analysis["headword"].strip()
            or not (
                analysis.get("homograph") is None
                or isinstance(analysis.get("homograph"), str)
            )
        ):
            raise ValueError(
                "Occurrence checks require explicit source headword identity"
            )
    return records


class OccurrenceCheck:
    def __init__(self, root):
        self.root = root


    def run(self, registry, payload, cancellation):
        if set(payload) - {"location", "provider", "forms", "max_new_forms"}:
            raise OccurrenceCheckRequestError("Unexpected occurrence-check fields")
        provider_id = payload.get("provider")
        if not isinstance(provider_id, str) or not provider_id:
            raise OccurrenceCheckRequestError("Select an occurrence-check provider")
        registration = registry.providers.get(provider_id)
        if (
            registration is None
            or not registration.enabled
            or "analyze" not in registration.manifest["capabilities"]
        ):
            raise OccurrenceCheckRequestError(
                "Provider must be enabled and support analyze"
            )
        maximum = payload.get("max_new_forms", 0)
        if type(maximum) is not int or not 0 <= maximum <= MAX_NEW_FORMS:
            raise OccurrenceCheckRequestError(f"max_new_forms must be an integer from 0 to {MAX_NEW_FORMS}")
        supplied = payload.get("forms", [])
        if not isinstance(supplied, list) or len(supplied) > MAX_FORMS or any(not greek_form(form) for form in supplied):
            raise OccurrenceCheckRequestError(f"forms must contain at most {MAX_FORMS} Greek words")
        try:
            target = CanonicalCorpus(self.root).resolve(payload.get("location"))
        except LocationError as error:
            raise OccurrenceCheckRequestError(str(error)) from error
        if not greek_form(target["text"]):
            raise OccurrenceCheckRequestError("location must select exactly one Greek word")
        forms = list(dict.fromkeys(key(form) for form in [target["text"], *supplied]))
        if len(forms) > MAX_FORMS:
            raise OccurrenceCheckRequestError(f"At most {MAX_FORMS} distinct forms including the selected word")
        location = target["location"]
        index = DialogueLexiconIndex(self.root)
        with index.request_context(location["dialogue"], location["text_version"]) as context:
            placeholders = ",".join("?" for _ in forms)
            rows = context.db.execute(
                "SELECT canonical_forms.lookup_key, COUNT(*) FROM tokens "
                "JOIN canonical_forms ON canonical_forms.id = tokens.form_id "
                "WHERE tokens.build_id = ? "
                f"AND canonical_forms.lookup_key IN ({placeholders}) "
                "GROUP BY canonical_forms.lookup_key",
                [context.build_id, *forms],
            ).fetchall()
            counts = dict(rows)
            if set(counts) != set(forms):
                raise OccurrenceCheckRequestError("Every requested form must occur exactly as spelled in the selected dialogue")
            if sum(counts.values()) > MAX_TOKENS:
                raise OccurrenceCheckRequestError(f"Bounded checks support at most {MAX_TOKENS} canonical occurrences")
            total_forms = context.db.execute(
                "SELECT COUNT(DISTINCT canonical_forms.lookup_key) FROM tokens "
                "JOIN canonical_forms ON canonical_forms.id = tokens.form_id "
                "WHERE tokens.build_id = ?",
                (context.build_id,),
            ).fetchone()[0]
            provider = registration.load()
            if not provider.available():
                raise OccurrenceCheckRequestError("Occurrence-check provider is unavailable")
            warnings = []
            snapshot = {}
            attempted = 0
            for form in forms:
                cancellation.check()
                if attempted >= maximum:
                    continue
                attempted += 1
                try:
                    snapshot[form] = validate_analyses(
                        provider.analyze(form, "exact", 1000),
                        form,
                        provider_id,
                    )
                except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
                    warnings.append(f"{provider_id}: analysis failed for {form}: {type(error).__name__}: {error}")
            cancellation.check()
            selected = snapshot.get(key(target["text"]))
            selected_records = selected if selected is not None else []
            identities = {}
            for record in selected_records:
                analysis = record["analysis"]
                identity = (analysis["headword"], analysis.get("homograph"))
                identities.setdefault(identity, record)
            readings = []
            for identity, selected_record in identities.items():
                compatible = [record for records in snapshot.values() for record in records
                              if (record["analysis"]["headword"], record["analysis"].get("homograph")) == identity]
                observed = index.observed_records(location["dialogue"], location["text_version"], compatible, context=context)
                readings.append({"lemma": selected_record["lemma"], "headword": identity[0], "homograph": identity[1],
                                 "count": sum(item["count"] for item in observed), "forms": observed})
            checks = []
            for form in forms:
                item = snapshot.get(form)
                records = item if item is not None else []
                if item is None:
                    status = "unchecked"
                elif not records:
                    status = "no_analysis"
                elif not identities:
                    status = "selected_reading_unknown"
                elif any((r["analysis"]["headword"], r["analysis"].get("homograph")) in identities for r in records):
                    status = "compatible"
                else:
                    status = "different_reading"
                checks.append({
                    "form": form,
                    "count": counts[form],
                    "status": status,
                    "analyses": records,
                })
            pending = [form for form in forms if form not in snapshot]
            return {
                "contract": "platosi.occurrence-check.v1", "target": target,
                "provider": {"id": provider_id, "version": registration.manifest["version"],
                             "source": registration.manifest["source"], "config": registration.manifest.get("config", {})},
                "status": "partial" if pending else "checked" if identities else "no_selected_analysis",
                "readings": readings, "form_checks": checks,
                "coverage": {"requested_forms": len(forms), "checked_forms": len(snapshot), "pending_forms": pending,
                             "candidate_tokens": sum(counts.values()),
                             "checked_tokens": sum(counts[form] for form in snapshot),
                             "total_dialogue_forms": total_forms,
                             "whole_dialogue_complete": not pending and len(forms) == total_forms,
                             "context_reviewed": False, "new_lookup_attempts": attempted},
                "warnings": warnings,
                "limitations": "Source-specific possible readings of supplied canonical forms only. "
                                "Compatible morphology does not identify the contextual meaning or referent. "
                                "Unchecked forms and no-analysis results do not establish absence. "
                                "Homographs remain separate; no lexical equivalence is inferred.",
            }
