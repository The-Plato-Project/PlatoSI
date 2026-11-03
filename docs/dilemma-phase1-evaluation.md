# Dilemma: comprehensive isolated evaluation

Evaluated 1 November 2026 with `dilemma-nlp` 1.3.10. This is a
capability evaluation, not an accuracy benchmark, linguistic adjudication,
or legal advice. It supersedes the earlier narrow lookup-only evaluation.

PlatoSI now pins `dilemma-nlp` 1.3.12. Dilemma 1.3.11 fixed eager backend
imports for lookup-only construction, so PlatoSI no longer pre-initializes
Dilemma on the main thread. The observations below retain their original
1.3.10 evaluation context unless stated otherwise.

## Conclusion

Dilemma has substantially more functionality than the earlier
PlatoSI adapter exposes. Its lookup lemmatization, POS-conditioned analysis,
contextual tagging, exact-form attestation, corpus citations, paradigms,
spelling support, morphology comparison, and source reconciliation all ran
offline in the isolated environment.

That does not make every result authoritative:

- Dilemma can propose plausible-looking analyses for invented forms even
  when neural guessing is disabled.
- Article resolution and POS hints can each select a single reading rather
  than preserve every possible analysis.
- Paradigms combine corpus-backed forms with generated forms. Those are
  different kinds of evidence and must remain visibly distinct.
- The public downloader did not provide two headword files required by
  lemma repair and strict citation validation. Those features are not
  operational in the downloaded distribution.
- The preload/export path omitted forms that direct lookup could resolve.
- Contextual tags and dependency relations are model predictions, not
  canonical facts.

The earlier `plugins/dilemma` adapter represented only a narrow subset of
Dilemma. PlatoSI now has a provider-owned evaluation operation for every
capability group in this report and a browser laboratory at `/dilemma`.
The laboratory exposes guided presets, editable request JSON, structured and
raw results, history, comparison, and export. It uses configured external
artifacts in place and does not copy or package them. This remains a research
environment in PlatoSI, not a Chora feature. The reader, not this report, will
determine which capabilities belong in the eventual reading workflow.

## Isolated environment

- Dilemma source release: 1.3.10, MIT-licensed code.
- Windows 11, Python 3.12.10, CPU ONNX inference.
- Inference ran with Hugging Face offline mode enabled after acquisition.
- Artifact directory: 131 files, 6,484,240,168 bytes.
- Important installed artifacts:

| Artifact | Bytes | Purpose |
| --- | ---: | --- |
| `data/lookup.db` | 1,214,173,184 | Form-to-lemma lookup |
| `data/spell_index.db` | 602,959,872 | Spelling suggestions |
| `data/form_profile.db` | 488,013,824 | Exact-form attestation |
| `data/form_citations.db` | 1,092,911,104 | Corpus citations |
| `model/grc-s3/encoder.onnx` | 6,862,227 | Ancient Greek lemma model |
| `tagger/grc/tagger.onnx` | 507,644,856 | Contextual tagger/parser |

The evaluation environment, script, and detailed JSON results remain outside
the repositories in the session research directory. The JSON records every
result, exception, provenance field, and operation timing.

## Coverage

The evaluation exercised all public exports and public methods discovered in
Dilemma 1.3.10:

- single, verbose, POS-aware, and batch lemmatization
- lookup-only and neural-guess paths
- POS prediction
- article-resolution, normalization, dialect, convention, and citation modes
- exact-form and lemma attestation, including citations
- spelling suggestions, headword checks and ranges
- lemma repair
- lookup database, preload, and cache export
- contextual POS, morphology, sentence segmentation, and dependency parsing
- verb, noun, and adjective paradigm generation
- attested-only paradigm filtering and paradigm citations
- form and paradigm morphology comparison
- multi-source voting and deterministic reconciliation
- Unicode, accent, editorial-form, elision, and nonlexical helpers
- citation-form validation

