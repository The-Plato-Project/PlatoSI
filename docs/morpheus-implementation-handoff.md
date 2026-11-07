# Plato morphology implementation handoff

Updated 6 November 2026.

## Current state

- The legacy Docker/Ruby/HTTP direction has been removed.
- `plugins/morpheus/provider.py` calls the pure-Python ikelos analyzer
  in-process and preserves every returned reading.
- `requirements-morphology-build.txt` pins `ikelos==0.1.0.dev1` by wheel hash.
- `DialogueLexiconIndex` and `DialogueMorphologyIndex` share the normalized
  `data/plato-greek-language-repository-v1.sqlite` database, shipped as
  `data/plato-greek-language-repository-v1.sqlite.xz`.
- Canonical passages and provider/form analyses are stored once; dialogue
  builds use compact membership indexes.
- Normal dialogue lookup reads only a ready artifact and never calls ikelos.
- Reviewed additions and exclusions are separate correction overlays.
- Packaging includes the artifact and its provenance inventory.

## Republic result

The completed Republic build contains 15,078 distinct forms:

- 14,933 analyzed;
- 145 explicitly unresolved;
- zero failed;
- zero pending.

The `καταβαίνω` regression returns six observed forms and seven tokens:

- `καταβαίνειν` — 2
- `κατέβην` — 1
- `καταβαίνων` — 1
- `καταβαίνῃ` — 1
- `καταβὰς` — 1
- `καταβῆναι` — 1

Ambiguity is retained; for example, `καταβῆναι` also has a `καθάπτω`
analysis. `ἀπῇμεν` retains source headword `ἄπειμι2`, normalized dictionary
lemma `ἄπειμι`, and homograph `2`.

## Maintainer commands

```powershell
python -m pip install --require-hashes -r .\requirements-morphology-build.txt
python .\scripts\build-plato-morphology.py --dialogue republic
python .\scripts\check-ikelos-update.py
```

See `docs/morpheus.md` for build, update, correction, attribution, and release
policy.
