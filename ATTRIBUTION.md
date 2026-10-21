# Attribution and licenses

Because the packed dataset carries the Septuagint layer, whose license (CC BY-NC-SA 4.0) forbids commercial use, the packed dataset as a whole is distributed for non-commercial use only.

Word Atlas counts words. The words, the tags, the cross references and the links it counts come from other people's work, listed here with the license each is used under and the form of credit each asks for. The same list travels with every packed dataset (the `sources` table in results.db and in the .wadb the Word Atlas Reader opens), so that a reader of the numbers can see where they came from without this repository.

Where a dataset was adapted, the adaptation is Word Atlas's: a count, a reduced table or a derived pair is not the source's own statement and should not be cited as such.

## Texts

**The King James Version (1769 text).** Public domain. The English text every page quotes, with the Strong's numbers behind each word from the tagging in the public-domain editions Word Atlas builds from (atlas_source.py).

**Other English translations free of copyright** (the Revised and American Standard Versions, Young's, Darby, Webster, the Geneva Bible, Tyndale, Wycliffe, the Jewish Publication Society 1917 text, and the others listed in metadata.db's translations table). Public domain, taken from the scrollmapper bible_databases collection and Bible Search Lite's bibles.db. Six translations still under copyright are excluded from the translations index and never distributed. These texts are witnesses to the English echoes; none is quoted at length.

**The Hebrew Old Testament, TAHOT** (Translators Amalgamated Hebrew Old Testament), STEPBible. Creative Commons Attribution 4.0 (CC BY 4.0). The Hebrew text, its Strong's numbers, its glosses and its morphology. Word Atlas adds the half-verse division read from the Masoretic accents in the same files, and root families derived from the Strong's lexicon.

**The Greek New Testament, TAGNT** (Translators Amalgamated Greek New Testament), STEPBible. CC BY 4.0. The Greek text with its Strong's numbers, parsing and glosses, with the Textus Receptus and Nestle-Aland readings marked.

**The Septuagint.** Rahlfs' Septuaginta of 1935, the Old Greek (Theodotion's text for Daniel, as a book of its own), in Eliran Wong's digital edition (LXX-Rahlfs-1935) of the morphologically analysed text of the CCAT at the University of Pennsylvania. Creative Commons Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0), with the CCAT user declaration. Confirmed 2026-10-20 from the record lxx.db keeps of its own source (its settings table: "LXX Rahlfs 1935 (Eliran Wong, CC BY-NC-SA 4.0; CCAT data)"), from build_lxx.py, and from the greek-lxx row of the corpora table (which is in metadata.db, not lxx.db, and names the edition but not the license). Non-commercial: a dataset holding the Septuagint tables (1e, 1f, 4e, 4f) may be given away with this credit but never sold, and what is made from it is shared on the same terms. Word Atlas adds the verse mapping to the English numbering and the lemma repairs noted in atlas_septuagint.py.

**Strong's numbers and dictionary.** James Strong's Exhaustive Concordance (1890), public domain: the numbers that tie each English word to its Hebrew or Greek word. The dictionary entries (lemmas and short definitions) are from the strongs3 project, MIT licence.

**Versification maps, TVTMS** (Translators Versification Traditions with Methodology for Standardisation), STEPBible. CC BY 4.0. The maps between the Hebrew, Greek, Latin and English verse numberings that let the translations and the Septuagint be read against the King James.

## Cross references and links

**OpenBible.info cross references.** Creative Commons Attribution. The "listed" column, its votes, and the footers that count listed links are derived from this dataset, which is itself built on the Treasury of Scripture Knowledge. Counts of ranges and of votes are Word Atlas's adaptation.

**Sefaria's links dataset.** Creative Commons Attribution (CC-BY), by permission confirmed by Sefaria's developer team in October 2026. The "cited" column, the "cited, N roots" rows, the co-citation counts in the Passage and dossier pages, and the reduced table of pairs that Word Atlas distributes are adaptations of this dataset: counts of how many passages of the rabbinic library (the Mishnah, the Talmuds, the Midrash and the commentators, as Sefaria links them) cite two verses together. The library's texts themselves are licensed per version and per language edition and are not distributed by Word Atlas. Sefaria's name is used as the source of the links and not as an endorsement; see developers.sefaria.org/docs/usage-of-our-name-and-logo.

