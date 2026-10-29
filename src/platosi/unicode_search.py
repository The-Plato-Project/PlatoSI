"""Explicit, case-sensitive search normalization with original-text offsets."""

import unicodedata


def normalize(text: str, mode: str = "exact") -> tuple[str, list[tuple[int, int]]]:
    if mode not in ("exact", "accent-insensitive"):
        raise ValueError(f"Unknown search mode: {mode}")
    output: list[str] = []
    offsets: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        start = i
        i += 1
        if text[start].isspace():
            while i < len(text) and text[i].isspace():
                i += 1
            part = " "
        else:
            while i < len(text) and unicodedata.category(text[i]).startswith("M"):
                i += 1
            part = unicodedata.normalize("NFD", text[start:i])
            if mode == "accent-insensitive":
                part = "".join(c for c in part if not unicodedata.category(c).startswith("M"))
            part = unicodedata.normalize("NFC", part)
        output.extend(part)
        offsets.extend([(start, i)] * len(part))
    return "".join(output), offsets


def key(text: str, mode: str = "exact") -> str:
    return normalize(text, mode)[0]


def is_word(char: str) -> bool:
    return char == "_" or unicodedata.category(char)[0] in "LMN"


def matches(text: str, needle: str):
    """Find normalized substring matches with Unicode word boundaries."""
    start = 0
    while True:
        pos = text.find(needle, start)
        if pos < 0:
            return
        end = pos + len(needle)
        if (not is_word(needle[0]) or pos == 0 or not is_word(text[pos - 1])) and (
            not is_word(needle[-1]) or end == len(text) or not is_word(text[end])
        ):
            yield pos, end
        start = pos + 1
