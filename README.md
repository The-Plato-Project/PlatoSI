# PlatoSI

A new, independent local AI project for Ancient Greek, initially focused on
Plato. The longer-term aim is to give a local language model reliable access
to Greek primary texts and linguistic references. This setup does not connect
to Chora, Ollama or any model, and does not include search tools or a UI.

## Layout

- `src/` - reserved for future project code.
- `scripts/` - corpus download and validation scripts.
- `data/tlg0059/` - original Plato Greek XML and CTS metadata, downloaded locally.
- `data/upstream/` - the source repository's README and license.
- `docs/corpus-inventory.json` - pinned upstream file paths, sizes and Git blob hashes.
- `docs/corpus-manifest.json` - work and edition metadata, citation declarations and validation results.

Downloaded data, generated indexes and model files are ignored by Git. The
small inventory and manifest are intended to be tracked.

## Download and validate

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

## Source and reuse

The corpus comes from [PerseusDL/canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit).
The pinned revision and exact inventory are recorded in the manifest and
inventory. The original XML headers and CTS files remain unchanged.
Perseus says repository contents are generally CC BY-SA 4.0 unless otherwise
indicated, and asks that modifications be offered back. Individual material
may have different copyright status; check the downloaded upstream README,
license and individual XML headers before reuse. The collection is a work in
progress, and its headers have not all been checked for accuracy.
