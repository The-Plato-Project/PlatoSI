# PlatoSI

A new, independent local AI project for Ancient Greek, initially focused on
Plato. The longer-term aim is to give a local language model reliable access
to Greek primary texts and linguistic references. The offline retrieval layer
is model-agnostic; an optional local Ollama plugin supports grounded inquiries.
The project does not currently connect to Chora. Its intended independent
service role and staged integration plan are described in
[Vision and staged integration plan](docs/vision-and-integration-plan.md).
An experimental local browser playground is available; it is not the final
PlatoSI UI.

For the portable local-process distribution and client protocol, see
[Local dependency](docs/local-dependency.md).

## Layout

- `src/platosi/` - provider contracts, registry, Unicode search and CLI.
- `plugins/` - independent corpus, dictionary and optional morphology providers.
- `plugins/ollama/` - replaceable local Ollama language-model adapter.
- `playground/` - experimental browser interface, localhost by default.
- `scripts/` - download, validation and retrieval/indexing entry points.
- `data/tlg0059/` - original Plato Greek XML and CTS metadata, downloaded locally.
- `data/upstream/` - the source repository's README and license.
- `data/lsj-logeion/` - original Logeion LSJ XML and source metadata, downloaded locally.
- `data/greek-morphology/` - original GLEM lists and Euthyphro treebank, downloaded locally.
- `docs/corpus-inventory.json` - pinned upstream file paths, sizes and Git blob hashes.
- `docs/corpus-manifest.json` - work and edition metadata, citation declarations and validation results.
- `docs/lsj-inventory.json` - pinned LSJ file paths, sizes, hashes and source information.
- `docs/lsj-manifest.json` - LSJ entry counts and validation results.
- `docs/morphology-inventory.json` and `docs/morphology-manifest.json` - pinned morphology sources and validation results.
- `docs/morphology-research.md` - resource comparisons, provenance and licensing caveats.
- `docs/retrieval.md` - provider architecture, search semantics and limitations.
- `docs/text-location-contract.md` - canonical text and location contract.
- `docs/canonical-corpus-v1-inventory.json` - canonical corpus source and text fingerprints.
- `tests/` - offline retrieval and provider-isolation tests.
- `data/indexes/` - independently generated, local SQLite indexes.
- `data/reader-profiles.json` - local reader preferences, independent of plugin state.

Downloaded data, generated indexes and model files are ignored by Git. The
small inventory and manifest are intended to be tracked.

## Index and retrieve locally

Install Python 3.10 or later; no third-party packages are required. On this
computer, Python 3.12 was installed for the current Windows user. In
PowerShell from the project root:

```powershell
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
& $python scripts\platosi.py index perseus-plato
& $python scripts\platosi.py index lsj-logeion
& $python scripts\platosi.py status
& $python scripts\platosi.py search 'κατέβην χθὲς εἰς Πειραιᾶ'
& $python scripts\platosi.py lookup 'καταβαίνω'
& $python scripts\platosi.py passage 'urn:cts:greekLit:tlg0059.tlg030.perseus-grc2' '327a'
```

On another computer set `$python` to the path of its Python executable.
`search`, `lookup`, `passage` and `analyze` produce JSON, including source
and license metadata. Use `--mode accent-insensitive` explicitly for a broader
match and `--limit N` to change the per-provider result limit.

GLEM is **disabled by default**. Its data and the generated GLEM index must
not be distributed or used commercially without resolving the licensing
questions. To enable it locally for research:

```powershell
& $python scripts\platosi.py enable glem
& $python scripts\platosi.py index glem
& $python scripts\platosi.py analyze 'κατέβην'
& $python scripts\platosi.py disable glem
```

Disable or enable any installed provider by ID. Missing, disabled or unindexed
providers are shown in `status` and do not block unrelated lookups. Run tests
from the project root with `& $python -m unittest discover -s tests -v`.
See `docs/retrieval.md` for precise matching, evidence, configuration and
indexing behavior, including important editorial and coverage limitations.

## Reader profiles

Profiles store ordered provider IDs and a text-first setting locally. To create
a text-first profile and use it in individual inquiries:

