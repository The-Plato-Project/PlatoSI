# PlatoSI — Text and Linguistic Services for Chora

## What is PlatoSI?

**PlatoSI was built to support Chora's reading and inquiry experience.** It supplies Plato's Greek texts, precise passage locations, dictionary and morphology evidence, dialogue-wide word occurrences, related lexical evidence, and optional model-assisted research.

**Chora is the reader's workspace.** It presents the text, Dreams, Signals, lemma observations, and research results while keeping the reader's developing understanding at the center. PlatoSI supplies the underlying material and services. See the [Chora user guide](../Chora/README.md) for the experience of reading and working with that evidence.

The browser pages included in this repository are the **PlatoSI test playground**. They exist to exercise and inspect functionality during development. Their reader, conversation page and laboratory are useful test interfaces; their menus and limitations do not define Chora's product experience.

This overview describes the implemented PlatoSI capabilities reviewed on **4 November 2026**. [DEVELOPER.md](DEVELOPER.md) explains architecture, configuration, commands, testing and integration. [CODEBASE_AUDIT.md](CODEBASE_AUDIT.md) preserves the detailed technical inventory and its verification boundaries.

## How Chora and PlatoSI work together

| Responsibility | Application |
| --- | --- |
| Reading workspace, selection, navigation, Dreams and Signals | Chora |
| Reader-authored Reflections and lemma observations | Chora |
| Canonical Greek catalogue, dialogue text and exact locations | PlatoSI |
| Dictionary, morphology and dialogue occurrence evidence | PlatoSI |
| Explicit lexical relationships and personal-name research | PlatoSI, presented by Chora |
| Model-provider configuration and research synthesis | PlatoSI |
| Standalone test reader, model conversation and Dilemma laboratory | PlatoSI test playground |

Chora starts PlatoSI as a local service. You do not need to run the test playground to use Chora. The service can also be used independently through its API or command line for development, research and integration.

## Plato's Greek texts and passages

PlatoSI supplies a canonical collection of **35 Platonic works**, including the Republic, Laws, Euthyphro, Apology, Crito, Phaedo, Symposium, Phaedrus, Meno and Gorgias. Chora uses this catalogue and text for its Library rather than maintaining a separate corpus.

The service returns complete dialogues or selected divisions and resolves exact selections identified by dialogue, text version and Stephanus positions. This allows Chora's chosen passages and returned word occurrences to refer to the same canonical text.

A separate indexed edition collection supports command-line and test-playground searches and passage lookups. It uses a different text representation from Chora's canonical Library. Technical differences and setup requirements are documented in the developer guide; they should not be confused with restrictions on what Chora can read.

## Greek word exploration

### Candidate lemmas and morphology

For a selected Greek word, PlatoSI can return candidate lemmas and linguistic analyses from configured resources. A **lemma** is a dictionary form associated with the selected surface form. One form can have several candidates, and the service preserves alternatives rather than deciding the contextual meaning.

The optional morphology resources are **Dilemma** and **GLEM**. They provide candidate analyses and direct form mappings. Dilemma's normal word-analysis path runs with neural guessing disabled under two article-resolution settings, while distinguishing lookup candidates from rule-generated suggestions. This does not make the results exhaustive or authoritative.

Chora requests the dialogue lexicon for the selected word and presents candidate lemmas in its Word lookup pane. Standalone word analysis is also available through the service and test tools.

### Dictionary evidence

The supplied dictionary adapter accesses the local **LSJ/Logeion** collection. It returns lexical entries and explicit orthographic variants, preserving separate source entries. Dictionary senses and etymological references remain evidence for the reader to examine, not an automatic choice of meaning.

A local dictionary entry may be missing even when a morphology resource returns a lemma. The service does not treat a missing lookup as proof that no valid analysis exists. Resource availability and coverage affect what Chora can present.

### Occurrences across a dialogue

The dialogue lexicon finds directly mapped forms of each candidate lemma that occur in the current canonical dialogue. It returns counts, passage contexts and exact locations. For the Republic, this service covers the whole dialogue, including its different numbered books.

Chora presents these occurrences and provides explicit navigation back to the text. This is distinct from the test playground reader's older book-or-division occurrence view.

Occurrence mappings can omit forms or associate an ambiguous form with a lemma that is unsuitable in context. Counts therefore describe the available evidence, not a final account of every use.

## Lexical relationships and personal-name research

### Related lemmas

PlatoSI can return related lemmas supported by explicit dictionary evidence, their relation types, and the mapped forms found in the current dialogue. Related lemmas remain separate from inflections of the original lemma.

The supplied relationship extraction currently covers a limited subset of LSJ etymological references. Broader root, compound and cross-reference exploration is incomplete. Similar spelling or a model's proposal does not silently create a source-backed relation.

Chora consumes this service in its Word lookup pane. The fact that the separate test playground has no dialogue-lexicon control does not make the service unavailable through Chora.

### Personal-name research

