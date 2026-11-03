"""Versioned canonical dialogue storage and Stephanus-relative locations."""

import hashlib
import json
import struct
import unicodedata
from pathlib import Path


CONTRACT = "platosi.location.v1"
INVENTORY = Path("docs/canonical-corpus-v1-inventory.json")
DATA = Path("data/canonical-text-v1")


class LocationError(ValueError):
    pass


def lp(text):
    encoded = text.encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded


def sections_from_segments(segments):
    sections = []
    seen = set()
    for segment in segments:
        reference = segment["stephanus"]
        text = segment["text"]
        division = segment["division"]
        if not isinstance(reference, str) or not reference or not isinstance(text, str) or not text:
            raise ValueError("Invalid canonical segment")
        if unicodedata.normalize("NFC", text) != text:
            raise ValueError("Canonical segment is not NFC")
        text.encode("utf-8")
        if not sections or sections[-1]["stephanus"] != reference:
            if reference in seen:
                raise ValueError(f"Noncontiguous Stephanus reference: {reference}")
            seen.add(reference)
            sections.append({"stephanus": reference, "division": division, "segments": []})
        elif sections[-1]["division"] != division:
            raise ValueError(f"Inconsistent division for {reference}")
        annotations = segment["annotations"]
        if not isinstance(annotations, list):
            raise ValueError("Invalid canonical annotations")
        for annotation in annotations:
            if annotation.get("kind") not in ("quotation", "citation"):
                raise ValueError("Invalid canonical annotation kind")
            start = python_offset(text, annotation.get("start"))
            end = python_offset(text, annotation.get("end"))
            if start >= end:
                raise ValueError("Invalid canonical annotation range")
        sections[-1]["segments"].append({"text": text, "annotations": annotations})
    if not sections:
        raise ValueError("Canonical work is empty")
    return sections


def text_version(dialogue, sections):
    digest = hashlib.sha256()
    digest.update(lp(CONTRACT))
    digest.update(lp(dialogue))
    digest.update(struct.pack(">I", len(sections)))
    for section in sections:
        digest.update(lp(section["stephanus"]))
        digest.update(lp("\n".join(segment["text"] for segment in section["segments"])))
    return "sha256:" + digest.hexdigest()