```powershell
& $python scripts\platosi.py profile save reader --text-first --resource perseus-plato --resource lsj-logeion
& $python scripts\platosi.py profile show reader
& $python scripts\platosi.py search 'κατέβην' --profile reader
& $python scripts\platosi.py lookup 'καταβαίνω' --profile reader --include lsj-logeion
& $python scripts\platosi.py search 'κατέβην' --profile reader --exclude perseus-plato
```

`profile list` shows saved profiles. Repeating `profile save` replaces the
named profile; list every resource and the desired mode each time. Repeated
`--resource` options set priority. An explicit `--include` list replaces the
profile's selection for that inquiry, in the order supplied; `--exclude`
removes IDs for that inquiry. Neither changes the profile or enables a
provider. In text-first mode, non-corpus resources require explicit inclusion,
even for a direct `lookup` or `analyze` request. Without a profile, existing
commands continue to use all enabled, available providers for the operation.
The profile file is ignored by Git.

## Ask a local model

Start Ollama separately and ensure a local model is installed. No model is
downloaded automatically. Discover available local models and ask about the
opening of the Republic:

```powershell
& $python scripts\platosi.py models --provider ollama
& $python scripts\platosi.py inquire 'What movement opens this passage, and what might it suggest?' `
  --provider ollama --model 'qwen3.5:9b' --include perseus-plato `
  --edition 'urn:cts:greekLit:tlg0059.tlg030.perseus-grc2' --citation 327a
```

The answer includes numbered evidence and source attribution. Add `--json`
for complete machine-readable evidence and diagnostics. Without a profile
or explicit inclusion, inquiries use corpus providers only. To use selected
scholarship, supply a profile or repeat `--include` for each desired provider,
including the corpus provider. `--headword` and `--form` supply explicit
dictionary and morphology queries; otherwise Greek words in the question or
`--text` are used literally. Without a passage reference, `--text` supplies
an exact Greek search phrase; if omitted, Greek words in the question are
searched. The system does not guess references or infer lemmas.

The default Ollama model and generation settings are configurable independently
of resource profiles. See `docs/retrieval.md` for options, replacement,
limits and attribution. Model responses can contain errors even when cited:
verify them against the returned evidence. GLEM remains optional and its
licensing is unresolved.

## Local model playground

Start Ollama separately and ensure at least one local model is installed.
From the project root, run:

