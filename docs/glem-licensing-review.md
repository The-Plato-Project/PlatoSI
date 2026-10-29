# GLEM morphological data: provenance and licensing review

Reviewed 29 October 2026. This is a technical licensing assessment, not legal
advice; a rights holder or qualified counsel should confirm the proposed use.

## Conclusion

**Commercial use and redistribution of the downloaded GLEM word lists are
not cleared.** The GLEM authors explicitly describe the merged list as
derived from PROIEL and Perseus, and the original PROIEL treebank is offered
under a noncommercial license. The 2017 GLEM paper itself states that GLEM
was created under CC BY-NC-SA 3.0, while later package metadata declares
GPL-3.0-only. Neither statement establishes an independent commercial grant
for every underlying data component.

Do not ship the lists, incorporate them into a commercial application or its
distributed indexes, or assume that a hosted commercial service avoids the
issue, until the relevant rightsholders provide written permission or counsel
determines that a specific use does not require their permission. This is a
clearance recommendation, not a finding that every individual word or
form-lemma pair is copyrightable. It does not require deleting the existing
local research copies. The existing overlap measurements are research results,
not evidence of permission to ship their source data.

## What the downloaded files contain

The review concerns [GLEM revision
`590175899090aa5c3fe647149a85412351463da2`](https://github.com/GreekPerspective/glem/tree/590175899090aa5c3fe647149a85412351463da2).
The project's [inventory](morphology-inventory.json) pins the original Git
blob hashes.

| File in GLEM's `glem/` directory | Contents and lineage | Clearance status |
| --- | --- | --- |
| `list_proiel_perseus_merged_word_lemma_POS_nofreq` | 377,255 rows of form, lemma and tag; the authors describe merging converted PROIEL and Perseus lexicons. A row is a candidate mapping, not necessarily a unique or contextually correct analysis. | Not cleared for commercial use or redistribution. |
| `list_proiel_word_lemma_POS_freq` | 34,494 lines of form, lemma, tag and frequency; three lines have malformed frequency fields. The authors describe the PROIEL lexicon as derived from annotated Herodotus. | Not cleared; PROIEL noncommercial terms are directly relevant. |
| `extra-wlt.txt` | 10,324 supplemental punctuation rows, described as such in GLEM's documentation. | Provenance and separate data rights not established; do not assume the same answer as for the other lists. |

These are row counts, not counts of unique forms or guaranteed correct
analyses. There are no row-level source identifiers establishing which rows of
the merged list came from which upstream source. A match with a Perseus entry
does not prove that the corresponding GLEM row is free of PROIEL-derived or
other rights.

## Trace to the original resources

1. In section 3, page 92, of the [authors' 2017 paper, *A Memory-Based
   Lemmatizer for Ancient Greek*](https://github.com/GreekPerspective/glem/blob/590175899090aa5c3fe647149a85412351463da2/GLEM_paper.pdf)
   ([DOI](https://doi.org/10.1145/3078081.3078100)), Bary, Berck and
   Hendrickx say they used PROIEL's annotated Herodotus, as available in
   February 2015, to make a frequency lexicon; they also used a separate
   Perseus form-lemma-POS lexicon. They converted the Perseus Beta Code to
   Unicode, mapped both tag sets to a common 10-character scheme, and merged
   the lexicons without frequency information. This establishes dataset-level
   provenance, but not the source of each individual row.
2. The paper points to the [Perseus open-source download
   page](https://www.perseus.tufts.edu/hopper/opensource/download) for its
   Perseus lexicon. That page licenses its **text files** under CC BY-SA 3.0
   US and separately lists database dumps, including `hib_lemmas` and
   `hib_parses`. It does not identify which exact archive or snapshot GLEM
   used, or clearly state that the text-file license covers every generated
   database dump. The license of that particular input remains to be confirmed
   by Perseus.
3. The [2017 data-addition commit](https://github.com/GreekPerspective/glem/commit/ca2f96be75a388a54eca60140a01d571421ed05d)
   added `proiel_v3_perseus_merged.txt` with Git blob
   `3b11461887a66b5c9f82baa1079d0c863d809d84` and the frequency list
   `greek_Haudag.pcases.lemma.lex.rewrite_new` with blob
   `dfb301c7036ec0853a230597276bae6bb66753c4`. Subsequent
   [2018 cleanup](https://github.com/GreekPerspective/glem/commit/586ffba6364c0963a69c111d4bdf536cf9c9ea8a)
   and [rename](https://github.com/GreekPerspective/glem/commit/cae7b9a5e2106e909f9ea0a3d11c6806373562bc)
   identify the current filenames. The blob hashes are unchanged. Git history
   corroborates continuity of the files, not a per-row rights grant.
4. The upstream [GLEM lexicon documentation](https://github.com/GreekPerspective/glem/blob/590175899090aa5c3fe647149a85412351463da2/doc/glem.tex)
   describes the three- and four-column lists and punctuation file. Its older
   example names are not by themselves a license or a provenance breakdown.

## Licenses and conflicts

| Material | Authoritative statement and practical effect |
| --- | --- |
| Original PROIEL treebank | The [PROIEL project README](https://github.com/proiel/proiel-treebank/blob/8e388967a1335ed12335ddc655fe46993ee7d57a/README.md) states **CC BY-NC-SA 3.0 US**. Its [license](https://creativecommons.org/licenses/by-nc-sa/3.0/us/legalcode.en) permits copying, redistribution and adaptations for noncommercial purposes with attribution and share-alike conditions; it does not grant commercial use. The precise copyright/database-rights status of a particular extracted list and a proposed use requires legal review. |
| GLEM paper's statement about GLEM | Page 92 of the [paper](https://github.com/GreekPerspective/glem/blob/590175899090aa5c3fe647149a85412351463da2/GLEM_paper.pdf) says: “GLEM is created under the Creative Commons Attribution- Non-Commercial-ShareAlike 3.0 License.” It does not identify a jurisdiction or provide a separate file-by-file grant for the downloaded lists. This statement concerns GLEM as described in the paper; it is not itself proof that all later files have that exact license. |
| GLEM package/software | Pinned [`setup.py`](https://github.com/GreekPerspective/glem/blob/590175899090aa5c3fe647149a85412351463da2/setup.py) declares `GPL-3.0-only` and includes all three lists in package data; pinned [`codemeta.json`](https://github.com/GreekPerspective/glem/blob/590175899090aa5c3fe647149a85412351463da2/codemeta.json) also identifies GPL-3.0-only as the software license. [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.en.html) permits commercial use, modification and distribution subject to its conditions, including source and copyleft obligations on conveyance. Package metadata is evidence of the project's declaration, but does not establish that the authors could remove third-party noncommercial restrictions. It is not a substitute for a data-specific grant. |
| Perseus AGDT 2.1, a separate resource | The pinned [Perseus treebank README](https://github.com/PerseusDL/treebank_data/blob/bf4334f0af5e13d16b04c1cccd6237e683ac6f5f/README.md) states **CC BY-SA 3.0 US**, while reserving third-party rights. The [license](https://creativecommons.org/licenses/by-sa/3.0/us/legalcode.en) permits commercial use, modification and redistribution with attribution, indication of changes and applicable share-alike conditions. The [Greek README](https://github.com/PerseusDL/treebank_data/blob/bf4334f0af5e13d16b04c1cccd6237e683ac6f5f/v2.1/Greek/README.MD) credits annotators and says Morpheus assisted morphological annotation. This is useful alternative evidence, **not proof** that the separate Perseus input used in GLEM was that AGDT release or had the same terms. |
| UD PROIEL conversion, not the GLEM input identified in the paper | Its [README](https://github.com/UniversalDependencies/UD_Ancient_Greek-PROIEL/blob/a4ab8d436de97d4598d410d91ea20b4127d04a5f/README.md) names **CC BY-NC-SA 3.0**. Its [license file](https://github.com/UniversalDependencies/UD_Ancient_Greek-PROIEL/blob/a4ab8d436de97d4598d410d91ea20b4127d04a5f/LICENSE.txt) says 3.0 Generic but links to 4.0. Both versions are noncommercial; ask the maintainer which version applies. This discrepancy must not be used to assign a different license to the 2015 GLEM input. |
| UD Perseus conversion, not the original Perseus AGDT | Its [README](https://github.com/UniversalDependencies/UD_Ancient_Greek-Perseus/blob/331ddef91411d0e6549744ee889e05549e6da77d/README.md) and [license file](https://github.com/UniversalDependencies/UD_Ancient_Greek-Perseus/blob/331ddef91411d0e6549744ee889e05549e6da77d/LICENSE.txt) state **CC BY-NC-SA 2.5**, despite conversion from AGDT. Do not substitute the source AGDT's commercial-use terms for those of this particular conversion. |

The GLEM paper's noncommercial statement and the later GPL software metadata
are materially different public signals. We have not located a data-specific
relicensing announcement, a source-by-source breakdown, or permission from
PROIEL to use or redistribute its contribution commercially. It is therefore
not established that GPL applies to each list, or that GLEM's authors could
grant rights held by upstream parties. Nor is it established that the paper's
statement alone resolves every file's current license.

## Alternatives with documented commercial-use grants

These are candidates for review, not drop-in replacements or a blanket
clearance of every third-party component:

1. **Original Perseus AGDT 2.1**, described above, explicitly grants
   commercial use under CC BY-SA 3.0 US for repository material, subject to
   third-party rights and share-alike obligations. The already acquired
   *Euthyphro* XML supplies contextual form, lemma and tag evidence. It
   covers that dialogue, not all Plato, and is not an inflection generator.
   Review each selected file's header and provenance before redistribution.
2. **[Greek morphology reader](https://github.com/nevenjovanovic/grcka-morfologija/tree/410206f4cde25d416ca9bf106b99355d8e3d48d1)**:
   its README and license state **CC BY 4.0**, which permits commercial
   sharing and adaptation with attribution, license notice, change indication
   and no additional restrictions. It contains small ALDT annotated Greek
   excerpts, including three Plato files. For example, the
   [Phaedo XML](https://github.com/nevenjovanovic/grcka-morfologija/blob/410206f4cde25d416ca9bf106b99355d8e3d48d1/grcpos/tlg0059.tlg004.ffzghr-pos%3A84-85.xml)
   itself declares CC BY 4.0 and includes form, lemma and POS tags. The
   [README](https://github.com/nevenjovanovic/grcka-morfologija/blob/410206f4cde25d416ca9bf106b99355d8e3d48d1/README.md)
   also credits Perseus and Open Greek and Latin for source texts, so check
   the exact underlying edition and attribution requirements; its scope is
   far smaller than GLEM.
3. **[MorphGNT SBLGNT](https://github.com/morphgnt/sblgnt/tree/aaed91e57c8e4a8dc9a2383e129ca5e75fe6393d)**:
   its [README](https://github.com/morphgnt/sblgnt/blob/aaed91e57c8e4a8dc9a2383e129ca5e75fe6393d/README.md)
   assigns **CC BY-SA 3.0** to parsing and lemmatization and separately points
   to the SBLGNT text license. The [linked text license](https://sblgnt.com/license/)
   currently presents **CC BY 4.0**. Both named licenses permit commercial
   reuse with their respective conditions; verify their applicability to the
   chosen release and comply with both for files containing both components.
   These are contextual Koine New Testament tokens, not Plato or a general
   classical Greek analyzer. MorphGNT's separate
   [morphological lexicon](https://github.com/morphgnt/morphological-lexicon/blob/0dca2af89f413cbb24f617ddbdc347e9d798ddf3/README.md)
   says code is MIT and content CC BY-SA 3.0, but its source-specific
   third-party fields also merit review.
4. **[Perseids Morpheus](https://github.com/perseids-tools/morpheus/tree/ab6898ffed335fc6169fa02c9940657a9b5a78e0)**:
   the repository has an [MPL-2.0 license](https://github.com/perseids-tools/morpheus/blob/ab6898ffed335fc6169fa02c9940657a9b5a78e0/LICENSE)
   for covered software, and [Mozilla's FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)
   confirms commercial use is permitted, with file-level source obligations
   for distributed modifications. It is an analyzer with included stem
   libraries, but this does **not** by itself establish the rights of every
   stem/data file or generated output. The project documents Linux/macOS or
   Docker, not a native Windows build. Confirm data provenance and license
   before treating it as a cleared replacement.

## Outstanding questions and recommended action

1. Ask the GLEM authors which precise PROIEL and Perseus releases and
   components generated each list, whether any source identifiers or
   provenance-separated lists exist, and which license applies to each file.
2. Ask the PROIEL rights holders whether they can grant written commercial
   use, modification and redistribution rights for their contributions and
   derivatives, including bundled and hosted commercial products. Ask Perseus
   to identify the original lexicon archive, its applicable license and any
   third-party restrictions. A GLEM maintainer's permission is insufficient
   by itself if they do not hold all upstream rights.
3. Obtain written authorization from **all relevant rightsholders**, including
   a clear grant for commercial redistribution and adaptations, or have
   counsel assess an alternative legal basis. Clarify obligations and whether
   terms apply to indexes and generated datasets. Until then, prefer evaluating
   the separately sourced alternatives above; do not derive a supposedly clean
   commercial list by filtering GLEM without a rights and provenance review.

## Draft inquiry (not sent)

Send first to the GLEM maintainers, for example through the
[GLEM issue tracker](https://github.com/GreekPerspective/glem/issues), and
forward the relevant questions to the PROIEL and Perseus maintainers.

> **Subject: Commercial reuse and provenance of GLEM word lists**
>
> Hello, we are evaluating offline Ancient Greek morphology for PlatoSI. At
> GLEM revision `590175899090aa5c3fe647149a85412351463da2`, we are interested
> in `list_proiel_perseus_merged_word_lemma_POS_nofreq`,
> `list_proiel_word_lemma_POS_freq`, and `extra-wlt.txt`.
>
> Your 2017 paper describes PROIEL and Perseus inputs and says GLEM was
> created under CC BY-NC-SA 3.0, while the repository's package metadata says
> GPL-3.0-only. Could you identify the exact upstream releases and licenses
> for each list, explain which license applies to each file today, and say
> whether row-level source information or separately licensed source lists
> are available?
>
> Can the relevant rightsholders grant permission for commercial use,
> modification, and redistribution of these lists and derived indexes,
> including in a bundled application or hosted service? If additional
> permission is needed from PROIEL, Perseus, or others, whom should we
> contact, and what attribution or other conditions would apply?
>
> Thank you.
