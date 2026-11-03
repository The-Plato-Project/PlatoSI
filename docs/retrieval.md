# Offline retrieval architecture

## Boundaries and attribution

The core in `src/platosi` knows only provider capabilities. It discovers
`plugins/*/plugin.json`, dynamically loads the named module, and calls the
capability methods in `contracts.py`; it does not import specific adapters.
Manifests describe a provider ID, type, adapter version, capabilities,
configuration, source revision, attribution and licensing. Several providers
can implement the same capability; their results remain separate.

`CorpusProvider` offers `search` and `passage`, `DictionaryProvider` offers
`lookup`, and `MorphologyProvider` offers `analyze`. The
`LanguageModelProvider` and general `ScholarlyResourceProvider` protocols
define interfaces for independently installed resources. `retrieve`
passes a JSON object to selected scholarly providers implementing `retrieve`;
no general analytical provider is currently implemented. The Ollama model
provider is independent of the resource providers. Provider code executes
locally: install only trusted plugins. The retrieval core does not make an
interpretation or generate hypotheses; the model inquiry layer may offer
explicitly tentative interpretations.

Each supplied adapter's result identifies its provider and version, upstream
repository and revision, attribution, license status, and a source location. Corpus results
represent source-edition evidence, LSJ entries are scholarly classifications,
and GLEM results are *candidate* mappings, not verified contextual analyses.
`editorial_text` marks search matches overlapping the explicitly indexed
editorial TEI tags listed below. No automatic claim combines evidence from
different providers; an interpretive hypothesis would require its own
explicit attribution and must not be presented as a source assertion.

## Installation, configuration and indexes

See the README for commands. Acquire each source using its existing download
script, then index that provider individually. Each adapter has its own SQLite
file under `data/indexes/`; rebuilding one never reads or rebuilds another.
The downloaded sources and indexes are ignored by Git. Builds verify the
selected source files' Git blob hashes and counts against the relevant pinned
inventory, fail on missing, extra or altered selected files, and replace the
index only after a successful build. This checks the selected input files, not
all ancillary files; run the original validation scripts for full checks.
Changing the manifest's version, source or configuration makes its old index
unavailable until rebuilt. Source changes *after* a build are not monitored:
revalidate and rebuild when source files change.

Enable or disable with `enable ID` or `disable ID`; state is saved locally in
ignored `data/plugin-config.json`. To remove a provider, disable it and remove
its own plugin directory and, if desired, its own local source and index.
Other providers do not depend on these files. If a provider's source, index,
or matching index metadata is absent, `status` marks it unavailable and
unrelated operations continue. A corrupt index or plugin error is surfaced,
not silently treated as a successful empty search.
Retrieval responses list `available_providers`; if none supports the operation,
an explicit `message` distinguishes that condition from a search with no
matches. `selected_resources` reports missing, disabled, unavailable,
unsupported and text-first-suppressed choices. The `providers` list describes
installed resources and their enabled and selected states. Its `available`
value is null when availability was not checked, such as for an unselected
provider; unselected provider code is not loaded by retrieval. Use `status`
to check availability of all enabled providers.

To change paths, add a `config` object for the provider in
`data/plugin-config.json`; values override its manifest, and may be absolute
or relative to the project root. For example:

```json
{
  "lsj-logeion": {
    "enabled": true,
    "config": {"source": "D:\\Greek\\lsj", "index": "D:\\Greek\\indexes\\lsj.sqlite"}
  }
}
```

The default inventory is retained in this example. When using different
source data or revisions, supply a matching inventory and source metadata in
the provider manifest rather than attributing new data to the pinned revision.
GLEM is disabled by default and isolated: its list and derived index are not
packaged or copied into another provider. Its commercial use and
redistribution are **not cleared**. See `glem-licensing-review.md`.

## Experimental word exploration

The separate browser reader uses the optional `reading` corpus capability
to retrieve exact indexed source text, citation milestones and editorial
markup. Greek-word offsets are Unicode code-point offsets into that text;
browser rendering preserves the original form. The reader calls enabled,
selected morphology and dictionary providers locally and keeps each analysis
and its provenance separate. Failures are reported without discarding results
from other providers. A profile's text-first setting and explicit overrides
have the same meaning as elsewhere.

