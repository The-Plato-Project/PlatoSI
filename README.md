# PlatoSI — Text and Linguistic Services for Chora

## What is PlatoSI?

**PlatoSI was built to support Chora's reading and inquiry experience.** It supplies Plato's Greek texts, precise passage locations, dictionary and morphology evidence, dialogue-wide word occurrences, related lexical evidence, and optional model-assisted research.

**Chora is the reader's workspace.** It presents the text, Dreams, Signals, lemma observations, and research results while keeping the reader's developing understanding at the center. PlatoSI supplies the underlying material and services. See the [Chora user guide](../Chora/README.md) for the experience of reading and working with that evidence.

The browser pages included in this repository are the **PlatoSI test playground**. They exist to exercise and inspect functionality during development. Their reader and conversation page are useful test interfaces; their menus and limitations do not define Chora's product experience.

This overview describes the implemented PlatoSI capabilities reviewed on **5 November 2026**. [DEVELOPER.md](DEVELOPER.md) explains architecture, configuration, commands, testing and integration. [CODEBASE_AUDIT.md](CODEBASE_AUDIT.md) preserves the detailed technical inventory and its verification boundaries.

## How Chora and PlatoSI work together

| Responsibility | Application |
| --- | --- |
| Reading workspace, selection, navigation, Dreams and Signals | Chora |
| Reader-authored Reflections and lemma observations | Chora |
| Canonical Greek catalogue, dialogue text and exact locations | PlatoSI |
| Dictionary, morphology and dialogue occurrence evidence | PlatoSI |
| Explicit lexical relationships and personal-name research | PlatoSI, presented by Chora |
| Model-provider configuration and research synthesis | PlatoSI |
| Standalone test reader and model conversation | PlatoSI test playground |

Chora starts PlatoSI as a local service. You do not need to run the test playground to use Chora. The service can also be used independently through its API or command line for development, research and integration.

## Plato's Greek texts and passages

PlatoSI supplies a canonical collection of **35 Platonic works**, including the Republic, Laws, Euthyphro, Apology, Crito, Phaedo, Symposium, Phaedrus, Meno and Gorgias. Chora uses this catalogue and text for its Library rather than maintaining a separate corpus.

The service returns complete dialogues or selected divisions and resolves exact selections identified by dialogue, text version and Stephanus positions. This allows Chora's chosen passages and returned word occurrences to refer to the same canonical text.

A separate indexed edition collection supports command-line and test-playground searches and passage lookups. It uses a different text representation from Chora's canonical Library. Technical differences and setup requirements are documented in the developer guide; they should not be confused with restrictions on what Chora can read.

## Greek word exploration

### Candidate lemmas and morphology

For a selected Greek word, PlatoSI can return candidate lemmas and linguistic analyses from configured resources. A **lemma** is a dictionary form associated with the selected surface form. One form can have several candidates, and the service preserves alternatives rather than deciding the contextual meaning.

The **Morpheus** plugin uses the pure-Python **ikelos** port to build grammatical
evidence. PlatoSI ships those readings in a permanent database keyed by
canonical dialogue and text version, preserving source headwords, homograph
identifiers, grammatical features, and ambiguity. Readers do not run an
analyzer or make an HTTP request. See
[Plato morphology and ikelos](docs/morpheus.md).

Chora requests the dialogue lexicon for the selected word and presents candidate lemmas in its Word lookup pane. Standalone word analysis is also available through the service and test tools.

### Dictionary evidence

The supplied dictionary adapter accesses the local **LSJ/Logeion** collection. It returns lexical entries and explicit orthographic variants, preserving separate source entries. Dictionary senses and etymological references remain evidence for the reader to examine, not an automatic choice of meaning.

A local dictionary entry may be missing even when a morphology resource returns a lemma. The service does not treat a missing lookup as proof that no valid analysis exists. Resource availability and coverage affect what Chora can present.

### Occurrences across a dialogue

The dialogue lexicon finds directly mapped forms of each candidate lemma that occur in the current canonical dialogue. It returns counts, passage contexts and exact locations. For the Republic, this service covers the whole dialogue, including its different numbered books.

Maintainers use a pinned ikelos wheel to analyze every distinct canonical form
and publish a versioned PlatoSI evidence database. Canonical passages are
stored once, token locations point to shared forms, and morphology analyses are
reused across dialogues. Normal lookup reads that shipped database without
importing ikelos. If a completed build for the dialogue and
text version is absent, PlatoSI reports occurrence coverage as unavailable
instead of substituting partial evidence. Generic reverse-inventory plugins
remain supported independently.

Chora presents these occurrences and provides explicit navigation back to the text. This is distinct from the test playground reader's older book-or-division occurrence view.

Occurrence mappings can omit forms or associate an ambiguous form with a lemma that is unsuitable in context. Counts therefore describe the available evidence, not a final account of every use.

## Lexical relationships and personal-name research

### Related lemmas

PlatoSI can return related lemmas supported by explicit dictionary evidence, their relation types, and the mapped forms found in the current dialogue. Related lemmas remain separate from inflections of the original lemma.

The supplied relationship extraction currently covers a limited subset of LSJ etymological references. Broader root, compound and cross-reference exploration is incomplete. Similar spelling or a model's proposal does not silently create a source-backed relation.