```powershell
& $python scripts\playground.py
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/) in a browser. The
opening page offers word, Plato text, and Republic passage lookups and reports
when a resource is unavailable. The text search covers the installed Plato
corpus, not only the Republic. Word analysis requires an enabled morphology
resource; without one, an exact dictionary lookup may still return entries.
The links at the top open the experimental word reader and the existing model
conversation. Keep the terminal open; press Ctrl+C there to stop the server.
Use `--port 8766` to choose another local port. No extra Python packages,
hosted frontend services or model downloads are required.

### Dilemma laboratory

When the optional Dilemma provider and its separately configured artifacts are
available, open [http://127.0.0.1:8765/dilemma](http://127.0.0.1:8765/dilemma).
The laboratory exposes all 18 provider evaluation groups with guided presets
and editable JSON options. It displays provider, license, artifact fingerprint,
file count and size before running anything. Completed runs provide structured
and raw JSON views, tab-local history, two-run comparison, and JSON export.

The laboratory uses the configured artifacts in place. It does not copy,
download, commit, or package Dilemma models and databases. Exported results may
contain provider output and local artifact metadata; review them before sharing.
Stopping a run immediately stops browser polling and marks the job cancelled,
but some synchronous native Dilemma operations cannot interrupt until their
current operation returns. Every result remains experimental evidence rather
than an authoritative linguistic judgment. See
[the comprehensive Dilemma evaluation](docs/dilemma-phase1-evaluation.md) for
known limitations, artifact gaps, and licensing cautions.

The model conversation, available at `/conversation`, starts in Free
Conversation mode and does not consult the corpus or any
scholarly provider. Messages stay in memory during the browser session;
reloading or using New Conversation clears the context. The editable system
prompt, temperature and response-token limit apply to the next message. Stop generation cancels the
local model request. The model selector lists enabled plugins that implement
the cancellable chat interface and their available local models.

Text-Grounded Inquiry uses the existing reader profile and resource
selection rules. Enter an exact Greek search string or an edition and
citation. The optional resource override selects **only** the checked
providers and bypasses a profile's text-first restriction; include a corpus
provider. Expand the grounding-instructions panel to see the additional
instructions sent for this mode, and expand evidence records to examine
sources and warnings. Model responses may still be inaccurate.

The default server binds only to `127.0.0.1` and keeps requests and job
results in memory; it does not save conversations. Other programs or browser
extensions running on this computer may still have access to local activity.

## Canonical dialogue corpus

The canonical corpus provides 35 dialogues using the text and locations in
[the location contract](docs/text-location-contract.md). Build it independently
from the pinned Perseus source:

```powershell
& $python scripts\build-canonical-corpus.py
```

The builder downloads the original XML and source licensing metadata into
`data/canonical-text-v1/`, verifies source hashes, and reproduces and checks
the frozen text, paragraph boundaries, annotations, and fingerprints. The
corpus is ignored by Git; rerun the command to reproduce it. Existing source
files that fail verification produce an error rather than being overwritten.
`--dialogue republic` builds just one dialogue; the full catalogue is available
once all works have been built. Source edition rights still require review.

## Local reader API

The experimental version 1 integration API is separate from the playground
HTTP endpoints. A client starts `scripts/reader_api.py` as a child process
and exchanges UTF-8 JSON objects, one per line, on standard input and output.
It does not open a port. Standard output is reserved for protocol messages.
For example:

```json
{"version":1,"id":"word-1","operation":"word.analyze","payload":{"form":"κατέβην"}}
```

Every response echoes the version and request ID and has `status` `ok`,
`invalid`, `failed`, or `cancelled`. An `ok` response has a `result`;
`invalid` and `failed` include an `error`. Concurrent responses may arrive
out of order; IDs must be unique while requests are active. Send
`request.cancel` with a new ID and `{"id":"word-1"}` as its payload to
request cancellation. Its acknowledgement says whether the request was still
active; the original request also receives a terminal response. Cancellation
is cooperative and can race completion. Closing input requests cancellation
of outstanding work before the process exits.

| Operation | Payload | Result |
|---|---|---|
| `system.info` | `{}` | Service and protocol versions and location contract. |
| `capabilities` | `{}` | Available lookup types and component availability. |
| `word.analyze` | `{"form":"κατέβην"}` | Candidate analyses and dictionary entries for the form and candidate lemmas. |
| `linguistics.evidence` | `{"location":{"dialogue":"republic","text_version":"sha256:…","start":{"stephanus":"327a","offset":0},"end":{"stephanus":"327a","offset":7}}}` | Organized, model-free evidence for one exact canonical Greek word: lemma possibilities, local dictionary entries, normalization, spelling suggestions, attestations, citations, distributions, provenance, and compact paradigms. |
| `linguistics.dialogue-lexicon` | `{"location":{"dialogue":"republic","text_version":"sha256:…","start":{"stephanus":"327a","offset":0},"end":{"stephanus":"327a","offset":7}}}` | Candidate lemmas plus dictionary evidence, every directly mapped form actually present in that canonical dialogue, counts, exact locations, persistent cache provenance, and explicit source-backed related lemmas. The operation omits the expensive attestation, citation, and generated-paradigm work exposed by `linguistics.evidence`. |
| `linguistics.person-research` | `{"location":{"dialogue":"republic","text_version":"sha256:…","start":{"stephanus":"327a","offset":44},"end":{"stephanus":"327a","offset":53}},"lemma":"Ἀρίστων"}` | Lazy proper-name research for a morphology candidate, with cached Wikidata, Wikipedia, and Wiktionary evidence; locally validated LSJ comparisons; source-linked Ollama synthesis; and explicit identity or etymology uncertainty. |
| `lemma.matchForms` | `{"lemma":"καταβαίνω","forms":["κατέβην"]}` | Candidate mappings, each paired with the exact input form. |
| `dilemma.evaluate` | `{"feature":"analyze","options":{"form":"κατέβην","guess":false}}` | Raw output or a visible unavailable or failed outcome for one reader-selected Dilemma laboratory action. |
| `text.search` | `{"text":"κατέβην"}` | Exact-mode search across installed corpus providers. |
| `text.passage` | `{"edition":"…","citation":"327a"}` | Passages from the requested edition and citation. |
| `inquiry.ask` | `{"question":"…","text":"…"}` or `{"question":"…","edition":"…","citation":"…"}` | A model response grounded in retrieved evidence, if available. |
| `canonical.catalog` | `{}` | Canonical dialogues and their text versions. |
| `canonical.work` | `{"dialogue":"republic"}` | Versioned canonical dialogue, including sections, segments and provenance. Optional `text_version` and `division` (`{"type":"book","label":"1"}`) select a version or book. |
| `canonical.resolve` | `{"location":{"dialogue":"republic","text_version":"sha256:…","start":{"stephanus":"327a","offset":0},"end":{"stephanus":"327a","offset":7}}}` | Exact selected text, boundary-section context, location and provenance. |

Use the full `text_version` returned by `canonical.catalog` or
`canonical.work`. Canonical offsets count UTF-16 code units within a
Stephanus section; the end is exclusive. A location can cross sections and
does not contain selected text. Unknown dialogues, versions, references,
invalid offsets, and reversed ranges return explicit errors. Corpus
availability is reported by `capabilities`; build the corpus before using
these operations. Older operations retain their existing semantics and do
not use the canonical location coordinates.

Lookup result sections have `status` `ok`, `partial`, or `unavailable`,
`records`, `warnings`, and `possibly_truncated`. No available morphology is
not the same as a successful search with no candidates. Analyses and mappings
are source-specific possibilities, not contextual determinations. Text search
and passage locations refer to PlatoSI's sources; they are not automatically
valid selections in a different application's text. Passage records include
the requested span in `match` and may include a larger surrounding `text`;
search citations identify the match, not necessarily every word of that
surrounding text. `linguistics.dialogue-lexicon` stores its canonical token
index and provider form inventories in an untracked local SQLite cache keyed
by text version, matching policy, and provider artifact fingerprint. Its
current direct-lookup stage and planned related-lemma graph are specified in
[the lemma and dialogue index plan](docs/lemma-dialogue-index-plan.md).
`linguistics.person-research` is separate from ordinary word lookup because it
may use online sources and the configured local model. Raw source responses and
validated model results are cached in the untracked
`data/person-research-cache-v1.sqlite` file. Generated claims are retained only
with valid source IDs; lexical comparisons are not presented as established
name etymologies unless a retrieved name reference supports that connection.
`lemma.matchForms` accepts
up to 500 distinct input forms, allowing a client to join the returned
`input_form` to its own exact occurrences. Each request is limited to 2 MB,
each response to 8 MB, and at most 16 requests may be active; lookups are
limited to 20 results per provider where applicable. Capability availability
does not guarantee that the configured model is installed or that an inquiry
will succeed. The API does not accept model choices or prompts from clients.

`dilemma.evaluate` is an explicit evaluation surface. Its bounded feature
names expose the installed Dilemma lemmatization, batch, POS, attestation,
spelling, headword, repair, tagger/parser, paradigm, generation, morphology
comparison, reconciliation, normalization, nonlexical, citation, lookup,
cache, and inventory paths. Feature options are passed as JSON objects and
validated by the provider. The result preserves Dilemma's structured output;
feature failures are returned visibly rather than converted into empty data.

`inquiry.ask` searches PlatoSI's corpus for the supplied Greek text or passage
reference; it does not yet accept arbitrary Chora passage context. It may
return no answer when no corpus evidence is found. Generated answers are
fallible, and evidence references do not establish correctness. The API does
not automatically receive or persist Chora Dreams, Signals, or notes.
Packaging the Python runtime and resources and connecting Chora remain future
work.

### Optional access from your home network

On the Lenovo, start a separate, token-protected LAN instance. Port 8766 is
used here so it can run alongside the default localhost instance on 8765:

```powershell
& $python scripts\playground.py --lan --port 8766
```

The terminal shows the detected private IPv4 address or addresses, a browser
URL for each, and a newly generated access token. On the other computer,
open the URL for the Lenovo's home-network address and enter the token shown
in the terminal. The other computer needs only a browser. The token and
authenticated sessions expire when this server stops; restart it to generate
a new token. If startup reports no private address, check the Lenovo's
connection with `ipconfig` and retry. Restart the server after its address
changes.

Windows Firewall must allow the chosen port on a **Private** network. First
check the Lenovo's network profile with `Get-NetConnectionProfile`. Only
mark a network Private if you trust it. To add a rule for port 8766, run the
following in an **administrator** PowerShell; the project does not create
firewall rules automatically:

```powershell
New-NetFirewallRule -DisplayName 'PlatoSI Playground LAN 8766' -Direction Inbound `
  -Action Allow -Protocol TCP -LocalPort 8766 -Profile Private -RemoteAddress LocalSubnet
```

