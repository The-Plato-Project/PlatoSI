import hashlib
import json
import struct
import unicodedata
import unittest
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "text-location-v1.json"


def lp(value):
    encoded = value.encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded


def sections_from_fixture(fixture):
    sections = []
    seen = set()
    for section in fixture["sections"]:
        reference = section["stephanus"]
        text = "\n".join(section["segments"])
        if not reference or reference in seen or not text:
            raise ValueError("Invalid fixture section")
        if unicodedata.normalize("NFC", text) != text:
            raise ValueError("Non-NFC fixture section")
        text.encode("utf-8")
        seen.add(reference)
        sections.append((reference, text))
    return sections


def fingerprint(fixture, sections):
    data = lp(fixture["contract"]) + lp(fixture["dialogue"]) + struct.pack(">I", len(sections))
    data += b"".join(lp(reference) + lp(text) for reference, text in sections)
    return "sha256:" + hashlib.sha256(data).hexdigest()


def index_at_utf16(text, offset):
    if type(offset) is not int or offset < 0:
        raise ValueError("INVALID_OFFSET")
    data = text.encode("utf-16-le")
    if offset * 2 > len(data):
        raise ValueError("INVALID_OFFSET")
    try:
        return len(data[:offset * 2].decode("utf-16-le"))
    except UnicodeDecodeError as error:
        raise ValueError("INVALID_OFFSET") from error


def resolve(fixture, sections, case):
    if case.get("dialogue", fixture["dialogue"]) != fixture["dialogue"]:
        raise ValueError("UNKNOWN_DIALOGUE")
    if case.get("text_version", fixture["text_version"]) != fingerprint(fixture, sections):
        raise ValueError("VERSION_MISMATCH")
    indices = {reference: index for index, (reference, _) in enumerate(sections)}
    if case["start"][0] not in indices or case["end"][0] not in indices:
        raise ValueError("UNKNOWN_REFERENCE")
    start_section = indices[case["start"][0]]
    end_section = indices[case["end"][0]]
    start = index_at_utf16(sections[start_section][1], case["start"][1])
    end = index_at_utf16(sections[end_section][1], case["end"][1])
    if start_section > end_section or (start_section == end_section and start > end):
        raise ValueError("REVERSED_RANGE")
    if start_section == end_section:
        return sections[start_section][1][start:end]
    parts = [sections[start_section][1][start:]]
    parts.extend(text for _, text in sections[start_section + 1:end_section])
    parts.append(sections[end_section][1][:end])
    return "\n".join(parts)


class TextLocationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.sections = sections_from_fixture(cls.fixture)

    def test_fingerprint(self):
        self.assertEqual(fingerprint(self.fixture, self.sections), self.fixture["text_version"])
        changed = list(self.sections)
        changed[0] = (changed[0][0], changed[0][1] + "!")
        self.assertNotEqual(fingerprint(self.fixture, changed), self.fixture["text_version"])

    def test_valid_ranges(self):
        for case in self.fixture["valid"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(resolve(self.fixture, self.sections, case), case["text"])

    def test_invalid_ranges(self):
        for case in self.fixture["invalid"]:
            with self.subTest(case=case["name"]):
                with self.assertRaisesRegex(ValueError, "^" + case["error"] + "$"):
                    resolve(self.fixture, self.sections, case)

    def test_rejects_noncanonical_sections(self):
        for sections in (
            [{"stephanus": "327a", "segments": ["α\u0301"]}],
            [{"stephanus": "327a", "segments": ["a"]},
             {"stephanus": "327a", "segments": ["b"]}],
        ):
            with self.subTest(sections=sections):
                with self.assertRaises(ValueError):
                    sections_from_fixture({"sections": sections})


if __name__ == "__main__":
    unittest.main()
