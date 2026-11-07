# Lemma, dialogue-form, and relationship index plan

For the implemented stages and remaining work, see the current
[Morpheus implementation handoff](morpheus-implementation-handoff.md).
Canonical tokens and generic provider inventories remain supported. Morpheus
now supplies a permanent, dialogue-scoped PlatoSI morphology build.

## Purpose

PlatoSI will own a durable local index that begins with a word selected at an
exact canonical location and returns:

- every candidate lemma supported by configured linguistic providers;
- every form of each candidate lemma actually present in the selected
  dialogue, with counts and canonical locations;
- directly related lemmas supported by configured local sources;
- which related lemmas and forms occur in the selected dialogue;
- evidence, provenance, and limitations for every mapping.

Chora will request and present this information. It will not perform
morphological matching, discover lexical relationships, or maintain the
linguistic cache.

## Principles

1. Preserve ambiguity. A selected form may have more than one candidate
   lemma; PlatoSI will not choose one contextual meaning.
2. Observed and generated data remain distinct. A generated paradigm form is
   not an occurrence until it is found at an exact canonical location.
3. Inflection and derivation remain distinct. A verbal noun may be related to
   a verb, but it is not an inflected form of the verb's lemma.
4. Every relationship has a source. Models do not silently invent lemma
   relationships.
5. The canonical dialogue is authoritative for dialogue counts and
   locations.
6. Permanent results are tied to the canonical text version, provider identity,
   and the matching-policy version.

## Reader result

For a selected form such as `κατέβην`, PlatoSI will organize the response by
candidate lemma:

```text
καταβαίνω

Forms in the Republic
  κατέβην       1
  καταβαίνει    4
  καταβῆναι     2

Related lemmas in the Republic
  κατάβασις     2    derived noun

Other related lemmas
  ...
```

Each observed form carries its exact locations and passage context. A client
may initially render only the count and reveal the locations on demand.

## Evidence layers

Form mappings use the following ordered evidence classes:

1. `direct_lookup`: a provider explicitly maps the surface form to the lemma.
2. `normalized_lookup`: a capitalization, grave/acute, elision, or documented
   editorial normalization maps to a direct provider row.
3. `source_paradigm`: a named morphology source supplies the form for a
   paradigm slot and the form occurs in the dialogue.
4. `generated_paradigm`: a template supplies the form and the form occurs in
   the dialogue.
5. `model_suggestion`: an explicitly requested model proposes the mapping.

The initial production path will include the first three layers. Generated
and model-suggested relationships must remain visibly weaker and will not be
silently mixed into direct results.

Related-lemma edges use explicit relation classes:

- `alternate_headword`
- `spelling_variant`
- `dialect_variant`
- `derived_noun`
- `derived_adjective`
- `derived_adverb`
- `prefixed_compound`
- `compound`
- `dictionary_cross_reference`
- `etymological_relation`

The initial relationship extractor will use structured local source evidence,
beginning with explicit LSJ etymological references. Similar spelling alone does not create a relationship.

## Persistent storage

PlatoSI will use a local SQLite database under generated, untracked data. The
database will contain:

### `index_builds`

- dialogue
- canonical text version
- matching-policy version
- provider fingerprint
- state (`building`, `ready`, or `failed`)
- creation and completion timestamps

### `tokens`

- stable token identifier
- dialogue build reference
- canonical section reference
- shared canonical form reference
- UTF-16 start and end offsets

`canonical_sections` stores each Stephanus passage and division once.
`canonical_forms` stores each exact surface form and its normalized keys once.

### `provider_lemma_forms`

- normalized lemma
- exact form key
- relation to the lemma
- evidence class
- provider and provider version
- source and license metadata
- artifact fingerprint

Provider lemma inventories are stored independently of canonical dialogue
builds. Dialogue counts and locations are derived at request time by
intersecting those records with `tokens`.

### `morphology_builds`, `morphology_build_forms`, `morphology_forms`, and `morphology_analyses`

- one resumable build per canonical dialogue version and Morpheus identity;
- one shared checked, unresolved, failed, or pending state per provider/form;
- compact membership rows connecting each dialogue build to its forms;
- every candidate lemma, source headword, homograph, grammatical reading, and
  raw Morpheus evidence;
- a ready state only after every distinct canonical form has a valid response.

### `lemma_relations`