Change the port in the rule if you use a different `--port`. Remove this
specific rule when it is no longer needed:

```powershell
Remove-NetFirewallRule -DisplayName 'PlatoSI Playground LAN 8766'
```

LAN mode binds to `0.0.0.0` but accepts only loopback or private IPv4 clients,
and only the detected local private-IP host addresses. It does not change
Ollama's localhost-only configuration. Do not configure router port
forwarding, a public tunnel or a reverse proxy for the playground; inspect
your network configuration to ensure the port is not exposed publicly.
**HTTP is unencrypted:** the token, conversation and generated text can be
observed by someone with access to network traffic. Use this mode only on a
trusted private network, and do not share the token beyond trusted users.

## Experimental word reader

Start the playground as above and choose **Open word reader**, or open
`http://127.0.0.1:8765/reader`. The default text is the installed Perseus
edition of *Republic* Book I. Build the corpus and LSJ indexes first.
Select a Greek word to see local evidence and source details; no language
model is invoked. When an installed dictionary supplies an XML entry, the
reader displays attributed excerpts of its senses beneath the corresponding
candidate lemma, with further senses and the full source record expandable.
These excerpts are not a decision about which sense applies in the passage.
The reader has a work selector and a book selector for the Republic; other
text identifiers remain available under source settings. The Etymology
section shows references explicitly marked in the selected dictionary XML,
with context, when present. Such references do not necessarily identify a
historical root, and their absence does not prove that no etymology exists.
AI exploration of relationships across a book or whole work is not yet
implemented.
Choose a candidate lemma to see corpus-backed occurrences
and click one to return to its location in the reading. The matches are
provider-supported possibilities, not an exhaustive or contextually verified
list, and compounds and related roots are not automatically merged.

