# Plato morphology and ikelos

PlatoSI ships a permanent morphology database built from
[ikelos](https://github.com/jmyerston/ikelos), a pure-Python port of Perseus
Morpheus. Readers do not run Morpheus, install ikelos, use Docker, or make an
HTTP request.

## What each resource supplies

- ikelos/Morpheus analyzes an observed Greek form and returns possible lemmas
  and grammatical readings.
- PlatoSI preserves every returned reading and organizes it by canonical
  dialogue and text version.
- The canonical dialogue index supplies token counts, passages, and exact
  locations.
- LSJ/Logeion supplies definitions and other dictionary evidence.
- The reader decides what a form means in context.

Morphological ambiguity is evidence. PlatoSI does not ask a model to select a
reading, collapse homographs, or infer a referent.

## Shipped database

The compact database is `data/plato-morphology-v1.sqlite`. It contains:

- dialogue and canonical text-version identity;
- every distinct observed form and its analyzed or unresolved state;
- every candidate lemma, source headword, homograph, grammatical feature, and
  normalized raw ikelos record;
- exact provider version, source, license, wheel hash, and build policy;
- reviewed correction overlays stored separately from analyzer output.

The current artifact contains the Republic:

- 15,078 distinct forms checked;
- 14,933 forms with one or more analyses;
- 145 explicit no-analysis results;
- no failed or pending forms.

Its full provenance and checksum are recorded in
`docs/plato-morphology-v1-inventory.json`. A build is usable only when every
distinct form is analyzed or explicitly unresolved. Partial and failed builds
are never used for ordinary dialogue lookup.

Normal `linguistics.dialogue-lexicon` requests read this database only. They do
not import ikelos and do not modify the artifact. PlatoSI joins the stored
form-to-lemma evidence to canonical tokens at request time.

## Maintainer build

ikelos is a build dependency, not a reader dependency. Install the exact wheel
and verify its hash:

```powershell
python -m pip install --require-hashes -r .\requirements-morphology-build.txt
```

Build one or more dialogues and regenerate the artifact inventory:

```powershell
python .\scripts\build-plato-morphology.py --dialogue republic
python .\scripts\build-plato-morphology.py --dialogue republic --dialogue phaedo
python .\scripts\build-plato-morphology.py --all
```

Use `--rebuild` only when intentionally replacing an existing build with the
same source identity. Builds are resumable after a failed form. The lower-level
command remains available:

```powershell
python .\scripts\platosi.py index-dialogue-morphology republic
```

The analyzer uses `strict_case=false`, which preserves both capitalized and
lowercase candidates when Morpheus supplies them. The provider normalizes a
numeric headword such as `ἄπειμι2` to dictionary lemma `ἄπειμι` while retaining
the original headword and homograph `2`.

## Direct analysis

Maintainers can query ikelos through the provider:

```powershell
python .\scripts\platosi.py enable morpheus
python .\scripts\platosi.py analyze ἀπῇμεν --include morpheus
```

`linguistics.verify-occurrences` can also analyze a caller-supplied, bounded
set of canonical forms. This is a research check only. It does not update or
replace the shipped database.

## Corrections

Analyzer output is immutable evidence. A reviewed PlatoSI correction is stored
in `morphology_corrections` as either:

- an added analysis record; or
- an exclusion referencing the exact SHA-256 identity of an analyzer record.

Every correction requires a reason, source, reviewer, dialogue, text version,
and form. Reads apply the overlay without deleting or rewriting the original
ikelos record. Corrections therefore remain auditable and dialogue-specific.

## Updating ikelos

The current pin is `ikelos==0.1.0.dev1`; its wheel SHA-256 is
`908f58a9136538f9f65a13fdb858d8f86e9e542914195493d09cade60df31ae9`.
The project is alpha, so PlatoSI never upgrades it automatically.

Maintainers can check PyPI:

```powershell
python .\scripts\check-ikelos-update.py
```

For a proposed update:

1. review the upstream release and source changes;
2. update the exact version and wheel hash;
3. build a separate proposed database;
4. compare changed lemmas, features, newly resolved forms, and newly
   unresolved forms;
5. run Plato-specific regression cases, including all six Republic
   `καταβαίνω` forms and `ἀπῇμεν → ἄπειμι2`;
6. review correction compatibility;
7. publish a new immutable artifact only after approval.

## Attribution and license

ikelos and its bundled Greek stem library are MPL-2.0. PlatoSI credits ikelos
as the analyzer and Perseus Morpheus as the original engine. The artifact
inventory records the exact package and source metadata used for each build.
