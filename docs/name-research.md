# Configuring name research

PlatoSI owns reference retrieval and local-model synthesis; Chora displays the resulting account. The operation is still named `linguistics.person-research`, but proper names can denote places and other entities as well as people. Morphology's proper-name flag is a candidate gate, not identification of the referent in context.

## Sources

Edit [config/name-research-sources.json](../config/name-research-sources.json). Name Research uses two enabled scholarly sources:

| Source | Role |
| --- | --- |
| Platonis Humanistica Digitalia | Plato-specific prosopography of approximately 80 historical people, based primarily on Debra Nails' *The People of Plato*. Its person records and RDF data are CC BY-NC 4.0. Supported Perseus citations in a matched person record are resolved automatically and retained as attributed evidence. |
| Athenian Onomasticon | Current onomastic and prosopographical records for ancient Athens, with stable person IDs and references to LGPN, APF, inscriptions, and other scholarly resources. The public site does not state a data-reuse license, so PlatoSI retrieves search results rather than redistributing its dataset. |

The selected Platonic passage is used only to identify which same-name person is relevant. It is not presented as biographical evidence. Wikipedia, Wikidata, Wiktionary, and Grokipedia are not Name Research sources.

Removing a configured source or setting `enabled` to `false` prevents new requests to that source. There is no source-settings GUI. Each entry has a unique `id`, display `name`, supported `adapter`, HTTPS `endpoint`, language, boolean `enabled`, integer `priority` (lower runs first), and `limit` from 1 to 50. Entries with the same result URL are deduplicated.

The Humanistica adapter downloads the edition page once, extracts its compact person dictionary and source citations, and caches that parsed dataset. For a supported Perseus citation, PlatoSI resolves the cited work through its CTS metadata, retrieves the available Perseus edition, finds references to the matched person's Greek or English name, and retains the cited range or nearby sections. This is general citation traversal; person names and historical passages are not hardcoded. Resolved excerpts are cached and remain attributed to the Humanistica citation.

The Athenian Onomasticon adapter sends a bounded exact-name search and retains separate stable records for every same-name person. The configuration is read for each new research request. Invalid configuration fails explicitly. Source failures become warnings and do not prevent remaining sources from being tried. Humanistica and Onomasticon extracts are bounded to 3,000 characters; resolved citation evidence is bounded to 8,000 characters.

## Synthesis and model selection

The sole enabled chat provider and its configured model are selected through PlatoSI's existing plugin configuration. The source configuration's `synthesis.max_tokens` controls the response budget (default 3,200; accepted range 256–8,192). Chora does not select another model silently.

The model first selects relevant reference IDs using the Greek passage and dialogue to identify the historical subject. The Plato-specific prosopography and its resolved historical citation evidence cannot be discarded during selection. Same-name Onomasticon records remain separate candidates, and unrelated people, offices, titles, and lexical similarities are excluded rather than merged into the person's account.

The writing step receives the selected external evidence. It must give historical identity, family, civic status, political setting, major events, fate, and property or legal consequences when the evidence supplies them. A detailed cited account cannot be reduced to a generic execution sentence: each source has a configured minimum number of supported statements. The model may use supplied external scholarship but may not rely on uncited model memory. Every occupation, status, relationship, and date must be stated by a supplied source. Participation in a philosophical dialogue is explicitly not evidence that a historical person was a philosopher. Source disagreement is retained instead of silently resolved. LSJ and proposed lexical roots are excluded from this workflow; LSJ remains part of dictionary evidence and explicit lexical relationships elsewhere.

The writer must supply an overview plus supporting quotations. The service validates the JSON shape, a nonempty bounded overview, paragraph citations, and that each supporting quotation is an exact substring of its claimed reference after whitespace normalization. Each cited source must have a verified quotation. A separate call to the configured model then reviews the draft against those quotations for unsupported assertions. Rejected writing receives one corrective attempt and review. Invalid source selection, model/network failures, or exhausted corrections produce an explicit partial result. Failed responses are not cached as successful synthesis.

If no usable synthesis is produced, Chora shows one short failure message. It does not dump retrieved namesakes, source links, or raw model errors into the reading panel. The structured response retains warnings for service diagnostics. Exact quotations prove that the quoted text was retrieved, not that a paraphrase follows from it; the model reviewer is also fallible and uses the same configured model. This is not independent factual certification.

Successful synthesis caches cover the prompt policy, lemma, dialogue, passage, evidence, model identity/digest, and token budget. Earlier per-candidate summaries are not reused. The UI lists only the sources cited by a successful explanation.

The current synthesis policy is `name-synthesis-v9`; summaries generated under
earlier policies are not reused. Existing reference-response caches and saved
reader notes are preserved. Restart the service to load changed Python code.

## Integration and saved notes

`linguistics.person-research` still accepts exactly `location` and `lemma`. Its response contract is now **`platosi.person-research.v3`**. It returns `overview`, `sources`, stable `candidates` for reader-note targets, model identity, cache metadata, warnings, and the existing target/classification. Status is `ok`, `partial` (references but no synthesis), `empty`, or `not_candidate`. The old `roots`, `name`, and individual candidate summaries are removed. Update the service and Chora together, then restart Chora to load both changes.

Candidates are retained for notes, not displayed as repeated research cards. Existing Wikidata note identities remain available from the local cache after Wikidata's removal; their old descriptions are not sent to the model or shown as current research sources. This makes no new Wikidata requests and does not delete reader notes.