Chora consumes this service in its Word lookup pane. The fact that the separate test playground has no dialogue-lexicon control does not make the service unavailable through Chora.

### Name research

For a selected form with a proper-name candidate, PlatoSI uses the selected passage to disambiguate Plato-specific and Athenian prosopographical records, then asks its local model for one source-cited historical account. Supported Perseus citations found in the Plato-specific record are followed automatically, and the relevant cited passages are added as evidence. Names can denote places as well as people. Chora displays the consolidated account with working source links below it.

The enabled research authorities are Platonis Humanistica Digitalia, whose person dictionary is based primarily on Debra Nails' *The People of Plato*, and the Athenian Onomasticon. PlatoSI may retrieve a primary text that Humanistica explicitly cites; it does not insert person-specific sources independently. Wikipedia, Wikidata, Wiktionary, and Grokipedia are not queried. See [configuration instructions](docs/name-research.md). LSJ stays in the dictionary section and is not queried again for name research or speculative roots.

Chora keeps the reader's saved notes separately from generated research. Existing saved notes are preserved. If the model cannot produce a usable summary, the interface reports that once and keeps the references accessible.

This remains experimental. Proper-name morphology does not identify the intended entity, and exact quotation checks do not independently establish historical truth. Same-name records remain separate during retrieval, and the synthesis rules forbid inferring an occupation from participation in a philosophical dialogue.
## Optional AI and additional service tools

The model's role is to support reader-directed inquiry. Reading, dictionary lookup and deterministic dialogue-form evidence do not require an AI model. In Chora's current interface, model-assisted synthesis is used for personal-name research; it does not provide a general Dream chat or write the reader's observations.

PlatoSI additionally implements tools for independent testing and integration:

| Tool | Access and scope |
| --- | --- |
| Grounded questions | CLI and local API; test-playground conversation mode. Retrieves text and selected evidence, returns an answer with evidence references and warnings. |
| Free model conversation | Test playground; no scholarly retrieval in this mode. |
| Two-model word assessment | Test playground reader. Sends the same evidence independently to two selected models and presents candidate statuses and agreement/disagreement. |
| Canonical word evidence | Local API. Organizes one selected word's source-specific morphology and dictionary evidence. |
| Greek corpus search and edition passages | CLI, local API and test playground. Exact search and reference retrieval over installed indexed editions; CLI also supports accent-insensitive matching. |
| Direct lemma/form matching | Local API and internal resource capabilities. Returns source mappings for requested forms. |

The only supplied model adapter is **Ollama**, using locally installed models through a loopback service. PlatoSI does not download or train models. Generated answers can be wrong even when their evidence references are valid; agreement between models is not proof.


These testing and service capabilities are not automatically Chora features. The Chora guide describes which workflows its interface actually provides.

## Notes and persistence

Chora owns the reader's durable work: Dreams, Signals, Reflections and dialogue/version/lemma observations. They are separate from PlatoSI's downloaded resources and generated research caches. See the Chora guide for saving, recovery and backup behavior.

PlatoSI stores downloaded texts and dictionaries locally, maintains generated indexes, and caches provider lemma-form inventories, dialogue occurrences, personal-name references and model results. These caches support reuse; they are not the reader's notebook.

The test playground has its own small browser-local notes feature tied to a word position. Its conversations are temporary tab state. These test-interface behaviors should not be used to describe Chora's notes or persistence.

After setup, text, dictionary, and shipped morphology retrieval work offline.
Direct maintainer morphology analysis requires the pinned ikelos build
dependency. Personal-name references require internet access when absent from
the cache; the model itself runs locally.

## Getting started with Chora and PlatoSI

For the reading experience, follow the [Chora user guide](../Chora/README.md#getting-started). Chora needs a local PlatoSI installation with the canonical corpus and paths to the service's Python interpreter and reader API script.

To prepare the canonical texts from this repository:

```powershell
python .\scripts\build-canonical-corpus.py
python .\scripts\check-local-dependency.py
```

Python is required; the audited environment used Python 3.12.10 and the source uses Python 3.10+ syntax. Dictionary and richer linguistic research require separate resource setup. The [developer setup reference](DEVELOPER.md#setup-and-configuration) covers LSJ, Morpheus, Ollama, configuration and command-line diagnostics.

You do not launch the playground as part of Chora startup. For development, it can be started separately to inspect service behavior; its commands and routes are described in the developer guide.

## Current limitations

Morphology candidates, dictionary senses and direct form mappings can be incomplete or unsuitable for a passage. Related-lemma extraction is narrow, and generalized relationship scanning is unfinished. Generated summaries and answers require the reader's judgement even when cited.

Some optional dependencies have incomplete data provisioning. Readiness checks, cancellation and cache invalidation have known limits. The indexed test tools and canonical Chora services also use distinct text representations and must retain their own location semantics.

The audit verified automated retrieval and location checks, including all 35 canonical works, but did not establish the semantic quality of live model answers or every optional provider operation. Its Chora coverage boundary remains a record of that audit's scope; the separate Chora user guide has since been checked against relevant Chora source.

Texts, dictionaries, linguistic datasets and models have their own attribution and licensing terms. See [DEVELOPER.md](DEVELOPER.md) for technical and distribution boundaries and [CODEBASE_AUDIT.md](CODEBASE_AUDIT.md) for detailed evidence and open questions.