Choose a reader profile or explicitly select resources. Disabled providers
are not enabled by the reader. A text-first profile suppresses scholarly
resources unless explicitly selected. Without an enabled, available
morphology plugin, candidates and lemma occurrences will not be available;
the original text and any applicable dictionary entries remain accessible.

Notes, textual connections and a candidate chosen for exploration are saved
only when requested, in the current browser's local storage. They are separate
from model output and are not sent to models. Browser data can be cleared or
lost, and notes saved on another computer are not automatically synchronized.

**Examine with AI** is optional. Discover and choose a primary and a
validation model independently; each receives the same bounded local evidence,
not the other model's conclusions. Select different models for a more useful
comparison. Agreement is not verification. If a model is unavailable or
returns an invalid assessment, its error is shown and local reading remains
available. Successful assessments may be cached on the server in ignored
`data/word-exploration-cache.sqlite`; they include the supplied textual and
lexical evidence and model outputs. The cache is used only when both model
providers report model digests. Check **Request fresh examination** to bypass
it. Never treat model-generated text as a corpus occurrence or dictionary
entry.

### Optional Dilemma provider

Dilemma is disabled by default and is not included in the repository. Its
source code and its separate data/model artifacts have different licensing
considerations; review `docs/dilemma-phase1-evaluation.md` and the upstream
artifact terms before downloading, using commercially, or redistributing
anything. To install it separately on Windows, with internet access:

```powershell
& $python -m venv data\dilemma\venv
& .\data\dilemma\venv\Scripts\python.exe -m pip install 'dilemma-nlp==1.3.12'
& .\data\dilemma\venv\Scripts\python.exe -m dilemma download --dir data\dilemma --no-tagger
& .\data\dilemma\venv\Scripts\python.exe scripts\platosi.py enable dilemma
& .\data\dilemma\venv\Scripts\python.exe scripts\playground.py
```

