"""Bounded canonical occurrence checks through the local ikelos provider."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platosi.cancellation import Cancellation, Cancelled
from platosi.canonical_text import (
    DATA,
    make_work,
    segment_digest,
    sections_from_segments,
    text_version,
)
from platosi.occurrence_check import OccurrenceCheck
from platosi.reader_api import InvalidRequest, ReaderApi
from tests.test_morpheus import MorpheusFixture


class OccurrenceCheckTests(MorpheusFixture):
    def setUp(self):
        super().setUp()
        self.registry.set_enabled("morpheus", True)
        self.text = "ἀπῇμεν κατέβην κατέβην Πολεμάρχου ξξξξξ ἄπειμι"
        segments = [{
            "stephanus": "327b",
            "division": {"type": "book", "label": "1"},
            "text": self.text,
            "annotations": [],
        }]
        sections = sections_from_segments(segments)
        version = text_version("fixture", sections)
        entry = {
            "dialogue": "fixture",
            "tlg": "tlg030",
            "edition": "perseus-grc2",
            "title": "Fixture",
            "title_greek": None,
            "text_version": version,
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
        self.api = ReaderApi(self.root)
        self.addCleanup(self.api.close)
        self.location = {
            "dialogue": "fixture",
            "text_version": version,
            "start": {"stephanus": "327b", "offset": 0},
            "end": {"stephanus": "327b", "offset": len("ἀπῇμεν")},
        }

    def execute(self, forms=None, maximum=0, **extra):
        payload = {
            "location": self.location,
            "provider": "morpheus",
            "forms": forms or [],
            "max_new_forms": maximum,
            **extra,
        }
        with patch("platosi.reader_api.Registry", return_value=self.registry):
            return self.api.execute("linguistics.verify-occurrences", payload)

    def test_zero_budget_leaves_forms_explicitly_unchecked(self):
        result = self.execute(["κατέβην", "Πολεμάρχου"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["readings"], [])
        self.assertEqual(result["coverage"]["checked_forms"], 0)
        self.assertEqual(result["coverage"]["candidate_tokens"], 4)
        self.assertEqual(
            {check["status"] for check in result["form_checks"]},
            {"unchecked"},
        )

    def test_bounded_analysis_preserves_identity_and_ambiguity(self):
        result = self.execute(["κατέβην", "Πολεμάρχου"], maximum=3)
        self.assertEqual(result["status"], "checked")
        self.assertEqual(result["coverage"]["checked_forms"], 3)
        selected = result["readings"][0]
        self.assertEqual(selected["headword"], "ἄπειμι2")
        self.assertEqual(selected["count"], 1)
        descent = next(
            check for check in result["form_checks"] if check["form"] == "κατέβην"
        )
        self.assertEqual(descent["status"], "different_reading")
        self.assertGreaterEqual(len(descent["analyses"]), 2)

    def test_selected_form_occurrences_do_not_double_count_readings(self):
        start = self.text.index("κατέβην")
        self.location = {
            **self.location,
            "start": {"stephanus": "327b", "offset": start},
            "end": {
                "stephanus": "327b",
                "offset": start + len("κατέβην"),
            },
        }
        result = self.execute(maximum=1)
        self.assertEqual(result["status"], "checked")
        self.assertEqual(len(result["readings"]), 1)
        self.assertEqual(result["readings"][0]["count"], 2)
        self.assertEqual(
            len(result["readings"][0]["forms"][0]["evidence"]),
            2,
        )

    def test_no_analysis_differs_from_unchecked(self):
        result = self.execute(["ξξξξξ", "Πολεμάρχου"], maximum=2)
        statuses = {
            check["form"]: check["status"]
            for check in result["form_checks"]
        }
        self.assertEqual(statuses, {
            "ἀπῇμεν": "compatible",
            "ξξξξξ": "no_analysis",
            "Πολεμάρχου": "unchecked",
        })
        self.assertIn("do not establish absence", result["limitations"])

    def test_normal_dialogue_lookup_does_not_use_bounded_analyzer(self):
        with patch("platosi.reader_api.Registry", return_value=self.registry):
            result = self.api.execute(
                "linguistics.dialogue-lexicon",
                {"location": self.location},
            )
        self.assertEqual(result["lemmas"], [])
        self.assertEqual(result["coverage"]["morphology_indexes"], [])
        self.assertTrue(
            any(
                "No completed local dialogue morphology index" in warning
                for warning in result["warnings"]
            )
        )

    def test_invalid_requests_provider_failures_and_cancellation(self):
        for change in (
            {"provider": "missing"},
            {"forms": ["word"]},
            {"forms": ["λόγος"] * 51},
            {"max_new_forms": -1},
            {"extra": True},
        ):
            with self.subTest(change=change):
                with self.assertRaises(InvalidRequest):
                    self.execute(**change)
        with patch.object(
            self.provider,
            "analyze",
            side_effect=RuntimeError("analysis failed"),
        ):
            result = self.execute(maximum=1)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(
            any("analysis failed" in warning for warning in result["warnings"])
        )

        class Stop:
            def check(self):
                raise Cancelled("stop")

        with self.assertRaises(Cancelled):
            OccurrenceCheck(self.root).run(
                self.registry,
                {
                    "location": self.location,
                    "provider": "morpheus",
                    "forms": [],
                    "max_new_forms": 1,
                },
                Stop(),
            )


if __name__ == "__main__":
    unittest.main()
