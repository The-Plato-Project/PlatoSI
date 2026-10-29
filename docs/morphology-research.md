# Ancient Greek morphology research

## Selected offline evidence

- [GLEM](https://github.com/GreekPerspective/glem), pinned at
  `590175899090aa5c3fe647149a85412351463da2`, supplies precomputed lists:
  a PROIEL-frequency list, a merged PROIEL/Perseus form-lemma-tag list, and
  a supplemental punctuation list. They are UTF-8 text and can be inspected
  offline on Windows without installing Python, Frog, or a model. Each row is
  a candidate association, not necessarily a unique or contextually correct
  analysis. Exact matches may miss spelling and accent variants. The upstream
  documentation describes the sources, but does not trace every row to a
  particular text or author. GLEM itself is not being installed.
  Its package metadata declares GPL-3.0-only for the software, but the
  authors' paper describes a PROIEL-derived list and states CC BY-NC-SA 3.0
  for GLEM. Commercial use and redistribution of these lists are not cleared.
  See the [licensing review](glem-licensing-review.md).
- [Perseus Ancient Greek Dependency Treebank 2.1](https://github.com/PerseusDL/treebank_data/tree/master/v2.1/Greek),
  pinned at `bf4334f0af5e13d16b04c1cccd6237e683ac6f5f`, contains
  context-specific form, lemma, and morphological tag annotations in XML.
  We preserve the *Euthyphro* treebank, tagset and source documentation, not
  the rest of the treebank. It was semi-automatically annotated with Morpheus
  assistance and later normalized; its own README identifies remaining
  annotation issues. The file's source edition and variants may differ from
  the project's Plato corpus. The repository README states CC BY-SA 3.0 US,
  subject to third-party rights; credit Perseus and the listed annotators.

The [manifest](morphology-manifest.json) reports observed sample matches,
ambiguities and missing data; the [inventory](morphology-inventory.json) pins
and identifies every downloaded file. The validation script uses NFC for
comparison only and never modifies source data.

## Other options

- [Morpheus](https://github.com/perseids-tools/morpheus) at
  `ab6898ffed335fc6169fa02c9940657a9b5a78e0` is an actual Greek/Latin
  morphological analyzer, not merely a precomputed mapping; its stem libraries
  are in the repository. The README documents Linux/macOS C builds (make, gcc
  and flex on Linux) or Docker, with Greek examples in Beta Code. No native
  Windows instructions are supplied. Offline operation is possible after a
  successful build, but compiling or installing Docker is outside this phase.
  Its repository has an MPL-2.0 license file; check individual data provenance
  and applicable terms. No Morpheus executable was acquired or tested.
- [UD Ancient Greek Perseus](https://github.com/UniversalDependencies/UD_Ancient_Greek-Perseus)
  supplies offline CoNLL-U form, lemma and morphology annotations converted
  from the AGDT; its listed works do not include Plato. Its README and license
  specify CC BY-NC-SA 2.5. It is useful supplementary evidence, not an
  inflection generator.
- [UD Ancient Greek PROIEL](https://github.com/UniversalDependencies/UD_Ancient_Greek-PROIEL)
  has annotated New Testament and Herodotus rather than Plato. Its README
  specifies CC BY-NC-SA 3.0 while its license file links to 4.0 despite naming
  3.0, so clarify the discrepancy before relying on its license terms.
- [Eulexis](https://github.com/biblissima/eulexis) is archived and points to a
  successor; it requires separate data downloads and a PHP environment. Its
  README declares CC BY-NC 4.0 for the program and credits Diogenes and
  Perseus for lemmatization/flexion data; verify data rights separately.
- [Gorman Trees](https://github.com/perseids-publications/gorman-trees) includes
  an annotated *Apology*, but its README calls the treebank license CC0 while
  `TREEBANK_LICENSE` contains CC BY-SA 4.0. Clarify that discrepancy before
  reuse or distribution.

The manifest also measures exact NFC form overlap against the merged list
across the pinned Plato editions, using simple Greek-letter runs as tokens.
This intentionally case-sensitive, accent-sensitive estimate splits on
apostrophes and punctuation; it is not an accuracy measure or evidence that a
candidate is contextually correct. It and the samples do not eliminate the
need for context-sensitive linguistic review.
