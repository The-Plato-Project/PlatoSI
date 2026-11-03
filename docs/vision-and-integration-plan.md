# Vision and staged integration plan

This document records the project's direction and proposed work. It describes
the intended architecture, not a claim that the integration or relationship
exploration has already been implemented.

## Purpose

PlatoSI is an independently usable, local service for exploring Ancient Greek
texts, initially Plato. It supplies primary texts, precise locations,
linguistic resources, model selection, and an API for text-grounded inquiry.
Another application should be able to download and use PlatoSI as a local
dependency without PlatoSI depending on that application.

For this project, the larger goal is a conversation between a reader, the
dialogue, and AI in Chora. The reader builds a living memory graph or map of
the dialogue that can reveal powerful conceptual and eidetic relationships,
and support an understanding of the dialogue's deeper power and, as Plato
intended it, the soul. The graph supports the reader's inquiry; it does not
settle interpretation for them.

## Responsibilities

**PlatoSI owns:**

- The Perseus-derived dialogue texts it distributes or makes available,
  their provenance, and a versioned, reproducible text representation.
- The standard locations used to identify passages and occurrences.
- Access to dictionary, morphology, and other replaceable evidence providers.
- Model discovery and selection capabilities and the local API that connects
  models, textual evidence, and consuming readers.
- Attributed, tentative suggestions for relationships grounded in actual
  occurrences in the text.

**Chora owns:**

- The reader's interface and interactions, including the selected passage
  from which a Dream begins.
- Local storage and presentation of Dreams, observations, reader additions,
  and the evolving memory graph.
- The reader's decisions about which relationships to notice, describe,
  keep, or connect.

The dependency runs from Chora to PlatoSI, never from PlatoSI to Chora.
PlatoSI must also be usable without Chora. A consuming application may supply
reader-selected context for an inquiry, but PlatoSI does not own Chora's
graph or silently write over reader contributions. Providing saved material
to a model as context is not the same as retraining the model's weights.

## Dimensions of understanding

The goal is not to select a single definitive meaning or produce an
exhaustive list of meanings. The aim is to make the *means by which a reader
understands what a word points to* visible, while allowing context and later
reading to change what the reader notices. An English translation may not
preserve all the dimensions present in a Greek word's use.

The reader chooses the passage. The following dimensions help orient inquiry:

- **Passage and dialogue:** the immediate context, what is happening, and
  occurrences across a chosen book or whole dialogue.
- **Morphology:** the form and grammatical structure of the word. Declension
  and inflection matter for syntax and relations without, by themselves,
  determining the word's meaning.
- **Dictionary:** attributed entries and possible senses as resources, not
  exhaustive or unquestionable truth.
- **Related forms:** a central dimension. Follow roots and changing stems
  through the text, including possible compounds and forms such as
  καταβαίνω, -βαίν-, and -βη-. These relationships can expand understanding
  beyond a fixed dictionary account.
- **Sound and appearance:** notice echoes and wordplay, especially in nearby
  text, such as πομπή and ἔπεμπον. Similarity alone does not establish a
  shared historical root.
- **Connections in sense and context:** explore how words, dictionary
  references, roots or stems, and situations in the dialogue may illuminate
  one another. Keep these connections open to the reader's judgment.

Grammar tables and dictionaries are valuable scaffolding, not final
authorities. Suggestions should be starting points, not claims to perfection
or completeness. Do not assign an automatic importance score: a connection
that appears obscure may be powerful to the reader.

The reader can add a missed form or occurrence, create a relationship, and
write and save observations about it. Reader contributions must remain
distinguishable from source evidence and model suggestions. The text, rather
than a model's invented quotation or citation, grounds each proposed
occurrence. Model output and inferred relationships remain fallible.

## Shared text and location contract

PlatoSI will define and own the text representation and location contract;
Chora and other clients will consume them. The existing dialogue JSON files
in Chora are useful prior work to examine during migration, not a runtime
dependency of PlatoSI.

The intended request identifies a dialogue and precise start and end
positions using Stephanus references and offsets. It does **not** send the
selected Greek text or require a reader-facing edition choice. Start and end
may belong to different Stephanus sections. PlatoSI retrieves the selected
text from its own corpus and returns grounded evidence and occurrence
locations in the same contract.

The [version 1 text and location contract](text-location-contract.md) defines
the initial baseline, coordinate rules, fingerprint, and conformance fixtures.
The following requirements guide its implementation and migration:

- How the canonical text is extracted and segmented, including paragraph
  boundaries, whitespace, punctuation, editorial markup, and verse.