For a selected form with a capitalized-headword candidate, PlatoSI can collect reference candidates from Wikidata, English Wikipedia and English Wiktionary. It can also investigate a possible LSJ lexical comparison and ask its configured local model for a sourced summary of identity, name meaning and relationships.

Chora displays the research in its Person column and provides links to the source pages. PlatoSI retains distinct source candidates and tags relevance; Chora groups the relevant and other candidates for presentation.

This remains experimental. A capitalized candidate is not contextual entity recognition, namesakes may be confused, and a lexical comparison is not an established derivation. Citation filtering cannot establish that a source supports every generated statement. Some contextual grounding, cache invalidation and source-quality limits are recorded in the audit.

## Optional AI and additional service tools

The model's role is to support reader-directed inquiry. Reading, dictionary lookup and deterministic dialogue-form evidence do not require an AI model. In Chora's current interface, model-assisted synthesis is used for personal-name research; it does not provide a general Dream chat or write the reader's observations.

PlatoSI additionally implements tools for independent testing and integration:

| Tool | Access and scope |
| --- | --- |
| Grounded questions | CLI and local API; test-playground conversation mode. Retrieves text and selected evidence, returns an answer with evidence references and warnings. |
| Free model conversation | Test playground; no scholarly retrieval in this mode. |
| Two-model word assessment | Test playground reader. Sends the same evidence independently to two selected models and presents candidate statuses and agreement/disagreement. |
| Canonical word evidence | Local API. Organizes one selected word's evidence and can add Dilemma normalization, spelling, attestation and paradigms. |
| Greek corpus search and edition passages | CLI, local API and test playground. Exact search and reference retrieval over installed indexed editions; CLI also supports accent-insensitive matching. |
| Direct lemma/form matching | Local API and internal resource capabilities. Returns source mappings for requested forms. |
| Dilemma laboratory | Local API and test playground. Exposes 18 operation groups for inspecting linguistic capabilities and their prerequisites. |

The only supplied model adapter is **Ollama**, using locally installed models through a loopback service. PlatoSI does not download or train models. Generated answers can be wrong even when their evidence references are valid; agreement between models is not proof.

The Dilemma laboratory covers single/batch lemmatization, POS prediction, attestation and citations, spelling, headword checks, repair, contextual tagging/parsing, paradigms and individual forms, morphology comparison, source reconciliation, normalization, nonlexical classification, citation validation, direct lookup, cache inspection and package/data inventory. Availability depends on operation-specific artifacts, and some headword-dependent functions are not fully provisioned in the audited installation.

These testing and service capabilities are not automatically Chora features. The Chora guide describes which workflows its interface actually provides.

## Notes and persistence

Chora owns the reader's durable work: Dreams, Signals, Reflections and dialogue/version/lemma observations. They are separate from PlatoSI's downloaded resources and generated research caches. See the Chora guide for saving, recovery and backup behavior.

PlatoSI stores downloaded texts and dictionaries locally, maintains generated indexes, and caches some dialogue-form evidence, personal-name references and model results. These caches support reuse; they are not the reader's notebook.

The test playground has its own small browser-local notes feature tied to a word position. Its conversations and laboratory run history are temporary tab state. These test-interface behaviors should not be used to describe Chora's notes or persistence.

After setup, local text and lexical retrieval can work offline. Personal-name references require internet access when absent from the cache; the model itself runs locally.

## Getting started with Chora and PlatoSI

For the reading experience, follow the [Chora user guide](../Chora/README.md#getting-started). Chora needs a local PlatoSI installation with the canonical corpus and paths to the service's Python interpreter and reader API script.

To prepare the canonical texts from this repository:

```powershell
python .\scripts\build-canonical-corpus.py
python .\scripts\check-local-dependency.py
```

Python is required; the audited environment used Python 3.12.10 and the source uses Python 3.10+ syntax. Dictionary and richer linguistic research require separate resource setup. The [developer setup reference](DEVELOPER.md#setup-and-configuration) covers LSJ, optional Dilemma/GLEM, Ollama, configuration and command-line diagnostics.

You do not launch the playground as part of Chora startup. For development, it can be started separately to inspect service behavior; its commands and routes are described in the developer guide.

## Current limitations

Morphology candidates, dictionary senses and direct form mappings can be incomplete or unsuitable for a passage. Related-lemma extraction is narrow, and generalized relationship scanning is unfinished. Generated summaries and answers require the reader's judgement even when cited.

Some optional dependencies have incomplete data provisioning. Readiness checks, cancellation and cache invalidation have known limits. The indexed test tools and canonical Chora services also use distinct text representations and must retain their own location semantics.

The audit verified automated retrieval and location checks, including all 35 canonical works, but did not establish the semantic quality of live model answers or every Dilemma operation. Its Chora coverage boundary remains a record of that audit's scope; the separate Chora user guide has since been checked against relevant Chora source.

Texts, dictionaries, linguistic datasets and models have their own attribution and licensing terms. See [DEVELOPER.md](DEVELOPER.md) for technical and distribution boundaries and [CODEBASE_AUDIT.md](CODEBASE_AUDIT.md) for detailed evidence and open questions.