def segment_digest(segments):
    value = json.dumps(segments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def python_offset(text, offset):
    if type(offset) is not int or offset < 0:
        raise LocationError("INVALID_OFFSET: offset must be a nonnegative integer")
    encoded = text.encode("utf-16-le")
    if offset * 2 > len(encoded):
        raise LocationError("INVALID_OFFSET: offset is outside the section")
    try:
        return len(encoded[:offset * 2].decode("utf-16-le"))
    except UnicodeDecodeError as error:
        raise LocationError("INVALID_OFFSET: offset splits a surrogate pair") from error


def make_work(inventory, entry, segments):
    sections = sections_from_segments(segments)
    if segment_digest(segments) != entry["segments_sha256"]:
        raise ValueError(f"Canonical segments differ from the frozen baseline: {entry['dialogue']}")
    version = text_version(entry["dialogue"], sections)
    if version != entry["text_version"]:
        raise ValueError(f"Canonical text fingerprint differs from the frozen baseline: {entry['dialogue']}")
    source_file = f"tlg0059.{entry['tlg']}.{entry['edition']}.xml"
    return {
        "contract": CONTRACT, "dialogue": entry["dialogue"], "text_version": version,
        "title": entry["title"], "title_greek": entry["title_greek"], "author": "Plato",
        "language": "grc",
        "source": {
            "repository": inventory["source_repository"], "revision": inventory["source_revision"],
            "source_file": source_file,
            "text_id": f"urn:cts:greekLit:tlg0059.{entry['tlg']}.{entry['edition']}",
            "attribution": "Perseus Digital Library; consult the original TEI header.",
            "license": "Repository generally CC BY-SA 4.0; review individual edition rights.",
        },
        "sections": sections,
    }


class CanonicalCorpus:
    def __init__(self, root):
        self.root = Path(root)
        path = self.root / INVENTORY
        self.inventory = json.loads(path.read_text(encoding="utf-8"))
        if self.inventory.get("contract") != CONTRACT:
            raise ValueError("Unsupported canonical corpus contract")
        self.entries = {entry["dialogue"]: entry for entry in self.inventory["works"]}
        if len(self.entries) != len(self.inventory["works"]):
            raise ValueError("Duplicate dialogue in canonical corpus inventory")

    def available(self):
        return all((self.root / DATA / "works" / f"{dialogue}.json").is_file()
                   for dialogue in self.entries)

    def any_available(self):
        return any((self.root / DATA / "works" / f"{dialogue}.json").is_file()
                   for dialogue in self.entries)

    def entry(self, dialogue):
        if not isinstance(dialogue, str) or dialogue not in self.entries:
            raise LocationError("UNKNOWN_DIALOGUE: unknown dialogue")
        return self.entries[dialogue]

    def catalogue(self):
        if not self.available():
            raise FileNotFoundError("Canonical corpus is incomplete; run scripts/build-canonical-corpus.py")
        return {"contract": CONTRACT, "works": [
            {"dialogue": item["dialogue"], "title": item["title"],
             "title_greek": item["title_greek"], "author": "Plato", "language": "grc",
             "text_version": item["text_version"]} for item in self.inventory["works"]
        ]}

    def work(self, dialogue, version=None):
        entry = self.entry(dialogue)
        if version is not None and version != entry["text_version"]:
            raise LocationError("VERSION_UNAVAILABLE: requested text version is not installed")
        path = self.root / DATA / "works" / f"{dialogue}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Canonical dialogue is unavailable: {dialogue}; run scripts/build-canonical-corpus.py")
        stored = json.loads(path.read_text(encoding="utf-8"))
        segments = []
        for section in stored["sections"]:
            for segment in section["segments"]:
                segments.append({"stephanus": section["stephanus"], "division": section["division"],
                                 "text": segment["text"], "annotations": segment["annotations"]})
        verified = make_work(self.inventory, entry, segments)
        if stored != verified:
            raise ValueError(f"Canonical work metadata or content differs from inventory: {dialogue}")
        return verified

    def resolve(self, location):
        if not isinstance(location, dict) or set(location) != {"dialogue", "text_version", "start", "end"}:
            raise LocationError("INVALID_LOCATION: expected dialogue, text_version, start and end")
        dialogue = location.get("dialogue")
        version = location.get("text_version")
        if not isinstance(version, str) or not version:
            raise LocationError("INVALID_LOCATION: text_version is required")
        work = self.work(dialogue, version)
        indices = {section["stephanus"]: index for index, section in enumerate(work["sections"])}
        points = []
        for name in ("start", "end"):
            point = location.get(name)
            if not isinstance(point, dict) or set(point) != {"stephanus", "offset"}:
                raise LocationError(f"INVALID_LOCATION: {name} must contain stephanus and offset")
            reference = point.get("stephanus")
            if not isinstance(reference, str) or reference not in indices:
                raise LocationError(f"UNKNOWN_REFERENCE: invalid {name} Stephanus reference")
            index = indices[reference]
            text = "\n".join(segment["text"] for segment in work["sections"][index]["segments"])
            points.append((index, python_offset(text, point.get("offset")), text))
        (start_index, start, start_text), (end_index, end, end_text) = points
        if start_index > end_index or (start_index == end_index and start > end):
            raise LocationError("REVERSED_RANGE: end precedes start")
        if start_index == end_index:
            selected = start_text[start:end]
        else:
            middle = ["\n".join(segment["text"] for segment in section["segments"])
                      for section in work["sections"][start_index + 1:end_index]]
            selected = "\n".join([start_text[start:], *middle, end_text[:end]])
        context = [{"stephanus": work["sections"][index]["stephanus"], "text": text}
                   for index, text in [(start_index, start_text)] +
                   ([(end_index, end_text)] if end_index != start_index else [])]
        return {"location": location, "text": selected, "context": context, "source": work["source"]}