Representative inputs included `κατέβην`, `προσευξόμενός`, `πομπή`,
`πέμπω`, `αὐτοῦ`, `τοῦ`, invented forms, NFC/NFD variants, editorial forms,
and two sentences from *Republic* 327a and 327c.

Nineteen of twenty independently isolated capability groups completed.
Lemma repair was the only group that could not run.

## Findings by capability

### Lemmatization and ambiguity

Lookup returned the expected candidates for the central examples:

| Form | Candidate | Source |
| --- | --- | --- |
| κατέβην | καταβαίνω | exact lookup |
| προσευξόμενός | προσεύχομαι | exact lookup |
| βουλόμενος | βούλομαι | exact lookup |
| πομπή | πομπή | exact lookup |
| πέμπω | πέμπω | exact lookup |

The lookup remains candidate evidence rather than proof. With neural guessing
disabled, the invented `ἀφλωποτήσσουσιν` and `ζωπαρδυφάκω` still received
compound-derived candidates at score 0.65. Requiring corpus attestation
removed the invented candidate in the tested attested-only path.

Ambiguity is configuration-dependent:

- `αὐτοῦ` remained `αὐτοῦ` with surface mapping, became `αὐτός` with
  article/pronoun resolution, and could be selected as either `ADV` or
  `PRON` with a POS hint.
- `τοῦ` became `ὁ` as a determiner but produced `τίς` when forced through
  the pronoun POS path.

No single configuration preserves all plausible readings. A PlatoSI result
must identify the method and settings and must not describe a selected
candidate as an exhaustive analysis.

### Corpus attestation and citations

The optional attestation databases are functional. For `κατέβην`, Dilemma
reported:

- attested: true
- total count: 66
- works: 59
- ten requested citation records returned
- sources included Diorisis, First1KGreek, GLAUx, OGA, PG, and PTA
- one returned OGA citation identified Plato, *Respublica* 1.327

This is supporting evidence, but it is not Chora's canonical occurrence
index. Counts and locations reflect Dilemma's aggregated corpora, editions,
and locus schemes. Chora must use PlatoSI's canonical text for in-work
occurrence search and may show Dilemma citations as separately labeled
external corpus evidence.

### Contextual tagging and dependency parsing

The tagger processed both test sentences, segmented a combined paragraph
back into two sentences, and returned lemma, UPOS, morphological features,
dependency heads, and relations.

For the tested passages it returned:

- `Κατέβην` → `καταβαίνω`, first-person singular past indicative active
- `τοῦ` → `ὁ`, genitive singular masculine determiner
- `αὐτοῦ` in the 327c sentence → adverb with an adverbial dependency

This run was internally cleaner than the earlier limited experiment, but it
still establishes capability rather than accuracy. The evaluation laboratory
runs contextual output only when the reader requests that feature and shows
the returned structure directly.

### Paradigms and morphology comparison

Paradigm enumeration exposed 1,436 verb slots, 15 noun slots, and 45
adjective slots. Generation returned source provenance:

- `γράφω` present and aorist examples came from Morpheus.
- `καταβαίνω` produced 346 Morpheus forms; 125 were marked attested.
- `πομπή` produced 15 template forms; only one was marked attested.

The attestation distinction is essential. A generated paradigm form is not
an occurrence in Plato and is not necessarily attested anywhere.

Morphology comparison identified augment, stem, irregular-stem, and ending
roles for `ἔγραψα`. The laboratory exposes that comparison directly.

### Reconciliation

The reconciliation API retained competing source readings, reported a voice
disagreement, and then applied a deterministic mediopassive-ending rule to
change an active reading of `ὑπέσχετο` to middle. Its provenance recorded
both the vote and the correction rule.

The laboratory exposes this machinery with the competing readings and every
applied rule retained in the result. This evaluation does not measure its
accuracy against a larger manually reviewed Plato sample.

### Spelling, headwords, repair, and citation validation

