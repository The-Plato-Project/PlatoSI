import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const fixture = JSON.parse(readFileSync(new URL("./fixtures/text-location-v1.json", import.meta.url), "utf8"));

function sectionsFromFixture(input) {
    const seen = new Set();
    return input.sections.map((section) => {
        const text = section.segments.join("\n");
        if (!section.stephanus || seen.has(section.stephanus) || !text
            || text.normalize("NFC") !== text
            || [...text].some((char) => char.codePointAt(0) >= 0xD800 && char.codePointAt(0) <= 0xDFFF)) {
            throw new Error("Invalid fixture section");
        }
        seen.add(section.stephanus);
        return { reference: section.stephanus, text };
    });
}

function lp(value) {
    const text = Buffer.from(value, "utf8");
    const length = Buffer.alloc(4);
    length.writeUInt32BE(text.length);
    return Buffer.concat([length, text]);
}

function fingerprint(input, sections) {
    const count = Buffer.alloc(4);
    count.writeUInt32BE(sections.length);
    const pieces = [lp(input.contract), lp(input.dialogue), count];
    for (const section of sections) {
        pieces.push(lp(section.reference), lp(section.text));
    }
    return "sha256:" + createHash("sha256").update(Buffer.concat(pieces)).digest("hex");
}

function validateOffset(text, offset) {
    if (!Number.isInteger(offset) || offset < 0 || offset > text.length) {
        throw new Error("INVALID_OFFSET");
    }
    const before = text.charCodeAt(offset - 1);
    const after = text.charCodeAt(offset);
    if (before >= 0xD800 && before <= 0xDBFF && after >= 0xDC00 && after <= 0xDFFF) {
        throw new Error("INVALID_OFFSET");
    }
}

function resolve(input, sections, testCase) {
    if ((testCase.dialogue ?? input.dialogue) !== input.dialogue) {
        throw new Error("UNKNOWN_DIALOGUE");
    }
    if ((testCase.text_version ?? input.text_version) !== fingerprint(input, sections)) {
        throw new Error("VERSION_MISMATCH");
    }
    const startSection = sections.findIndex((section) => section.reference === testCase.start[0]);
    const endSection = sections.findIndex((section) => section.reference === testCase.end[0]);
    if (startSection < 0 || endSection < 0) {
        throw new Error("UNKNOWN_REFERENCE");
    }
    const start = testCase.start[1];
    const end = testCase.end[1];
    validateOffset(sections[startSection].text, start);
    validateOffset(sections[endSection].text, end);
    if (startSection > endSection || (startSection === endSection && start > end)) {
        throw new Error("REVERSED_RANGE");
    }
    if (startSection === endSection) {
        return sections[startSection].text.slice(start, end);
    }
    const parts = [sections[startSection].text.slice(start)];
    for (let index = startSection + 1; index < endSection; index += 1) {
        parts.push(sections[index].text);
    }
    parts.push(sections[endSection].text.slice(0, end));
    return parts.join("\n");
}

const sections = sectionsFromFixture(fixture);
assert.equal(fingerprint(fixture, sections), fixture.text_version, "fingerprint");
const changed = sections.map((section) => ({ ...section }));
changed[0].text += "!";
assert.notEqual(fingerprint(fixture, changed), fixture.text_version, "changed text");
for (const testCase of fixture.valid) {
    assert.equal(resolve(fixture, sections, testCase), testCase.text, testCase.name);
}
for (const testCase of fixture.invalid) {
    assert.throws(() => resolve(fixture, sections, testCase), { message: testCase.error }, testCase.name);
}
assert.throws(() => sectionsFromFixture({ sections: [{ stephanus: "327a", segments: ["α\u0301"] }] }));
assert.throws(() => sectionsFromFixture({ sections: [
    { stephanus: "327a", segments: ["a"] }, { stephanus: "327a", segments: ["b"] }
] }));
console.log(`Location contract: ${fixture.valid.length} valid and ${fixture.invalid.length} invalid cases passed.`);