The download is several gigabytes and is not pinned by that upstream
command. Run the playground with the interpreter containing Dilemma. To use
an existing download, add a `dilemma` config entry in ignored
`data/plugin-config.json` with `data` pointing to its `data` directory; keep
other provider settings intact. The optional `artifact_revision` is a
reader-supplied declaration, not a verified revision. The adapter reports a
local file-metadata fingerprint, not content hashes. Restart the server after
changing Dilemma data or its configuration. No model or tagger is run by
this adapter: it uses the verbose lemmatizer with neural guessing disabled,
under both article-resolution settings. Its lookup and rule suggestions can
still be wrong or incomplete; direct lookup occurrences omit inferred forms.
See `docs/retrieval.md` for details.

## Download and validate Plato

On Windows, run from the project root using Windows PowerShell 5.1 or later:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\download-plato.ps1
```

The script downloads from a fixed upstream commit, verifies each file against
its Git blob SHA-1, and regenerates the inventory and manifest. It replaces
local files that differ from that revision; keep edits elsewhere. It downloads
all work metadata and Greek edition XML in Plato's `tlg0059` directory, not
the English translations. Internet access to GitHub is required. GitHub API
rate limits apply.

To recheck the existing files offline:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate-plato.ps1
```

The validator checks file integrity, XML well-formedness, metadata-to-edition
links, language markers, nonempty Greek-script body content, body identifiers
and citation declarations. It does **not** perform
TEI/EpiDoc schema validation or establish textual accuracy, completeness or
authorship. Issues appear in the manifest; errors produce a nonzero exit
status. Citation declarations are recorded as XML from the original TEI
headers, alongside observed milestone units; they are not normalized into a
new citation scheme.

## Download and validate the Logeion LSJ

On Windows, run from the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\download-lsj.ps1
```

This downloads all `greatscott*.xml` files and the original README and license
from a pinned revision of [helmadik/LSJLogeion](https://github.com/helmadik/LSJLogeion).
The script verifies upstream Git blob hashes, regenerates the LSJ inventory and
manifest, and replaces local LSJ files that differ from that revision; keep
edits elsewhere. GitHub access is required and API rate limits apply. The
data stays separate from the Plato corpus and is ignored by Git.

To recheck downloaded files offline:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate-lsj.ps1
```

The validator checks integrity, strict UTF-8, XML well-formedness, entry IDs
and types, and Greek letters in entry headwords. It counts `div2` elements directly under
`text/div1`, including entries marked as glosses, but excludes front matter.
It records problem counts and examples per file. Errors produce a nonzero exit
status; warnings identify source data needing review, including duplicate IDs.
This is not TEI schema validation or a guarantee of lexical accuracy or coverage.

The upstream repository describes this as Logeion's edited version of the
Perseus LSJ, not the entire Logeion site or its other dictionaries. Corrections
are ongoing and only a few supplement changes are incorporated. The upstream
license specifies CC BY-SA 4.0; its README asks users to credit both Perseus
Tufts and Helma Dik/Logeion. Preserve that attribution and the license for
reuse, and consult the original metadata for details.

## Download and validate morphological evidence

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\download-morphology.ps1
```

The script obtains the files pinned in `docs/morphology-inventory.json`,
checks their Git blob hashes and runs offline validation. It replaces local
morphology files that differ from the pinned versions; keep edits elsewhere.
The downloaded files are ignored by Git and remain independent of any model.
To repeat validation without downloading, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate-morphology.ps1
```

The selected GLEM word lists contain candidate form-lemma-tag mappings, not
a running analyzer or guaranteed context-sensitive analyses. The AGDT XML
provides contextual annotations for *Euthyphro* only. Validation checks
integrity, UTF-8, XML, list structure and selected attested forms; it also
measures simple exact-form overlap with Plato. This is not linguistic
accuracy or exhaustive coverage. See
`docs/morphology-research.md`, `docs/glem-licensing-review.md`, and the
manifest for licensing and limitations. Commercial use and redistribution of
the GLEM word lists are not cleared: they incorporate PROIEL material, and
the GLEM authors' paper states noncommercial terms despite later GPL software
metadata.

## Plato source and reuse

The corpus comes from [PerseusDL/canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit).
The pinned revision and exact inventory are recorded in the manifest and
inventory. The original XML headers and CTS files remain unchanged.
Perseus says repository contents are generally CC BY-SA 4.0 unless otherwise
indicated, and asks that modifications be offered back. Individual material
may have different copyright status; check the downloaded upstream README,
license and individual XML headers before reuse. The collection is a work in
progress, and its headers have not all been checked for accuracy.
