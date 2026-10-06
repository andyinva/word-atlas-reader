# Word Atlas

A tool for seeing how much influence each word of the Bible has over the
words around it, and how that influence changes as you zoom from the
whole Bible to one book, one chapter or one passage.

The picture to keep in mind is an atlas. A world map shows one set of
relations, a national map another, a state map a third. Words behave the
same way. "LORD" casts a large shadow over the whole Bible; "vine" casts
almost none at that scale, yet in John 15 it is the largest thing on the
page.

Word Atlas counts the Hebrew and Greek words behind the King James text
(through its Strong's tagging), stores the counts once in `atlas.db`,
and shows them as pages: a book, a chapter, a section of a book, a word,
a chapter's kin, a testament, or two books chapter against chapter.
Every number on every page can be traced to the verses that produced it
with one click.

## Running it

    cd ~/projects/word_atlas
    source venv/bin/activate      (Linux)
    venv\Scripts\activate         (Windows)
    python build_atlas.py         (once, about a minute; needs bibles.db and strongs.csv)
    python word_atlas.py          (the window; needs PyQt6)

The same pages print as text without the window:

    python atlas_query.py book Joel
    python atlas_query.py compare Exodus x Leviticus
    python atlas_query.py dossier Ezekiel --brief

Word Atlas reads the same `bibles.db` that Bible Search Lite uses; it
needs the `verse_strongs` table in it and the Strong's dictionary
`strongs.csv` from the strongs3 project. Neither file is in this
repository. The Greek layer (`lxx.db`) is built separately from the
Septuagint files (`build_lxx.py`), STEPBible's TAGNT Greek New
Testament (`build_gnt.py`, two files downloaded into `data/tagnt/`)
and STEPBible's TAHOT Hebrew Old Testament (`build_tahot.py`, four
files into `data/tahot/`), both from github.com/STEPBible/STEPBible-Data
under CC BY 4.0; the manual's section 28c says how. With both Greek
corpora in place the pages gain the Septuagint layer (`atlas_septuagint.py`,
section 28d): a New Testament book's Greek against the Septuagint, its
Septuagint words, and the echoes across the testaments in Greek.

## Sharing the results without the program

    python atlas_query.py dossier all --results
    python atlas_pack.py

writes every page of the canon into `reports/results.db` and packs it
into one `reports/word_atlas_<version>.wadb` file. The Word Atlas
Reader, a separate program at github.com/andyinva/word-atlas-reader,
opens that one file with no Bible build and no main program behind
it: every page as text, every table as a sortable grid, a search
across every cell, the results questions, and a panel for asking
Claude questions of the data with the reader's own API key. Hand a
reader the `.wadb` and the Reader, and they have the findings.

## Checking it

    python3 test_atlas.py

builds every kind of page on a few books, runs the same pages twice
under different hash seeds, and checks the guards and the version
lines; it prints one line per test and exits 1 on a failure, so it can
be a pre-commit hook. `--quick` leaves out the determinism test.

## Reading further

`WORD_ATLAS_MANUAL.md` is the one document: how to start, how to read
every table on every page, what the measures mean, the worked examples
(the Psalter, Isaiah, Jeremiah, Kings, Chronicles, Genesis, the
Synoptic Gospels), the rules and how to tune them, and the vocabulary,
notation and version history as appendices.

`HOW_WORD_ATLAS_GREW.md` is the story of how the program came to be
written, in the order it happened. `IMPROVEMENTS.md` is the one list of
what is proposed and waiting. The manual's Appendix E is a lab: twelve
commands a new reader can type, each with a small result and what it
means.

Help mode in the window (the ? button, or F1) explains any control,
column or cell while you point at it.

## Licence

The code and documents are released under the MIT licence (see
`LICENSE`). The King James text and its Strong's tagging are public
domain; the Strong's dictionary is from the strongs3 project (MIT).