Spelling suggestions worked and recovered accented and unaccented candidates
around `κατεβην`. Headword-constrained suggestions did not work because the
headword inventory was absent.

The downloaded distribution did not contain:

- `data/lsj_headwords.json`
- `data/cunliffe_headwords.json`

Consequences:

- `repair_lemma` raised a runtime error instructing the user to run the same
  downloader that had already completed.
- `is_headword("καταβαίνω", "lsj")` returned false.
- headword ranges were empty.
- the trusted Ancient Greek citation-headword inventory contained zero rows.
- strict citation policy rejected even `καταβαίνω` as untrusted.

These are packaging/data defects, not negative linguistic judgments.
PlatoSI must not expose these operations until Dilemma supplies and documents
the required artifacts or PlatoSI deliberately provisions a verified source.

### Normalization and sanitation

NFC and NFD inputs produced the same displayed candidates in the tested
forms, with different match provenance (`exact` versus `mono`). Accent,
grave-to-acute, Byzantine normalization, Ionic normalization, LSJ convention,
editorial-form expansion, elision, capitalization, numeral, abbreviation,
punctuation, and nonlexical classification paths all executed.

The laboratory exposes these helpers together so their transformations can be
examined against the original selected text.

### Cache behavior

Direct Ancient Greek lookup resolved `κατέβην` through the database's
language fallback. After `preload()`, `export_cache()` contained 10,521
entries but did not contain `κατέβην`.

The preload/export representation therefore is not equivalent to direct
lookup for `lang="grc"`. The laboratory exposes both paths so the discrepancy
is visible.

## Performance observations

These are single-machine observations, not benchmarks:

- constructing seven differently configured engines took about 21 seconds
  in total
- nine lookup/neural examples took about 5.2 seconds
- a cold contextual tagger run took about 6.3 seconds
- paragraph segmentation with a new tagger took about 5.7 seconds
- two full paradigms with attestation took about 1.7 seconds
- direct batch and POS operations were subsecond after initialization

The runtime and approximately 6.5 GB of artifacts are material packaging
constraints. Repeated cold initialization is visible in the timings.

## Reader-operated evaluation access

PlatoSI's provider-owned evaluation operation exposes all capability groups
in this report; its browser playground still needs to present them:

- lemmatization with editable guessing, article, normalization, dialect,
  convention, POS, citation-policy, and attestation options
- batch lemmatization and POS prediction
- form and lemma attestation with citations
- spelling, headword, repair, and citation-form operations
- contextual tagging, morphology, segmentation, and dependencies
- full paradigms and individual slot generation
- form and paradigm morphology comparison
- competing-reading reconciliation
- Unicode, editorial-form, elision, and nonlexical helpers
- direct lookup, preload/cache comparison, and artifact inventory

Inputs are editable JSON. Results are shown as returned, including provenance,
scores, alternatives, generation sources, attestation, citations, timings,
and feature errors. Broken or incomplete features remain accessible so the
reader can observe those failures rather than relying on this report's
classification.

## Licensing and distribution

Dilemma's source code is MIT. Its license and notice state that lookup
databases, weights, and derived artifacts remain subject to upstream terms.
The successful local evaluation does not clear the approximately 6.5 GB
artifact bundle for commercial redistribution.

Before packaging Dilemma with PlatoSI or Chora:

1. obtain artifact-specific licensing and lineage confirmation
2. identify attribution and share-alike requirements
3. confirm whether the optional attestation and citation databases may be
   redistributed
4. resolve the missing-headword artifact problem
5. define installation, update, integrity, and disk-space behavior

## Evaluation boundary

The laboratory keeps these result kinds visibly separate:

- canonical Plato text and occurrences
- Dilemma lookup candidates
- contextual model predictions
- external corpus attestation and citations
- generated paradigm forms
- reader-authored observations

The evaluation surface does not save results into Dreams or Signals and does
not decide which capabilities should become permanent reader features.