- Unicode normalization, offset origin, counting unit, and exclusive end
  boundaries. Version 1 uses NFC and UTF-16; Python must convert explicitly
  and reject invalid boundaries.
- How multiple segments within one Stephanus section map to one unambiguous
  coordinate system, and how cross-section selections are reconstructed.
- A text version and content fingerprint, including the extraction contract,
  so a client and PlatoSI can detect mismatched text rather than silently
  return the wrong passage.
- How existing Chora selections and graph anchors are migrated or resolved
  against their original text version without silently moving them.

Sharing Perseus as a source is not sufficient by itself. Chora and PlatoSI
currently have different extracted text layouts and pinned source revisions.
Chora's existing offsets are segment-relative JavaScript string offsets;
PlatoSI's experimental reader currently uses Python code-point offsets into
its indexed scope text. The local reader API separately exposes the shared
canonical contract; the older offsets retain their existing semantics.

## Staged work plan

Stages 1 and 2 have been implemented and checked. Stage 3 has a clean-install
tested development archive; it has not been published. The remaining stages
are planned, not completed. Each stage has its own checks;
evaluation and error handling are not deferred until the end. Begin with the
*Republic* for end-to-end examples, but design the text contract and catalogue
for all supported dialogues.

### 1. Define the canonical text and location contract

**Status:** specification and conformance fixtures completed; production
corpus import, API implementation, and legacy migration remain in later
stages. See [the contract](text-location-contract.md) for the decisions and
baseline audit.

**Do**

- Inventory Chora's existing work JSON, source revision, extraction rules,
  segment boundaries, and saved selection format. Compare these with
  PlatoSI's available Perseus sources; identify differences rather than
  assuming the two text representations are interchangeable.
- Decide which source and deterministic extraction rules PlatoSI will own.
  Specify a versioned work catalogue and dialogue representation, including
  metadata, source attribution, divisions, Stephanus references, punctuation,
  whitespace, editorial markup, verse, and paragraph boundaries.
- Specify a location consisting of a dialogue, text version, and start and
  end Stephanus positions with offsets. Define how to flatten multiple
  segments under one reference, how section boundaries work, and how
  selections spanning sections reconstruct text.
- Decide the offset unit and Unicode rules. The specified contract uses
  UTF-16, NFC-normalized text, and start-inclusive/end-exclusive ranges, with
  validation for invalid boundaries.
- Define how the text fingerprint is calculated and how unavailable versions,
  ambiguous references, and mismatches are reported. Do not require the
  reader to choose an edition or send selected text.

**Done when:** a written specification and representative fixtures allow
both a JavaScript client and PlatoSI to compute and resolve the same
locations independently, including cross-section selections.

### 2. Make PlatoSI the text owner

**Status:** implemented for the pinned 35-work canonical baseline through
the local reader API. Chora integration and distribution remain later stages.

**Do**

- Build or import a reproducible dialogue representation under PlatoSI,
  preserving Perseus source and licensing metadata. Use the Chora JSON as
  prior art where appropriate, without making Chora a runtime prerequisite.
- Expose a work catalogue and dialogue or book text through the local API,
  with text version, fingerprint, citation structure, and divisions. Make
  access practical for whole dialogues as well as books.
- Add location resolution: accept only the standard location and return the
  exact selected text, context, and corresponding standard coordinates.
  Return explicit errors for unavailable, invalid, or mismatched locations.
- Preserve existing experimental API behavior or introduce a clearly
  versioned change; do not silently reinterpret its current offsets.

**Done when:** PlatoSI alone can provide and resolve its text. Tests cover
the opening κατέβην, repeated references, multiple paragraphs per
reference, cross-section ranges, punctuation, verse, normalization,
supplementary characters, and invalid or mismatched versions.

### 3. Deliver PlatoSI as a local dependency

**Status:** a portable development ZIP and checksum can be built locally.
Clean-install verification covers corpus acquisition and the process API
without Chora or a model. Python is a separate prerequisite; a hosted release
and stable version have not been published. See [local dependency
instructions](local-dependency.md).

**Do**

- Decide and document a downloadable installation and update method, runtime
  requirements, local data and index setup, and lifecycle. Keep PlatoSI
  independently runnable, with no dependency on Chora.
- Evaluate the existing versioned, newline-delimited local-process API as a
  transport; choose the supported interface based on integration needs.
  Specify startup, capability discovery, request IDs, cancellation,
  compatibility, shutdown, and actionable errors.
