"""Reproduce the canonical reading text from pinned Perseus TEI."""

import re
import unicodedata
import xml.etree.ElementTree as ET


MARKERS = ("\ue000", "\ue001", "\ue002", "\ue003")


def local_name(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


class Collector:
    def __init__(self):
        self.citation = None
        self.division = None
        self.parts = []
        self.segments = []
        self.quotation_lines = 0

    def append(self, text):
        if text:
            self.parts.append(re.sub(r"\s+", " ", text))

    def flush(self):
        text = "".join(self.parts)
        text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
        text = unicodedata.normalize("NFC", re.sub(r"[ \t]+", " ", text).strip())
        text = re.sub(" *" + MARKERS[0] + " *", "\n" + MARKERS[0], text)
        text = re.sub(" *" + MARKERS[1] + " *", MARKERS[1] + "\n", text)
        text = re.sub(" *" + MARKERS[2] + " *", MARKERS[2], text)
        text = re.sub(" *" + MARKERS[3] + " *", MARKERS[3] + "\n", text)
        starts = {}
        annotations = []
        result = []
        length = 0
        for char in text:
            if char in (MARKERS[0], MARKERS[2]):
                starts[char] = length
            elif char in (MARKERS[1], MARKERS[3]):
                start = starts.pop(MARKERS[0] if char == MARKERS[1] else MARKERS[2], None)
                if start is not None and start < length:
                    annotations.append({"kind": "quotation" if char == MARKERS[1] else "citation",
                                        "start": start, "end": length})
            else:
                result.append(char)
                length += utf16_length(char)
        text = "".join(result)
        leading = utf16_length(text) - utf16_length(text.lstrip())
        text = text.strip()
        text_length = utf16_length(text)
        annotations = [{**item, "start": max(0, item["start"] - leading),
                        "end": min(text_length, item["end"] - leading)} for item in annotations]
        annotations = [item for item in annotations if item["start"] < item["end"]]
        annotations.sort(key=lambda item: item["start"])
        if text:
            self.segments.append({"stephanus": self.citation, "division": self.division,
                                  "text": text, "annotations": annotations})
        self.parts = []

    def children(self, element, ancestors):
        self.append(element.text)
        for child in element:
            self.visit(child, ancestors + (local_name(element.tag),))
            self.append(child.tail)

    def visit(self, element, ancestors):
        name = local_name(element.tag)
        if name == "milestone":
            unit = element.get("unit")
            if unit == "section" and element.get("resp", "").lower() == "stephanus":
                self.flush()
                self.citation = element.get("n")
            if unit == "para":
                self.flush()
        elif name == "lb":
            self.parts.append("\n")
        elif name == "quote" and "cit" in ancestors:
            previous = self.quotation_lines
            self.quotation_lines = 0
            self.parts.append(MARKERS[0])
            self.children(element, ancestors)
            self.parts.append(MARKERS[1])
            self.quotation_lines = previous
        elif name == "bibl" and "cit" in ancestors:
            self.parts.append(MARKERS[2])
            self.children(element, ancestors)
            self.parts.append(MARKERS[3])
        elif name == "l":
            if self.quotation_lines:
                self.parts.append("\n")
            self.quotation_lines += 1
            self.children(element, ancestors)
        else:
            self.children(element, ancestors)


def extract_segments(xml_path):
    root = ET.parse(xml_path).getroot()
    body = next((node for node in root.iter() if local_name(node.tag) == "body"), None)
    if body is None:
        raise ValueError(f"No TEI body in {xml_path}")
    collector = Collector()

    def blocks(node, division):
        if local_name(node.tag) == "div" and node.get("subtype") == "book" and node.get("n"):
            division = {"type": "book", "label": node.get("n")}
        if local_name(node.tag) in ("p", "sp", "lg"):
            collector.division = division
            collector.children(node, ())
            collector.flush()
        else:
            for child in node:
                blocks(child, division)

    blocks(body, None)
    if not any(segment["division"] for segment in collector.segments):
        for segment in collector.segments:
            segment["division"] = {"type": "chapter", "label": "1"}
    return collector.segments
