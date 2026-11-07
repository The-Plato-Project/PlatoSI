"""Permanent PlatoSI morphology builds from the in-process ikelos provider."""

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platosi.canonical_text import (
    DATA,
    make_work,
    segment_digest,
    sections_from_segments,
    text_version,
)
from platosi.dialogue_lexicon import DialogueLexiconIndex
from platosi.dialogue_morphology import DialogueMorphologyIndex, MorphologyBuildError
from platosi.reader_api import ReaderApi
from platosi.registry import Registry


class DialogueMorphologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(
            ROOT / "plugins" / "morpheus",
            self.root / "plugins" / "morpheus",
        )
        self.registry = Registry(self.root)
        self.addCleanup(self.registry.close)
        self.registry.set_enabled("morpheus", True)
        self.provider = self.registry.providers["morpheus"].load()
        self.text = "κατέβην ξξξξξ κατέβην"
        segments = [{
            "stephanus": "327a",
            "division": {"type": "book", "label": "1"},
            "text": self.text,
            "annotations": [],
        }]
        sections = sections_from_segments(segments)
        self.version = text_version("fixture", sections)
        entry = {
            "dialogue": "fixture",
            "tlg": "tlg030",
            "edition": "perseus-grc2",
            "title": "Fixture",
            "title_greek": None,
            "text_version": self.version,
            "segments_sha256": segment_digest(segments),
        }
        inventory = {
            "contract": "platosi.location.v1",
            "source_repository": "fixture",
            "source_revision": "test",
            "works": [entry],
        }
        inventory_path = (
            self.root / "docs" / "canonical-corpus-v1-inventory.json"
        )
        inventory_path.parent.mkdir()
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
        work_path = self.root / DATA / "works" / "fixture.json"
        work_path.parent.mkdir(parents=True)
        work_path.write_text(
            json.dumps(
                make_work(inventory, entry, segments),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.index = DialogueMorphologyIndex(self.root)

    def test_build_persists_all_readings_in_compact_database(self):
        with patch.object(
            self.provider,
            "analyze_complete",
            wraps=self.provider.analyze_complete,
        ) as analyze:
            first = self.index.build(self.registry, "fixture", self.version)
            self.assertEqual(analyze.call_count, 2)
            second = self.index.build(self.registry, "fixture", self.version)
            self.assertEqual(analyze.call_count, 2)
        self.assertEqual(first["state"], "ready")
        self.assertEqual(first["total_forms"], 2)
        self.assertEqual(first["analyzed_forms"], 1)
        self.assertEqual(first["unresolved_forms"], 1)
        self.assertTrue(first["whole_dialogue_complete"])
        self.assertEqual(second["build_id"], first["build_id"])
        self.assertTrue(self.index.path.is_file())

        with DialogueLexiconIndex(self.root).request_context(
            "fixture", self.version
        ) as context:
            records = self.index.lemma_records(
                context, first["build_id"], "καταβαίνω"
            )
            self.assertEqual(len(records), 2)
            observed = DialogueLexiconIndex(self.root).observed_records(
                "fixture",
                self.version,
                records,
                context=context,
            )
        self.assertEqual(
            [(item["form"], item["count"]) for item in observed],
            [("κατέβην", 2)],
        )

    def test_failed_build_resumes_without_reanalyzing_completed_forms(self):
        original = self.provider.analyze_complete
        calls = []

        def fail_unknown(form):
            calls.append(form)
            if form == "ξξξξξ":
                raise OSError("analyzer stopped")
            return original(form)

        with patch.object(self.provider, "analyze_complete", side_effect=fail_unknown):
            with self.assertRaisesRegex(MorphologyBuildError, "analyzer stopped"):
                self.index.build(self.registry, "fixture", self.version)
        self.assertEqual(calls, ["κατέβην", "ξξξξξ"])

        with patch.object(
            self.provider,
            "analyze_complete",
            wraps=original,
        ) as analyze:
            resumed = self.index.build(self.registry, "fixture", self.version)
        self.assertEqual(resumed["state"], "ready")
        self.assertEqual(resumed["checked_forms"], 2)
        analyze.assert_called_once_with("ξξξξξ")

    def test_dialogue_lookup_reads_database_without_calling_ikelos(self):
        snapshot = self.index.build(self.registry, "fixture", self.version)
        location = {
            "dialogue": "fixture",
            "text_version": self.version,
            "start": {"stephanus": "327a", "offset": 0},
            "end": {"stephanus": "327a", "offset": len("κατέβην")},
        }
        api = ReaderApi(self.root)
        self.addCleanup(api.close)
        with patch.object(
            self.provider,
            "analyze_complete",
            side_effect=AssertionError("reader called analyzer"),
        ):
            result = api.execute(
                "linguistics.dialogue-lexicon",
                {"location": location},
            )
        self.assertEqual(
            [item["lemma"] for item in result["lemmas"]],
            ["καταβαίνω"],
        )
        self.assertEqual(result["lemmas"][0]["forms"][0]["count"], 2)
        self.assertEqual(
            result["coverage"]["morphology_index_providers"],
            ["morpheus"],
        )
        self.assertEqual(
            result["coverage"]["morphology_indexes"][0]["build_id"],
            snapshot["build_id"],
        )

    def test_reviewed_corrections_are_separate_overlays(self):
        snapshot = self.index.build(self.registry, "fixture", self.version)
        with DialogueLexiconIndex(self.root).request_context(
            "fixture", self.version
        ) as context:
            original = self.index.form_records(
                context, snapshot["build_id"], "κατέβην"
            )
            self.index.add_correction(
                "fixture",
                self.version,
                "κατέβην",
                "exclude",
                "Regression fixture",
                "test source",
                "reviewer",
                analysis_identity=__import__("hashlib").sha256(
                    json.dumps(
                        original[0],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            )
            corrected = self.index.form_records(
                context, snapshot["build_id"], "κατέβην"
            )
        self.assertEqual(len(corrected), len(original) - 1)


if __name__ == "__main__":
    unittest.main()
