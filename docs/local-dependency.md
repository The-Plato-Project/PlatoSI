# PlatoSI local dependency

PlatoSI can run as a local child process without Chora or an AI model. The
`0.1.0.dev1` portable archive is a development build, not a published stable
release. It contains PlatoSI code, provider adapters, inventories, and the
versioned Plato morphology database. It does not contain Python, downloaded
canonical or dictionary corpora, model files, private configuration, or reader
data.

## Requirements and installation

- Windows with Python 3.10 or later. Python must be installed separately;
  no third-party Python packages are needed for the canonical text API.
- A writable installation directory and internet access for initial corpus
  setup. Once built, canonical text lookup works offline.
- The archive and its `.sha256` file. Obtain both from a source you trust;
  an unsigned checksum detects accidental corruption but is not a signature.

For example, after downloading the files, set the paths and compare the
checksum in PowerShell:

```powershell
$archive = 'C:\path\to\platosi-local-0.1.0.dev1.zip'
$python = 'C:\path\to\python.exe'
$install = Join-Path $env:LOCALAPPDATA 'PlatoSI\0.1.0.dev1'
$expected = ((Get-Content -LiteralPath "$archive.sha256" -Raw).Trim() -split '\s+')[0]
$actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'PlatoSI archive checksum mismatch.' }
if (Test-Path -LiteralPath $install) { throw 'Choose a new installation directory.' }
Expand-Archive -LiteralPath $archive -DestinationPath $install
& $python -I (Join-Path $install 'scripts\build-canonical-corpus.py')
if ($LASTEXITCODE -ne 0) { throw 'Canonical corpus setup failed.' }
& $python -I (Join-Path $install 'scripts\check-local-dependency.py')
if ($LASTEXITCODE -ne 0) { throw 'PlatoSI dependency check failed.' }
```

The builder downloads pinned Perseus XML and source README/license files,
verifies them, and creates the 35 canonical works under the installation's
`data/canonical-text-v1/`. It does not read or require Chora. Repeat the
builder to verify existing sources and regenerate the works; it reports
modified source files instead of replacing them. `--dialogue republic`
builds just that work, but the complete catalogue and dependency check require
all works. See `docs/text-location-contract.md` for text and location versions.

The Republic morphology artifact is included, so ordinary Republic occurrence
retrieval is local and needs neither ikelos nor a service. LSJ data, Ollama,
models, and canonical source XML are not included. Maintainers need the pinned
ikelos wheel only when rebuilding the artifact or performing direct analysis.
See `docs/morpheus.md`, `docs/retrieval.md`, and the provider notices.
The Perseus repository license is generally CC BY-SA 4.0, but review each
edition's TEI header and applicable terms. This distribution does not assert
that third-party artifacts are cleared for every use or redistribution.

## Connecting a local client

Launch the service using the installed Python and absolute script path:

```text
python -I -u <installation>\scripts\reader_api.py
```

`-I` isolates the process from Python environment variables and user site
packages; `-u` keeps protocol output unbuffered. If an optional provider
requires third-party Python packages, use a separately managed Python
environment that has those packages installed. Keep the installation writable
for local data, indexes, and configuration. No network port is opened by the
local-process API.

Write one UTF-8 JSON object per line to standard input and read one UTF-8 JSON
object per line from standard output. Standard output is reserved for
protocol messages; read standard error separately for process diagnostics.
Do not treat process startup as readiness: send this request and wait for its
response before issuing dependent work:

```json
{"version":1,"id":"hello","operation":"system.info","payload":{}}
```

An `ok` response returns `service`, the PlatoSI build `version`,
`protocol_version`, and `location_contract`. A client must check the
supported protocol before sending requests. `capabilities` reports which
operations are currently available; a partial corpus supports installed
works, but `canonical.catalog` requires all 35.

Use `canonical.catalog` to find dialogue IDs and text fingerprints,
`canonical.work` to obtain a dialogue or division, and `canonical.resolve`
to retrieve a selection by dialogue, fingerprint, Stephanus boundaries and
UTF-16 offsets. Do not send selected Greek as part of the location. The
contract is in `docs/text-location-contract.md`. For example:

```json
{"version":1,"id":"catalog","operation":"canonical.catalog","payload":{}}
{"version":1,"id":"book","operation":"canonical.work","payload":{"dialogue":"republic","division":{"type":"book","label":"1"}}}
{"version":1,"id":"word","operation":"canonical.resolve","payload":{"location":{"dialogue":"republic","text_version":"sha256:0d5d71f80d42eee6ec5c5328d1d1926789ddb327f53c8787131b1a20aa4af5ef","start":{"stephanus":"327a","offset":0},"end":{"stephanus":"327a","offset":7}}}}
```

In normal client code, take the full fingerprint from the installed work's
catalogue response and retain it with any saved location. The example version
identifies the current *Republic* baseline, not all future releases.

Each active request needs a unique nonempty string `id`. Responses echo it
and may arrive out of order. Terminal statuses are `ok`, `invalid`, `failed`,
and `cancelled`; errors must be shown to the caller. Send `request.cancel`
with a new request ID and `{"id":"<target>"}` to request cooperative
cancellation; its acknowledgement does not replace the target's terminal
response. Closing standard input requests cancellation of outstanding work
and shuts down the service. Wait for the process to exit and surface a
nonzero exit code or diagnostics. Messages are limited to 2 MB, responses to
8 MB, and concurrent requests to 16. The protocol is version 1; incompatible
request versions are rejected.

## Updates and data

Install a new release into a **new directory**, leaving the old installation
and its `data/` untouched until the new version is checked. Corpus files can
be rebuilt in the new installation; copying existing corpus data is only
safe after checking the new release's inventory and fingerprints. Different
text fingerprints are different versions and must not be silently substituted
for persisted locations. Review optional provider paths and configuration
before copying them. PlatoSI does not store or migrate Chora's reader graph.

To create an archive from a PlatoSI development checkout, run
`python -I scripts\package-platosi.py`. It writes a ZIP and SHA-256 sidecar
under `dist/`, refusing to overwrite an existing release. The archive's
`release-manifest.json` records per-file hashes and the service, protocol,
and location-contract versions. Generating a local archive does not publish
it to GitHub or assign a project license.
