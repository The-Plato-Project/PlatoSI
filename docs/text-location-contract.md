# Canonical text and location contract, version 1

Status: **implemented in PlatoSI's local reader API and independently
reproducible from pinned Perseus XML**. A portable development archive is
available locally; publication and Chora integration are future work. This
contract is owned by PlatoSI and does not require Chora at runtime. It is
separate from the existing experimental reader API's version number and
code-point offsets.

## Initial text baseline

The initial migration baseline is Chora's existing generated Plato work
snapshots, not PlatoSI's current raw-index extraction. This preserves the
reader text and offers a path for mapping existing selections. PlatoSI's
builder independently downloads the pinned Perseus XML and source metadata,
then verifies the extracted text and segmentation against a frozen inventory
of those snapshots. It does not read Chora or change it.

The inspected baseline is Chora commit
`3ce6aeebb869e8e82285463741b42fc11e9d1c6b`, with the generated work
snapshots and corpus builder unchanged in its working tree. Its catalogue
contains 35 works and identifies Perseus commit
`9a424880e535b7b24258feda413fa37580f8971f`. Its 35 work files match the
recorded SHA-256 checksums after conversion of checkout CRLF line endings
to LF. These are file checksums, **not** the location fingerprints defined
below. The baseline uses the catalogue's dialogue IDs; for example,
`republic` identifies the *Republic*. It retains internal source and edition
provenance, but clients do not ask readers to choose an edition.

For the inspected *Republic* snapshot, independent Python and JavaScript
calculations found 1,355 sections and the location fingerprint
`sha256:0d5d71f80d42eee6ec5c5328d1d1926789ddb327f53c8787131b1a20aa4af5ef`.
This identifies that snapshot's location text and the independently built
PlatoSI canonical work, not PlatoSI's older raw-text index.

PlatoSI's current Perseus inventory pins a different upstream revision,
`a6eb0cc3e6f6e382934a2c8b33577d2fb4371e00`, and its reader indexes raw
text with Python code-point offsets. These representations must not be
silently treated as the same version. Versioned migration and retention of
the original text for existing anchors are required before changing a
reader's corpus.

## Work representation

A work has a stable dialogue ID, catalogue metadata and provenance, and an
ordered sequence of nonempty text segments. Each segment has a Stephanus
section reference, text, and structural division when available. Preserve
the baseline's display text, punctuation, paragraph boundaries, embedded
line breaks, verse, and quotation and citation annotations; annotations and
other metadata are not themselves extra text. Preserve source markup and
provenance as separately attributed information where available. Do not
silently add, omit, or reinterpret text from the underlying XML during
conversion.

The initial baseline was built from Perseus TEI: the existing importer reads
`p`, `sp`, and `lg` blocks in order; flushes text at block boundaries,
Stephanus section milestones, and paragraph milestones; collapses source
whitespace; retains explicit line breaks and structured quotation/citation
breaks; trims segments and normalizes them to NFC. The generated snapshot is the baseline for this first version, not a claim
that every independently written TEI importer will produce identical
results. The PlatoSI builder verifies all extracted segments and annotations
against that baseline before publishing a work locally.

For version 1:

1. References are opaque, case-sensitive strings, unique within a work.
   Consecutive segments with the same reference form one section. Reject a
   work if a reference reappears noncontiguously, is missing, or is not a
   Stephanus section; do not merge or guess.
2. The section text is its segment texts in source order joined with one
   U+000A LINE FEED. Between consecutive sections, reconstruction likewise
   inserts exactly one U+000A. No separator is inserted before the first
   section or after the last.
3. Text must be valid Unicode scalar values and NFC. Reject a nonconforming
   snapshot; never normalize text after locations or fingerprints have
   been assigned. A noncomposing combining mark may remain in NFC text.
4. A section has one consistent division if divisions are present. Reject
   inconsistent section divisions. A work's catalogue retains its ordered
   divisions and source metadata; they are not user-selected editions.

The version 1 logical data model is:

- **Catalogue:** `contract` (`platosi.location.v1`) and an ordered `works`
  array. Each summary has `dialogue`, `title`, nullable `title_greek`,
  `author`, `language`, and `text_version`. IDs are unique. Discovery and
  pagination are API concerns, not part of this fingerprint.
- **Work:** `contract`, `dialogue`, `text_version`, the same title, author,
  and language metadata, `source`, and ordered `sections`. `source` records
  the repository, revision, source file, source text identifier, attribution,
  and license information; unavailable metadata is explicitly null or
  reported as unknown, never invented.
- **Section:** `stephanus`, nullable `division` with `type` and `label`,
  and ordered nonempty `segments`.
