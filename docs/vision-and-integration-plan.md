# Chora integration: current architecture and remaining work

This document describes the writing-first architecture in the stable Chora and
PlatoSI main branches. Future work is identified explicitly; the separate Goose
experiment is merged into Chora main and remains an optional, experimental feature.

## Responsibilities

PlatoSI owns canonical Greek texts, the work catalogue, text versions, exact
locations, dictionary material, morphology candidates, dialogue occurrences,
related lexical evidence and personal-name research. Its local process API is
usable independently of Chora. Provider configuration for PlatoSI research
belongs to PlatoSI.

Chora owns the reader's workspace, Markdown Visions, Vision folders, independent
exact anchors, document placements, word notes and application settings. A Vision
can begin without a selected passage. Its prose is the reader's interpretation;
Chora does not assign meaning or create relationships on the reader's behalf.

Visions live under `Documents/Chora/<work name>/Visions/`, with real nested
folders. Work-scoped anchor JSON lives under `Documents/Chora/<work name>/Anchors/`.
An anchor's identity comes from its kind and exact canonical versioned range.
Each placement has its own stable identity and refers to an independent anchor.
Word placements use `chora-word` directives; larger selections use `chora-range`.
Editor modes can display atomic Greek tokens while preserving canonical metadata.

The dependency runs from Chora to PlatoSI. PlatoSI does not read or modify
Vision files, manage the workspace, or own the reader's notes. Passing reader
writing as context does not retrain model weights.

## Implemented integration

Chora starts the local PlatoSI process through its main-process client. Its typed
preload/IPC boundary keeps filesystem access and service execution out of the
renderer. Chora's Library uses PlatoSI's canonical catalogue and complete work
text; it does not maintain a competing canonical corpus.

The [text-location contract](text-location-contract.md) identifies a dialogue,
`text_version`, and start/end Stephanus references with section-relative UTF-16
offsets. Text is NFC; ranges are start-inclusive and end-exclusive. Both sides
must preserve version identity and reject invalid boundaries or mismatches.
A displayed selection, stored anchor and returned occurrence refer to this same
canonical representation. The test playground's indexed-edition offsets remain
a separate contract and must not be substituted.

Chora's Word Lookup presents dictionary material and dialogue-wide occurrences.
Occurrence detail separates the Greek passage, exact-occurrence morphology and
linked Visions. Range placements preserve independent access to each contained
Greek word. Reverse indexes accelerate linked-Vision lookup; authoritative
anchors and Vision documents remain the fallback when an index is stale.

The linguistic services preserve alternative lemma candidates and grammatical
readings. They do not silently choose contextual meaning. Dictionary senses,
explicit lexical relationships and model-generated name research retain distinct
attribution, coverage and uncertainty. Shipped morphology serves normal reader
lookup; a maintainer analyzer is not required at runtime.

## Reader-directed assistance

Stable Chora uses PlatoSI's optional model synthesis for personal-name research.
Reading, dictionary lookup and shipped morphology do not require a model.

The merged [Agentian Stranger PR](https://github.com/The-Plato-Project/Chora/pull/2)
experiments with a replaceable local Goose backend owned by Chora. This is
separate from PlatoSI's research providers and is available in Chora main.
It exposes existing feature services through read-only tools rather than
copying the text database, Vision persistence or linguistic implementations.

The reader requests a particular task: locate passages, find information in
Visions, or address a specified question. The model must distinguish canonical
Greek, linguistic evidence, reader writing and its own provisional inference.
More writing supplies guidance; it does not grant authority for unattended
interpretation, contradiction finding or changes to the reader's documents.
Neither citations nor agreement between models establishes an interpretation.

## Remaining work and verification

- Publish and verify a supported PlatoSI distribution; the development archive
  and its prerequisites are described in [local dependency](local-dependency.md).
- Preserve exact versions during any corpus update. Older unversioned selections
  require explicit recovery against their original snapshot, never guessed moves.
- Improve incomplete lexical/root/compound coverage without treating spelling
  similarity as an established relationship.
- Keep source-backed occurrences distinct from proposed conceptual relationships.
  A general semantic graph or autonomous relationship scanner is not implemented.
- Evaluate the optional interlocutor against reader tasks, including invented
  citations, unsupported claims, incomplete coverage, cancellation and scope.
- Keep future exchange or retrieval of reader writing subordinate to the reader's
  authorship and local control. No model should silently persist a relationship.

Verification belongs to each changed feature. Exact ranges, supplementary
characters, cross-section selections, version mismatches and unavailable
resources need explicit coverage. Documentation updates are checked against the
owning interfaces; historical audit test counts remain historical observations.