- Keep corpus and index acquisition reproducible. Resolve distribution
  permissions for each bundled text or optional provider; do not package
  unresolved third-party resources by assumption.

**Done when:** a clean local installation can start PlatoSI and retrieve and
resolve a passage from a small client without Chora or a model.

### 4. Connect Chora and protect existing selections

**Do**

- Change Chora to consume the PlatoSI-owned catalogue and text instead of
  maintaining an independent canonical work corpus. Map its UI selections
  to the shared locations; return occurrence locations to the same reader
  text without requiring selected Greek in requests.
- Inventory existing Dreams, Signals, and other persisted anchors. Design a
  version-aware migration or legacy-resolution path using the appropriate
  original text. Preserve existing reader data, allow recovery, and make
  unmappable or ambiguous anchors visible rather than moving them silently.
- Handle a missing, stopped, incompatible, or unavailable PlatoSI dependency
  explicitly. Keep graph and reader data under Chora's control.

**Done when:** a real Chora selection of a word, phrase, and cross-section
passage resolves to exactly what the reader selected, and existing anchors
remain correct or are explicitly identified for recovery.

### 5. Expose linguistic evidence and model selection

**Do**

- Add location-based operations that retrieve the selected text and return
  morphology candidates, dictionary entries, source attribution, limitations,
  and provider errors. Preserve alternatives rather than choosing a single
  authoritative analysis.
- Expose available model providers and models, model selection, availability,
  and cancellable inquiry through PlatoSI. Chora consumes these capabilities;
  models remain independently replaceable.
- Keep local evidence useful when a model is unavailable. Do not present
  unverified model output as a dictionary or source assertion.

**Done when:** a client can select a model, request evidence for a location,
and distinguish complete, partial, unavailable, and failed results without
sending the selected Greek.

### 6. Explore related forms

**Do**

- Accept a selected word and exploration scope, including a book or whole
  dialogue. Use morphology and dictionary resources as scaffolding to propose
  related forms, roots, changing stems, and possible compounds.
- Find occurrences in PlatoSI's actual text and return their standard
  locations, form, scope, supporting sources, and the basis and uncertainty
  of each proposed relationship. Do not equate spelling similarity with a
  proven historical root or treat provider coverage as exhaustive.
- Support an initially useful, incomplete result that the reader can extend
  in Chora. Do not assign numerical importance or replace reader judgment.

**Done when:** a real Republic inquiry starting with κατέβην can surface
grounded candidates such as καταβαίνων, and the contract can also represent
the proposed -βαίν- / -βη- relationship without claiming that every possible
related form has been found.

### 7. Explore other dimensions

**Do**

- Add optional exploration of local sound and appearance, connections in
  sense, and changing use across the passage, book, or dialogue.
- Give each suggestion supporting source occurrences and clearly attributed
  evidence; separate a model's proposal from established lexical evidence.
- Allow the reader to examine possibilities rather than receive a ranked or
  definitive interpretation.

**Done when:** representative nearby sound echoes and contextual
relationships can be inspected against their cited text, with uncertainty
and failures visible.

### 8. Exchange graph-compatible records

**Do**

- Define versioned, attributable records for textual occurrences, source
  evidence, model proposals, and relationships, all using the shared
  locations. Design the API to accept reader-selected observations as
  context when explicitly provided.
- In Chora, let readers add forms, occurrences, relationships, and written
  observations; preserve their authorship and local control. Keep suggested
  material distinct from accepted or reader-created graph material.
- Enable revisiting saved graph material as inquiry context without implying
  that persistence retrains the model.

**Done when:** a reader can add and describe a relationship, save it in
Chora, reopen it with its source locations intact, and use it in a later
inquiry without PlatoSI owning or overwriting the graph.

### 9. Evaluate the whole workflow

**Do**

- Use real passages, multiple dialogues and models, and reader-added examples
  to check location fidelity, provider attribution, uncertainty, and
  graph round trips. Include negative cases for invented occurrences and
  unavailable resources.
- Review usability against the project's purpose: helping the reader notice
  and pursue conceptual and eidetic relationships, not reducing the
  dialogue to fixed definitions or model conclusions.
- Document known limits and refine the contracts based on actual use while
  preserving compatibility and existing reader data.

**Done when:** the workflow is repeatable on a clean local installation and
its successes, failures, and remaining limitations are documented.

Existing local reader and provider experiments are prototypes, not the
finished shared contract or relationship scanner. Stages may inform one
another, but later exploration depends on reliable text locations and
attributable evidence.