The optional `match_forms` morphology capability accepts a candidate lemma
and surface forms from the current source scope. GLEM and Dilemma return
their own direct lookup mappings; the reader joins those mappings to actual
text offsets and citations. This does not establish contextual correctness
or exhaustive coverage, and does not infer compounds or roots. It does not
reconstruct corpus passages with a model.

Dilemma requires its separate Python package and local data, and is disabled
by default. The adapter calls verbose lemmatization with `guess=False` under
both article-resolution settings. It labels lookup candidates and
rule-generated suggestions separately; this is not an exhaustive enumeration
and neither class is authoritative. Occurrences use direct lookup rows only.
The artifact revision in configuration is an unverified declaration, and
the reported file-metadata fingerprint is not a content hash. Dilemma's
process-wide data directory is fixed on import: restart after changing it.
See `dilemma-phase1-evaluation.md` for the evaluation and unresolved artifact
licenses.

Optional AI examination sends a bounded, attributed package to each selected
model independently; the validator never receives the primary model's answer.
Long dictionary entries are explicitly marked as truncated. The adapter
requests structured JSON where supported and checks candidate names, evidence
IDs and completeness, but this cannot establish semantic accuracy. Invalid,
truncated and unavailable responses are shown rather than cached as success.
The ignored SQLite cache contains evidence and outputs, is keyed by evidence,
prompt, provider identity and configuration digest, model digest and settings,
and is only used when both model digests are available. Reader notes and
exploration choices remain in browser local storage and are not included.

## Reader profiles and inquiry selection

Profiles are stored in the ignored `data/reader-profiles.json`, independently
of provider manifests, enablement, indexes and language models. Each named
profile is an object containing an ordered `resources` array of provider IDs
and a boolean `text_first`. The order is global across provider types; within
an operation it determines provider invocation and result order, not a
ranking of truth. Multiple results and conflicting source assertions remain
separate, with each provider's attribution intact.

Use `profile save NAME --resource ID ...` to create or replace a profile;
add `--text-first` to enable that mode. `profile show NAME` and
`profile list` inspect saved settings. Saving replaces the whole profile,
including its mode, and an empty resource list intentionally selects nothing.
IDs need not currently be installed. A missing, disabled, unsupported or
unavailable selection is reported, not deleted from the profile or silently
enabled. If it later becomes available, it can be selected again.

For `search`, `passage`, `lookup`, `analyze` and `retrieve`, `--profile NAME`
chooses the saved preference list. Without a profile, all installed providers
are considered in registry order, preserving the previous default. Repeated
`--include ID` options instead select exactly those IDs in the supplied order
for this inquiry, including IDs absent from the profile. Repeated `--exclude
ID` options remove IDs from that inquiry; an ID cannot be both included and
excluded. Overrides never mutate the profile or bypass global enablement.
The response echoes the overrides and includes selection diagnostics.

Text-first mode considers only providers whose manifest type is `corpus`
unless an explicit `--include` list is supplied for the inquiry. This applies
even to an explicit dictionary, morphology or scholarly operation; include
the desired provider to consult it. No provider is invoked automatically by
another operation, and each command only calls providers advertising its
capability. `retrieve` accepts a JSON-object query whose interpretation is
provider-specific; its provider results are not merged or normalized.

## Local model inquiries

The `LanguageModelProvider` contract exposes availability, model discovery
and generation. The registry loads the `ollama` adapter like any other
plugin; no corpus or scholarly provider imports it. `models --provider ollama`
discovers currently installed local models. If exactly one enabled model
provider supports the operation, `--provider` may be omitted; if several do,
the reader must choose one. Implement the same interface in another trusted
model plugin to replace Ollama without rebuilding indexes or changing profiles.

The Ollama adapter connects only to a loopback HTTP origin, uses no HTTP proxy
or redirect following, excludes models advertised as remote/cloud, and never
pulls a model. Start the server and install a model separately. Its default
model is `qwen3.5:9b`, but availability is checked against the live model
list: a missing model causes an explicit error. Use `--model NAME` to select
another, or update the `ollama` config entry in ignored
`data/plugin-config.json`. The adapter's `endpoint`, `model`,
`timeout_seconds`, `think` and `generation` settings can be overridden there
without changing other provider configuration. For example, an `ollama` entry
can contain:

```json
{
  "config": {
    "model": "qwen3.5:4b",
    "generation": {"temperature": 0.2, "num_predict": 500}
  }
}
```

`--generation` supplies a JSON object of per-inquiry generation settings
that override adapter defaults; the available keys depend on the adapter.
In Windows PowerShell 5.1, escape the JSON quotes when passing it to a native
program, for example `--generation '{\"temperature\":0.1}'`.
The Ollama server and each model have separate licensing terms; inspect those
terms before use.

`inquire` accepts a question, `--profile`, per-inquiry `--include` and
`--exclude`, and either `--edition` plus `--citation` or `--text` for an
exact Greek word or phrase. It searches Greek words in the question if no
reference or explicit search text is provided. It does not resolve an English
reference or perform semantic search. Search uses the existing matching mode,
with `--mode accent-insensitive` available explicitly.

Unlike standalone lookups, an inquiry with no profile and no explicit
inclusions selects only corpus providers. A profile enables its selected
scholarly resources; text-first profiles suppress them unless explicitly
included for the inquiry. An `--include` list replaces the selection, so
include a corpus provider alongside any desired scholarly providers.
Selection never enables a disabled provider. Missing or unavailable selections
are reported without changing saved preferences.

Dictionary and morphology providers receive literal reader-supplied
`--headword` and `--form` terms, or, if omitted, Greek words present in the
question or `--text`. They do not receive model-generated terms or
automatically inferred lemmas, and no GLEM result is fed into LSJ. Repeated
options supply multiple terms. `--scholarly-query` supplies a JSON object to
selected general scholarly providers; none is invoked without that query.
The per-provider, per-operation `--limit` defaults to three, and reaching it
is reported as possibly truncated.

Only retrieved records are sent to the model, with source metadata and
distinct evidence IDs. For passage retrieval, the exact returned match span
is sent rather than the larger surrounding textpart; editorial markup spans
are adjusted accordingly. Search results can include a larger textpart and
their Stephanus reference applies at the match, not necessarily throughout
that context. If no Greek passage is retrieved, the model is not called and
the response explicitly reports the missing evidence.

The prompt asks for textual observations to be distinguished from tentative
interpretation, for scholarly claims to be attributed, and for unsupported
facts not to be invented. The readable output shows model attribution,
evidence IDs, sources and Greek text; `--json` includes full records,
selection diagnostics and warnings. Unknown `[E<number>]` citations and
responses without evidence IDs produce warnings, but IDs are not semantic
fact checking. **A model can still invent or misinterpret claims even with
these instructions and valid citations.** In live testing, one response
incorrectly named a festival without evidence and another supplied an
unrequested morphological analysis without a morphology provider. The
prompt was tightened after those results, but this is not a guarantee. Treat
model output as unverified, and compare it with the returned records and the
original XML before accepting a claim.

## Experimental browser playground

The separate `scripts/playground.py` server and `playground/` browser assets
provide an in-memory conversation without changing provider indexes or reader
profiles. By default it listens only on `127.0.0.1`. The opt-in `--lan` mode
binds `0.0.0.0`, displays detected private IPv4 URLs, and requires a
per-process, randomly generated access token. Successful login creates an
in-memory, HttpOnly, SameSite=Strict session cookie. LAN mode rejects public
client addresses and unknown host headers; both modes enforce matching
host/origin checks on POST requests. The server does not modify Windows
Firewall. See the README for the Private-profile, local-subnet firewall rule.
Ollama remains local to the Lenovo.

LAN HTTP is not encrypted, so the token and conversation are observable on
the network. Use it only on a trusted private network and do not port-forward,
expose a public tunnel, or put it behind a reverse proxy. Application checks
and Private firewall rules cannot prevent exposure caused by unsafe router or
proxy configuration.

Model adapters may advertise `chat` and implement `ChatLanguageModelProvider`:
`chat(messages, options, cancellation)` receives explicit system/user/assistant
messages and must stop its in-flight request when the cancellation token is
triggered. The Ollama adapter uses its local chat endpoint and closes the
active connection on cancellation; adapters without this capability remain
usable through the existing CLI but are not listed in the playground. The
playground's editable system prompt is sent as the system message. It adds no
retrieval instructions in Free Conversation and never calls resource
providers in that mode.

