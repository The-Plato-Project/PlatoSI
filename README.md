# PlatoSI

A new, independent local AI project for Ancient Greek, initially focused on
Plato. The longer-term aim is to give a local language model reliable access
to Greek primary texts and linguistic references. The current offline retrieval
layer is model-agnostic. It does not connect to Chora, Ollama or any model,
and does not include a UI.

## Layout

- `src/platosi/` - provider contracts, registry, Unicode search and CLI.
- `plugins/` - independent corpus, dictionary and optional morphology providers.
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