- **Segment:** nonempty NFC `text` and an `annotations` array, which may be
  empty. An annotation carries a kind and a start-inclusive/end-exclusive
  UTF-16 range within the segment text. Its boundaries must be valid scalar
  boundaries. The initial known annotation kinds are `quotation` and
  `citation`; annotations never insert characters into the text.

`canonical.catalog` and `canonical.work` expose this model through the local
reader API. Source identifiers and edition metadata are for provenance;
they do not create an edition selector.

An audit of the 35 current Chora work snapshots found no uncited segments,
noncontiguous repeated section references, non-NFC segment text, or sections
spanning different divisions. This is a baseline observation, not a
guarantee about other editions or future texts. Unsupported data requires an
explicit contract revision or correction, not an invented reference.

## Location

A location is an object with exactly these logical fields:

```json
{
  "dialogue": "republic",
  "text_version": "sha256:<64 lowercase hexadecimal digits>",
  "start": { "stephanus": "327a", "offset": 0 },
  "end": { "stephanus": "327a", "offset": 7 }
}
```

`text_version` is the fingerprint specified below. Both positions refer to
section text, not an individual paragraph or the entire book. `offset` is a
zero-based integer count of UTF-16 code units, as used by JavaScript string
indexing. A position may be at zero or at the section's UTF-16 length.
Positions inside a surrogate pair are invalid. Boundaries between Unicode
scalar values are permitted even when they split a grapheme cluster; a UI
may enforce stricter selection rules but must not silently adjust a location.

The range is start-inclusive and end-exclusive. An empty range is valid.
For a cross-section range, use section order in the work, not lexical or
numeric sorting of the reference. Reconstruct the start section from its
start offset, all intervening sections, and the end section up to its end
offset, joining sections with exactly one LF. Thus an end at offset zero in
the next section includes the separator, and the range from the previous
section's end to the next section's beginning selects exactly that LF.
For a range within one section, slice only that section.

UTF-16 offsets cannot be used directly as Python string indices. Conversion
must count UTF-16 code units and validate both boundaries before slicing.
Do not normalize, trim, or otherwise transform the returned selected text.
Book or dialogue scope is a separate exploration argument, not part of
the location or an implicit change to its boundaries.

## Text version and fingerprint

The location fingerprint identifies the exact location-addressable dialogue
text and reference ordering under this contract. It does not hash titles,
source metadata, division labels, or annotations; publish and version those
separately. A revision to those fields must not be mistaken for an
unchanged metadata release merely because this text fingerprint is unchanged.

Compute SHA-256 over these bytes, in order:

1. `LP("platosi.location.v1")`.
2. `LP(dialogue ID)`.
3. The number of sections as an unsigned 32-bit big-endian integer.
4. For each section in order, `LP(reference)` followed by `LP(section text)`.

`LP(s)` is the unsigned 32-bit big-endian **byte length** of the UTF-8
encoding of `s`, followed by those bytes. Encode only valid Unicode scalar
values. Reject counts or byte lengths exceeding `2^32 - 1`. The version is
`sha256:` followed by the lowercase hexadecimal digest. JSON serialization,
OS newline conversion, titles, and section separator bytes are not inputs:
section separators are fixed by the contract, while intra-section LFs are
included in section text. An extraction-contract change requires a new
contract identifier, even if the visible text happens to match.

Clients must retain the version with each persisted location. PlatoSI must
resolve against that exact version or report that it is unavailable; a
current version must not be substituted. A supplied version that disagrees
with the actual loaded text is an error. Revisions may preserve old
snapshots or offer an explicit, verified migration; they must never
automatically relocate an anchor by guessing from similar text.

## Failure and migration requirements

Validate dialogue identity, text fingerprint, reference uniqueness and
existence, integer and boundary validity, and range order. Report a
distinguishable error for an unknown dialogue, unavailable or mismatched
version, unknown reference, invalid offset, and reversed range. Do not return
an empty success for invalid input or normalize a request to make it fit.

Chora's existing Dream source and Signal selections persist a `documentId`
and start/end `segmentKey` plus segment-relative UTF-16 offset. The initial
mapping must use the exact legacy snapshot and account for one LF between
segments. Existing records do not include this contract's text fingerprint;
establish their legacy snapshot before mapping. Preserve original records
and report ambiguous or unresolvable cases. Reader data stays in Chora.

## Conformance fixtures

The synthetic [fixture](../tests/fixtures/text-location-v1.json) exercises
multiple segments under one section, cross-section ranges and separators,
supplementary characters, and invalid requests. It is deliberately not a
complete Republic section and its fingerprint is not a corpus release ID.
Independent Python and JavaScript checks consume the same expected strings,
errors, and hash. They demonstrate the contract; neither is a production API.

```powershell
python -m unittest discover -s tests -p test_text_location_contract.py -v
node tests\text_location_contract.mjs
```