## Scholarship referred to in the reports

The published surveys and structures the reports test against are cited where they are used: Archer and Chirichigno, Old Testament Quotations in the New Testament (1983); E. Earle Ellis on Paul's citations; de Waard on Amos 5 (VT 27, 1977); Wenham on the flood narrative (VT 28, 1978) and Genesis 1 to 15 (1987); Fokkelman on Genesis 11 (1975); Vanhoye on Ezekiel in Revelation (1962). None of their text is reproduced.

## The sources table

The rows below are what Word Atlas copies into the `sources` table of results.db and of every packed dataset
(atlas_report.read_attribution reads this table, and nothing else in this file, so keep its five columns). The
Reader's About box shows them. "Adapted" says whether the atlas's figures are an adaptation of the dataset (counts,
reduced tables, derived pairs or maps, which the source itself never stated) and what was made, or why not.

| Name | Supplies | License | Credit | Adapted |
| --- | --- | --- | --- | --- |
| King James Version (1769) | The English text every page counts and quotes | Public domain (in the United Kingdom the Crown holds rights by letters patent) | King James Version, 1769 text, public domain. | no: quoted as printed; public domain, so there is nothing to mark |
| Strong's numbers and dictionary | The Hebrew or Greek word behind each English word; lemmas and short definitions | Numbers public domain (Strong, 1890); dictionary MIT licence | Strong's numbers (James Strong, 1890), public domain; dictionary from the strongs3 project, MIT licence. | no: numbers and lemmas used as given |
| Older English translations | Witnesses to the English echoes (the 'translations' and 'families' columns) | Public domain (published before 1930; the six under copyright excluded) | English translations out of copyright, from the scrollmapper bible_databases collection and Bible Search Lite. | no: only counts and names appear; public domain, so there is nothing to mark |
| TAHOT, Translators Amalgamated Hebrew OT | The Hebrew text, its Strong's numbers, glosses and morphology (1c, 7d, 7v, 7p) | CC BY 4.0 | TAHOT, Translators Amalgamated Hebrew OT (STEPBible / Tyndale House, CC BY 4.0). Credit STEP Bible, www.STEPBible.org. | yes: counts, the half-verse division read from the accents, root families |
| TAGNT, Translators Amalgamated Greek NT | The Greek text with Strong's numbers, parsing and glosses (4e, 4f) | CC BY 4.0 | TAGNT, Translators Amalgamated Greek NT (STEPBible / Tyndale House, CC BY 4.0). Credit STEP Bible, www.STEPBible.org. | yes: counts and the Greek runs of the echo tables |
| TVTMS versification maps | The maps between Hebrew, Greek, Latin and English verse numbers | CC BY 4.0 | Verse maps built from TVTMS by STEPBible.org, based on work at Tyndale House, Cambridge; CC BY 4.0. | yes: verse maps built from it for the Septuagint, the translations and Sefaria's links |
| Septuagint (Rahlfs 1935) | The Old Greek text of tables 1e, 1f, 4e and 4f | CC BY-NC-SA 4.0, with the CCAT user declaration; non-commercial | LXX Rahlfs 1935 (Eliran Wong, CC BY-NC-SA 4.0; CCAT data). | yes: counts, the verse mapping to the English numbering, lemma repairs; shared on the same terms |
| OpenBible.info cross references | The 'listed' column, its votes, and the footers that count listed links | CC BY | Cross references from OpenBible.info (built on the Treasury of Scripture Knowledge), CC BY. https://www.openbible.info/labs/cross-references/ | yes: counts of ranges and of votes |
| Sefaria links | The 'cited' column, the 'cited, N roots' rows, the co-citation counts, the reduced table of pairs | CC BY, by permission of Sefaria's developer team (October 2026) | Links from Sefaria (sefaria.org), CC BY. Sefaria's name marks the source of the links, not an endorsement. | yes: counts of passages citing two verses together, and the reduced table of pairs |

## How to credit Word Atlas

Word Atlas and the Word Atlas Reader are by Andrew Hopkins, with the review and design notes in reports/Analysis written with Claude. Counts, tables and figures from the program may be quoted with the program's name and version and the run date printed at the head of every page; the sources above must be credited with them when their data is what is being quoted.