- source lemma
- target lemma
- relation type and direction
- provider
- exact source reference or source fragment
- source and license metadata
- artifact fingerprint

Observed counts and locations are derived by matching `provider_lemma_forms` to
`tokens`. Locations will not be duplicated into opaque cached JSON.

## Build and cache behavior

1. Tokenize each canonical dialogue once per text version.
2. On the first request for a candidate lemma, retrieve and store its provider
   form inventory once for reuse across dialogues. Cache direct related-lemma
   edges separately for the selected dialogue.
3. Mark the cache entry ready only after all rows are committed.
4. Reuse the ready entry for any selected form that resolves to the same
   lemma.
5. Rebuild dialogue tokens when the canonical version or matching policy
   changes. Refresh provider inventories when their capability-specific
   configuration or artifact fingerprint changes.
6. Keep previous-version rows isolated until explicit cleanup so an
   interrupted rebuild cannot destroy the usable index.
7. Do not mark failed or partial provider retrievals as ready cache entries.
   Concurrent first-request serialization remains future work.

## Provider strategy

### Morpheus

- Build through an exact, hash-verified ikelos wheel.
- Analyze every distinct canonical form during an explicit resumable build.
- Preserve the source headword, homograph and grammatical features for each reading.
- Build PlatoSI's reverse lemma-to-observed-form mapping from those permanent rows.
- Filter mappings by the selected source headword and homograph.
- Count each token once even when multiple parses support the same headword.
- Never use a partial or failed build for ordinary dialogue lookup.

### LSJ and other dictionaries

- Preserve the original XML.
- Extract explicit cross-references and headword targets with their source
  fragments.
- Keep lexical relations separate from dictionary prose inferred by a model.
- Add other local dictionaries as independent providers rather than merging
  their claims without provenance.

## Local API

The planned location-based operation is:

```json
{
  "operation": "linguistics.dialogue-lexicon",
  "payload": {
    "location": {
      "dialogue": "republic",
      "text_version": "sha256:...",
      "start": { "stephanus": "327a", "offset": 0 },
      "end": { "stephanus": "327a", "offset": 7 }
    }
  }
}
```

The response will include:

- the selected target and context;
- candidate lemmas;
- observed dialogue forms grouped by candidate lemma;
- exact counts and canonical locations;
- direct related lemmas grouped by relationship type;
- dialogue presence and counts for related lemmas;
- provider and artifact provenance;
- cache identity and build status;
- explicit limitations.

## Chora presentation

Chora will present PlatoSI's organized response:

- form plus Republic occurrence count;
- click-to-expand occurrence locations;
- related lemmas present in the Republic first;
- other directly related lemmas separately;
- relation type and evidence source;
- panel-local history when a related lemma is opened.

Navigation to a selected occurrence is a later presentation step. The first
integration will render counts and expandable canonical locations.

## Delivery stages

### Stage 1: Durable dialogue token index

- Define the schema and atomic build lifecycle.
- Tokenize canonical NFC Greek words with UTF-16 offsets.
- Store and query Republic counts and locations.
- Verify reconstruction through the canonical location contract.

### Stage 2: Source-specific form evidence

- Build a compact, versioned morphology database from pinned ikelos.
- Preserve source provenance, homographs, all readings, and unresolved forms.
- Intersect mappings with the dialogue token index.
- Return all observed forms and exact locations for each candidate lemma.

### Stage 3: Related-lemma graph

- Define provider-neutral relationship records.
- Extract explicit LSJ cross-references.
- Persist direct edges and dialogue-presence summaries.

The initial implementation persists a separate relation cache and extracts
Greek targets from LSJ's structured `etym` elements. Targets must resolve to
real LSJ headwords, and the exact XML fragment is retained as evidence.
Broader equivalence and compound edges remain pending rather than being
inferred from spelling.

### Stage 4: Reader API and Chora

- Add `linguistics.dialogue-lexicon`.
- Decode the typed contract in Chora.
- Replace the current single-form occurrence section with lemma-grouped form
  counts and expandable locations.
- Add related-lemma groups without adding interpretation.

### Stage 5: Validation

- Contract and schema tests.
- Cache reuse and invalidation tests.
- Concurrent first-request tests.
- Real Republic tests beginning with `κατέβην`.
- Full PlatoSI and Chora regression suites.
- Manual Chora inspection performed by the user; automated work will not
  launch Chora as a background process.