Text-Grounded Inquiry calls `inquire` with the selected profile and optional
resource override, then uses the chat adapter for generation. The existing
grounding instructions are displayed in the interface and sent along with
the retrieved evidence; the editable system prompt is also sent. Previous
conversation messages are retained in browser memory and supplied with the
next request, but the complete prior evidence records are not automatically
re-retrieved. New Conversation clears the browser history and cancels any
active generation. A page reload also clears browser history.

## Matching and source text

Exact mode is case-sensitive and accent-sensitive, but it is **not byte
matching**: it applies canonical Unicode NFC and collapses runs of Unicode
whitespace to one space in the search key. Thus NFC and NFD spellings match,
and a phrase can cross XML element or line boundaries if the concatenated
source text contains the appropriate whitespace. No whitespace is invented
between elements. Punctuation is literal, and a query beginning or ending
with a Unicode letter, mark, number or underscore must have a non-word
boundary on that side. Inflected and similarly spelled words are not stemmed
or treated as equivalent.

Accent-insensitive mode additionally removes all Unicode combining marks,
including breathings and iota subscript; this can conflate distinct Greek
forms. It remains case-sensitive. Neither search mode changes returned text.
The corpus adapter indexes concatenated TEI body descendant text and uses
SQLite `instr` for candidate editions, then checks explicit Unicode
boundaries and maps matches back to original character offsets. It does not
use FTS5. Tests show SQLite's default FTS5 tokenizer does not equate NFC and
NFD Greek or remove Greek accents for the tested word, so default FTS5
behavior is not substituted for these semantics.

Passages use the XML-parsed body text, preserving its Greek characters and
whitespace as parsed (XML entities and line endings follow XML parser rules),
with work and edition URNs, hierarchical `textpart` paths, source
`refsDecl` declarations and the latest preceding Stephanus page/section
milestones when present. `passage` accepts a dot-joined textpart path (for
example `1.327`) or a Stephanus section (for example `327a`). A search across
adjacent textpart divisions may return text from both. Citation structures
vary by edition; this is not a general CTS resolver, and absent or malformed
source milestones cannot be inferred. Milestones in a returned passage are
not themselves textual characters. The `match` and its offsets identify the
requested span; `text` may include the surrounding textpart for context.

Flattening TEI body text includes its descendant text, including speaker
labels, bibliographic references and editorial additions/deletions when
present; it is not a normalized reading text. The `source_markup` field
reports spans for `del`, `add`, `label`, `bibl`, `sic`, `corr`, `head` and
`gap`, relative to returned passage text. Search matches overlapping these
nonempty spans are labeled `editorial_text` rather than `primary_text`.
Other TEI markup is not fully interpreted, and a zero-width gap is not a
match. Consult the original XML before making a textual claim.

LSJ lookup matches the complete displayed `head` text, not an automatically
inferred lemma or an inflected form. Entries are stored by source file and
ordinal, so duplicate upstream IDs are not collapsed. The returned entry XML
is a parsed/reserialized representation, not a byte-for-byte copy; the
original file remains authoritative. GLEM's source list supplies a form,
lemma and raw tag, but not per-row PROIEL-versus-Perseus attribution or
context-sensitive disambiguation. Each result includes its source line.

`--limit` is per provider; providers reaching it are named in
`possibly_truncated_providers`. Increase it to retrieve more matches. Search
scans normalized edition text rather than using a token index, favoring
predictable behavior over large-corpus performance.

## Verified examples and limits

The original XML and source lists were checked by the automated real-data
tests. The Republic opening phrase `κατέβην χθὲς εἰς Πειραιᾶ` is found in
`urn:cts:greekLit:tlg0059.tlg030.perseus-grc2`, Stephanus 327a.
Exact searches also find `βουλόμενος`, `ἔδοξεν`, and `καταλιπὼν` in the
corpus. The optional GLEM list associates these four forms respectively with
`καταβαίνω`, `βούλομαι`, `δοκέω`, and `καταλείπω`; these are source
candidates, not contextual determinations. LSJ has an exact headword entry
for each of those four lemmas. Each resource is queried independently.

Some source citations are absent or unsupported by this adapter; no citation
is invented. The previously tested exact form `προσευξόμενός` has no GLEM
match. A missing match is not evidence that no analysis exists. Duplicate
LSJ IDs and multiple morphology candidates are returned separately.
