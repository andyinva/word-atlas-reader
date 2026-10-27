# Word Atlas Reader

A viewer for the results of a Word Atlas run, for a reader who has the
dataset and not the program. The Reader opens one file and needs
nothing else: no Bible build, no databases, no main program. Every
page the main program wrote is there, as text laid out by the same
code the main program uses, as a grid that sorts by any column, and
as rows that a search or a question can reach.

Version 0.3.26. Andrew Hopkins, with Claude.

## What you need

Python 3.9 or later and PyQt6:

    pip install PyQt6

On Ubuntu that may be `pip3 install PyQt6` or `sudo apt install
python3-pyqt6`. On Windows, install Python from python.org (tick "Add
to PATH") and run the same pip command in a terminal. A built copy of
the Reader (see Building below) needs neither.

## Running it

    python3 word_atlas_reader.py
    python3 word_atlas_reader.py word_atlas_0.10.117_2026-10-27.wadb

The Reader remembers the last file opened and opens it again on the
next start. With no last file it opens the newest of its own datasets
(next section); with none of its own, and Word Atlas in the folder
beside it, it fetches the newest dataset from Word Atlas's `reports/`
folder. The small sample in `sample/` is there for the tests: open it
with File > Open to have a look, but the Reader never opens it of its
own accord.

## The file it opens

A Word Atlas dataset is a `.wadb` file: a zip archive holding
`results.db`, the SQLite database the main program writes with
`python3 atlas_query.py dossier all --results`, and a small manifest
(the program version, the runs inside, when it was packed). The main
program's `atlas_pack.py` makes one. The Reader also opens a bare
`results.db`.

**The Reader keeps its own copy.** A `.wadb` opened with File > Open
(or named on the command line) is first copied into `datasets/`, a
folder beside the program, and the copy is what the Reader opens and
remembers. The file it was given can then be moved, renamed or
replaced, or the drive it was on unplugged, and the Reader still has
its data; and the dataset that is open is always one the Reader holds,
which is what a zip or a USB drive made from the Tools tab carries.
Opening the same file again copies nothing. A dataset that was the
last file opened before the Reader kept copies is brought in the same
way the next time the Reader starts. The `datasets/` folder is made
the first time the Reader starts, not by the tests. A bare `results.db` is
not copied: it is the main program's working file and is opened where
it stands. `datasets/` is kept out of git (each dataset is some 100
MB). Where the program's folder cannot be written to, the copies go
to `~/.word_atlas_reader/library/` instead.

On the computer the datasets are made on, with Word Atlas in the
folder beside the Reader's, the Tools tab has **Fetch the newest
dataset from Word Atlas**: one press copies the newest `.wadb` in
Word Atlas's `reports/` into the Reader's folder and opens it, and
the status bar says at start when a newer one is waiting there.
**Datasets kept by the Reader**, on the same tab, lists the copies
and removes the ones that are not open.

The first time a `.wadb` is opened the Reader also unpacks it into
`~/.word_atlas_reader/datasets/` and reads from there afterwards; a
changed archive is unpacked again. The Reader never writes to a
dataset: the database is opened read-only.

**What a dataset of Word Atlas 0.10.101 or later holds besides the
pages.** The heat strips of every book (`heat_strips`, `heat_windows`,
`heat_spots`, written by the main program's `run_heat.py --all`), the
named passages of its catalogue (`passages`, `passage_ranges`), the
King James text with its Strong's tags (`kjv_books`, `kjv_verses`,
`kjv_tags`), and `schema_notes`, which says in plain words what every
table and column holds. The Heat tab reads them, and nothing else of
the atlas need be on the stick. An older dataset opens as it always
did; its Heat tab says it has no strips and which file to open
instead.

**Themes (Word Atlas 0.10.109).** A dataset packed by 0.10.109 or later
also carries the themes the main program had loaded: hand-made sets of
verses such as land and inheritance (`theme`, `theme_verse`,
`theme_strip`, `theme_term`, `theme_problem`). Every figure is stored
ready to use: each verse with its role (core, borderline, excluded),
reason and King James text, and for every chapter of the canon its
counts, expected counts, lift per chapter and the colour to draw it in.
The Themes tab reads them and works nothing out.

## What the window shows

The **?** button at the top right (or F1) is help mode: the pointer
becomes a question mark, and resting it on any part of the window
shows a note saying what that part is. Point at a column heading in a
grid and the note explains the column, with the same explanations the
main program gives. A click, Escape or ? again leaves help mode.

The run box at the top names each run the file holds (a run is one
pass of the main program: its version, build line and start time). The
tree on the left lists the run's pages by kind: Book, Chapter, Section,
Passage, Word, Kin, Testament, Compare. The filter box above the tree
narrows the list by title.

The **Page** tab shows the chosen page as text, exactly as the main
program's `reports/*.txt` file shows it, with a box to jump to any
section (its title lands on the first line) and a "Wrap long lines"
box for the prose lines that run past the window. File > Save page as
text writes it out.

The **Table** tab shows one table of the page as a grid. Click a column
header to sort by it (numbers sort as numbers). Hover over a row for
the verses behind it; click a row to see them in the status bar. The
table's note is above the grid and its footer lines below.

The **Search** box at the top looks through every cell, section title
and footer of the run. Double-click a hit to open its page at that
table. The arrow at the box's right lists earlier searches, and the
Search button turns green while the box holds something not yet
searched; the Ask Claude button does the same for a question.

The **Results** menu asks the questions `atlas_results.py` asks of the
main program's database: the runs in the file, the Septuagint shares
of every New Testament book (1f), every part's function-word Delta
against its rest (7d), the echo seams (4e), the tables that declined
and why, the echo tables against the cross references (the `listed` footers
of 4, 4e and 6, from Word Atlas 0.10.75 on), the English echoes by how many
other translations keep them (`idiom`, from 0.10.80), the echo tables against the
pairs the rabbinic library cites together (`cited`, from 0.10.81), and a diff of two runs
cell by cell when the file holds more than one run.

The **Ask Claude** tab sends a question about the dataset to Claude;
a "Past questions" box above it lists earlier ones, then a set of
starter questions to try. The first starter, "What can I ask about
this dataset?", has Claude describe what the file holds and suggest
questions; another asks what the sections on a book page are. Claude
can explain the dataset as well as answer from it. "Questions..."
opens a list of some two hundred questions grouped by subject (the
signature words, function words, the Septuagint, echoes, the parts of
a book, the whole file, method and caution) to filter and pick from;
"this book" in a question means the page open in the Reader, which
goes to Claude with every question. "Save answer as
text" writes the question, the answer and the queries Claude ran to
a text file, headed with the dataset, the run, the time and the model.
Claude is given one tool, a read-only SQL query against the open
database, and answers in prose, naming the page and table each figure
came from. This needs an API key from console.anthropic.com entered
under File > Claude settings; the key is kept in
`~/.word_atlas_reader/settings.json` and is sent only to
api.anthropic.com. The Fetch models button in that dialog lists the
models your key may use. Each question costs a few cents on your own
account, since only the rows Claude asks for travel, never the whole
file. Without a key, "Copy as a prompt for claude.ai" puts the
question, the schema and the open page on the clipboard, to paste into
claude.ai or any assistant by hand.

The **Themes** tab draws a theme's strip: one cell per chapter of the
canon in canonical order, a line per book, in the colour the main
program stored for it (light grey ordinary, red where the chapter holds
more of the theme than its length would give it, blue less, grey
outside the theme's home range), with a short tick where a section of a
book begins. The box beside the theme switches between core verses and
core plus borderline. Point at a cell for its stored figures (the
counts, what was expected, the lift); click it to list that chapter's
verses of the theme below, with their roles, reasons and text. A
dataset packed before Word Atlas 0.10.109 has no themes, and the tab
says so.

The **Constellations** tab shows the sets of two to five words that
gather in one stretch of text far more often than chance, as the main
program's atlas_sets.py found them (a dataset packed by Word Atlas
0.10.112 or later). The top row chooses the book, or the Old or New
Testament (choosing a book's page on the left brings it up here too);
the norm (against the book itself, or against its testament, where the
words that run through a whole book stand out); the kind
(constellations, frames, phrases); the size; and "Closed sets only",
ticked at first, which hides the smaller sets that say nothing their
larger set does not. The Root box keeps only the sets that hold one word:
type covenant or H1285 for every set the word belongs to, strongest
first. The grid lists words, size, kind, support (the ten-verse windows
the set occurs in), places (the separate places), expected, lift,
keyness (the sort order), span (chapters from the first place to the
last), in order (the share of windows where the roots keep one order),
inclusio (at both ends of the book) and folds; click a heading to sort,
point at a row for its Strong's numbers. Choosing a set draws its strip
along the book, red where it gathers, lists its places (click one for its
King James text, with Strong's numbers when asked) and the smaller sets
folded under it. Save as text keeps the grid with its filter at the head;
Copy set copies the chosen set's line. Every figure is stored; the tab
counts nothing.

The **Heat** tab draws a book's heat strips from the rows the main
program stored: one row per strip along the book, a cell per window of
ten verses moving a verse at a time, red where the strip runs hot,
blue where it runs cool and grey where it is ordinary, in the colours
of the main program's charts. Choose the book (choosing a book's page
on the left brings it up too), how it was measured (z against every
book of its language, the usual reading; percentile against the book
itself; G2 against the language or against the book's own kind) and
which kinds of strip to show (the five measures, feeling and its
families, the word lists such as ransom and rest, the names and
numbers, the contexts and the voices). Point at a cell for its verses
and score, and at a strip's name for what it measures and, for a word
list, its words. Click a strip to list its hot and cool spots below,
with the words that lit them as the main program's heat report prints
them, at the report's line or at the near line (three quarters of
it); click a spot to outline it on the strip. Clicking a cell or a
spot shows its King James verses on the right, where a named passage
can be chosen or a reference typed (Genesis 23:7-16, Ruth 3, John
1:1), with the Strong's numbers of the words when asked. Nothing on
the tab is counted afresh: every figure is the one the main program
wrote.

**The Hebrew and Greek.** View > Show Hebrew and Greek (on at first)
prints the Hebrew or Greek word and its transliteration after every
Strong's number, on every tab: hosts H6635 צָבָא tsava, grace G5485 χάρις
charis. The transliteration says how the word sounds (kh as in Bach, ts
as in cats; the divine name printed YHWH). Untick it for narrow tables.
Typing a transliteration in the search box (khesed) finds the cells that
hold its number. A dataset packed before Word Atlas 0.10.115 has no
table of words, and its pages show the numbers alone.

The transliteration is the word as it stands in the text, its prefixes
removed: a word that always follows a vowel may begin with v, kh or f
where a dictionary gives b, k or p (vohu for H922; a dictionary gives
bohu), and the Hebrew letters beside it follow the spelling (בֹהוּ,
without the dagesh). This is for nouns, adjectives and names, and
differs from the dictionary form only by the dagesh or a plural; a verb
keeps its dictionary form. The dictionary form is one hover away: point
at a cell and its tooltip reads, for instance, "H922 בֹהוּ vohu
(dictionary בֹּהוּ bohu)". The search matches both forms, so typing bohu
or vohu finds H922. A dataset packed
by Word Atlas 0.10.116 or earlier prints the dictionary form.

A dataset packed by Word Atlas 0.10.114 or later also holds two strips
of kind translations, shown under "every strip". **disagreement** is how
far the English translations stand apart on the window's verses: the
share of content words two translations do not share, matched through
an alignment with the King James so a spelling is not a difference,
proper names set aside, and each pair's usual distance taken off. Red
marks where the Hebrew or Greek is obscure, or where the manuscripts
differ. **missing** is the share of the translations lacking the verse;
a verse a translation holds inside its neighbour is merged (a
difference of verse division) and not counted.

The **Tools** tab, the last one, holds what is wanted now and then,
kept behind a tab so the window opens as plain as it always has. It
has three groups, and everything in them is about the Reader and the
dataset it has open (the tools that build the atlas are the main
program's and are on its Workbench tab, not here):

- *This dataset.* **Dataset details** says what the open file holds:
  where it is and how it was packed, each run with its version, date
  and pages, the rows in each table, and whether the file reads back
  sound. Below it is a box for a reading query of your own in SQL
  (only a single SELECT runs, the answer is laid out in columns and
  cut at a few hundred rows, and the dataset is never written to);
  **The tables and their columns** prints what there is to query.
  **Fetch the newest dataset from Word Atlas** and **Datasets kept by
  the Reader** look after the Reader's own copies (see "The file it
  opens").
- *This copy of the Reader.* **Check this copy** lists its version,
  the Python and Qt under it, its program files, its guest key, where
  its settings are and which datasets it has unpacked. **Run the
  Reader's tests** runs `test_reader.py` and prints its lines.
  **Guest key** says whether this copy carries one and writes a new
  one (see below).
- *Passing it on.* **Zip the Reader with this dataset** writes one zip
  of the program files and the open `.wadb` for someone who has
  Python. **Build or update a USB drive** makes a drive that installs
  the Reader on a Windows or Linux computer (next section).

What a tool reports is printed on the right of the tab; Save as text
keeps it.

## A USB drive that installs the Reader

Tools tab, **Build or update a USB drive**. Pick the drive (Look again
after plugging one in; Other folder for one not listed), tick what
goes on it, and press the button. The drive gets one folder,
`WordAtlas`, holding the Reader's program files, the dataset that is
open (the Reader's own copy of it; the line in the window names it
with its size, and Choose picks another), PyQt6 for Windows and Linux (fetched
from PyPI once, about 180 MB, and kept on this computer for the next
drive) and an installer. Nothing else on the drive is touched. When
the main program, Word Atlas, is in the folder beside the Reader's it
is offered too, with the built databases you tick; where it is not,
that part of the window says so and the drive carries the Reader
alone.

On the other computer, open the drive's `WordAtlas` folder and
double-click `Install-Windows.bat` (Windows) or run `bash
install-linux.sh` in a terminal (Linux). The installer says what the
drive holds, asks which program to install and where, copies it with
its dataset, sees to PyQt6 without the internet, and leaves an entry
in the applications menu (on Windows, the Start menu and the Desktop).
The computer needs Python 3.10 or later and nothing else; on a Windows
computer without Python the launcher says how to get it. The Reader
then opens on the installed dataset, which the installer puts in the
installed Reader's own `datasets/` folder.

Press the same button another day and the drive is brought up to
date: only the files that changed are copied, and the dataset it
carried before is replaced by the new one unless you tick "Keep the
older datasets". Running the installer again from the newer drive
updates the install the same way; a file changed on that computer
since is left alone and named. **Check the drive** reads every file
back against the checksum written with it. The same drive can be
made or updated from Word Atlas (its Workbench tab, Install menu),
and `python3 atlas_usb.py build DRIVE` does it from a terminal.

**Bible Search Lite.** The window's third box puts Bible Search Lite
on the drive with its bibles.db (about 440 MB), found in
`bible-search-lite` beside this folder or wherever Find... points. The
installer then offers it too. Its subjects and settings stay on the
computer the drive was made on. bibles.db holds translations still
under copyright, so keep such a drive for your own computers.

The installer was tried on Windows 11 on 2026-10-20 with the built
Reader: it installed and ran without trouble.

**The install report.** At the end of an install the installer checks
its own work and writes `install_report.txt` in the install folder:
the computer and Python, every program file present and matching what
was copied (`installed_files.json` keeps each file's size and
checksum), each dataset opening whole with the tables the Reader
reads, PyQt6 loading (and a window opening, on Linux), the starters
and the menu or Desktop entries. Each problem is followed by a "What
to do" line; the last line says NO PROBLEMS FOUND or how many there
were. It is the file to ask for when someone has trouble with an
install. To check again later, without the drive: the Tools tab's
**Check the install**, or `python3 usb_install.py --check` in the
installed Reader's folder.

## Updates from GitHub

An installed Reader brings itself up to date over the internet. The
Tools tab's "Updates from GitHub" group has:

- **Check for a newer Reader.** Reads the version of
  `word_atlas_reader.py` on the main branch of
  andyinva/word-atlas-reader. When it is newer, you choose: replace
  this copy's program files (the old ones go to a dated folder under
  the Reader's `backups` folder, so the update can be undone; the
  datasets, settings and guest key are never touched), or put the
  newer Reader into another folder. Start the Reader again afterwards.
  A built copy (no Python) cannot replace its own program; it can
  download the newer source into a folder, and is otherwise brought
  up to date by a new build or an updated drive.
- **Check for a newer dataset.** Looks at the repository's releases
  for the newest `.wadb`, downloads it into the Reader's `datasets`
  folder and opens it. Tick the box to remove the older datasets the
  Reader keeps. While it downloads, the other Tools buttons wait and a
  Stop button ends the download.

**A quiet notice at start.** When the Reader opens it asks the releases,
on its own thread so the window opens at once, for the newest dataset
and, when it does not hold that file, says on the status bar "A newer
dataset is on GitHub: Tools > Check for a newer dataset". Nothing is
downloaded without that press. It waits only a few seconds, and a failed
or slow answer is silent: no dialog, no message. Turn the question off
with `"check_dataset_at_start": false` in `settings.json` (a metered
connection, or none); the default is true.

**Publishing.** Push the Reader's code as usual; a new `VERSION` in
`word_atlas_reader.py` is what tells installed copies an update is
there. A dataset is too big for git, so it goes on a release: on
GitHub open the repository, Releases, "Draft a new release", give it
a tag of the form `dataset-<Word Atlas version>` (so the tag says which
program made the pack), attach the `.wadb`, and Publish. With the `gh`
tool:

    gh release create dataset-0.10.117 datasets/word_atlas_0.10.117_2026-10-27.wadb --repo andyinva/word-atlas-reader --title "Dataset 0.10.117" --notes "Word Atlas 0.10.117, canon run 7"

**Datasets published.** One line per release, so a reader can see what
a newer dataset would gain. The Reader finds the newest by upload date,
whatever the tag or the file is called.

- `dataset-2026-10-20` (Word Atlas 0.10.103): `word_atlas_0.10.103_2026-10-20.wadb`,
  128.1 MB; the heat strips of every book, the named passages and the
  King James text with its Strong's tags (the Heat tab).
- `dataset-0.10.117`: `word_atlas_0.10.117_2026-10-27.wadb`, 149.4 MB,
  canon run 7; Hebrew and Greek spellings beside every Strong's number,
  attested forms, constellations, the translations compared
  (disagreement and missing strips).

A copy can follow another repository: `"update_repo": "owner/name"`
in its `settings.json`.

## Credits and licences

**Help > Credits and licences** shows whose work the dataset rests on
and on what terms each may be passed on: the King James text and
Strong's numbers (public domain), the Strong's dictionary (MIT), the
cross references from OpenBible.info (CC BY), Rahlfs' Septuagint
(CC BY-NC-SA: with its credit, never for sale), STEPBible's Greek New
Testament, Hebrew Bible and verse maps (CC BY), the counts derived
from Sefaria's links (CC BY, by Sefaria's permission; the counts made
from the cross references and the links are Word Atlas's adaptation,
under CC BY), the older English translations (counts only),
and the programs themselves (MIT, on Python, Qt and PyQt6). With a
dataset open the page begins by saying which of those sources that
dataset draws on, found from its own tables, so a dataset packed
without the Greek layer does not credit the Septuagint. Save as text
and Copy are on the page.

**The sources table (0.3.14).** A dataset packed by Word Atlas 0.10.103
or later carries a `sources` table, copied from ATTRIBUTION.md (in this
folder and in Word Atlas's): one row per outside dataset with what it
supplies, its license, the credit line it asks for, and whether the
figures are an adaptation of it. **Help > About** shows it as a table,
with Copy and a button to the credits page; the credits page adds the
same rows under "As this dataset records them". An older dataset has no
such table, and the About box says so.

The same page prints from a terminal with `python3 reader_credits.py`
(add a dataset's name for that dataset's credits), and a zip made on
the Tools tab carries it as `CREDITS.txt`. Keep it with any copy you
give away: naming the sources is the one thing most of them ask.

## Giving copies away with a guest key

A copy of the Reader can carry a guest API key, so the person you
give it to can ask Claude questions for a while without a key of
their own. The key lives in `guest_key.dat` beside the program,
scrambled and tied to an end date; the Reader uses it until that
date, never shows it on screen, and a key the user enters under File
> Claude settings is used instead of it.

Do it in this order, because the real protection is on Anthropic's
side, not in the file:

1. In console.anthropic.com make a separate workspace for guests
   (Settings > Workspaces) and give it a monthly spending limit. A
   question costs cents, so a few dollars covers a fortnight of
   curiosity; the limit is what stops a copy that gets passed on from
   costing you more.
2. Make an API key in that workspace, not in your own.
3. On the Tools tab press **Guest key**, then "Write a new one", and
   enter the key and the days; or in the Reader's folder run

       python3 reader_guest.py make sk-ant-... 15

   Either writes `guest_key.dat` good for 15 days from today. The
   `.gitignore` keeps that file out of the repository.
4. Hand over the Reader's folder (or the PyInstaller build) with
   `guest_key.dat` and the `.wadb` inside; the zip and the USB drive
   on the Tools tab take the guest key along only when its box is
   ticked.
5. On the end date, delete the key in the console. The date in the
   file is a courtesy the Reader keeps; the deletion is the one nobody
   can get around.

`python3 reader_guest.py show` says whether a guest key is present
and when it ends. Be clear with yourself about what the scrambling
does: it keeps the key out of plain sight, off the screen and out of
the settings file, so a casual reader cannot copy it out. It does not
make it unrecoverable, because the program has to unscramble it to
send it; someone with the file, the source and the will can get it
out, as they can from any program that carries a key. That is why the
spending limit and the deletion matter, and why the guest key should
be thought of as a small prepaid card, never as a secret.

## The files

| file | what it is |
|---|---|
| `word_atlas_reader.py` | the window |
| `reader_data.py` | opens a `.wadb` or `results.db`, rebuilds pages, searches |
| `reader_claude.py` | the Claude panel's API call, the SQL tool, the worker thread |
| `reader_guest.py` | the guest key: `make` writes `guest_key.dat`, `show` reports it |
| `guest_key.dat` | a scrambled guest key with its end date, when a copy carries one; never committed |
| `reader_questions.py` | the Questions list, grouped by subject |
| `reader_tools.py` | the Tools tab: dataset details, a query of your own, this copy's tests and guest key, the zip |
| `reader_credits.py` | the credits and licences page: the sources, and which of them a dataset draws on |
| `reader_constellations.py` | the Constellations tab: the sets of words that travel together, from the stored rows |
| `reader_themes.py` | the Themes tab: a theme's strip and verses, drawn from the stored rows |
| `reader_heat.py` | the Heat tab: the strip chart, the spots, the King James text and the named passages |
| `reader_update.py` | updates from GitHub: a newer Reader from the main branch, a newer dataset from the releases |
| `atlas_usb.py` | the USB drive: finds drives, makes or updates the `WordAtlas` folder on one, fetches PyQt6 for it (the same file as the main program's) |
| `atlas_usb_dialog.py` | the USB drive's window (the same file as the main program's) |
| `usb_install.py` | the installer, copied to a drive as `install.py` (the same file as the main program's) |
| `reader_help.py` | help mode and the column explanations (copied from the main program's atlas_help.py) |
| `atlas_report.py` | the page layout, shared with the main program |
| `atlas_results.py` | the results questions, shared with the main program |
| `atlas_listed.py` | reads the listed-links footers back (shared with the main program) |
| `test_reader.py` | the test script: `python3 test_reader.py` before every commit |
| `word_atlas_reader.spec` | the PyInstaller build file |
| `sample/` | a sample dataset (Ezra, Revelation, 1 Kings from Word Atlas 0.10.69), for the tests |
| `datasets/` | the Reader's own copies of the datasets it has opened; never committed |

`atlas_report.py` and `atlas_results.py` are copies of the main
program's files and are standard library only, and the three USB
files are likewise copies of the main program's; the column help in
`reader_help.py` is copied from its `atlas_help.py`. When the main program
changes them, copy them over again; the Reader's tests will say if the
copy no longer fits.

## Building a copy that needs no Python

    pip install pyinstaller
    pyinstaller word_atlas_reader.spec

The result is `dist/WordAtlasReader/`, a folder holding the program
and the Python and Qt it needs, about 60 MB; zip the folder to hand it
on, and the reader double-clicks `WordAtlasReader` (or
`WordAtlasReader.exe`) inside it. Build on the platform the copy is
for: the Windows build on Windows, the Ubuntu build on Ubuntu. Windows
may warn that the program is from an unknown publisher the first time
it runs, since it is not signed; "More info" then "Run anyway" gets
past that.

A built copy travels on the USB drive too: when `dist/WordAtlasReader`
stands in the Reader's folder, "Build or update a USB drive" puts it
on the drive under `builds/` for the system it was built on, and on a
Windows computer with no Python the drive's `Install-Windows.bat`
offers to install that copy.

## Testing

    python3 test_reader.py

Seventeen tests: opening the sample, rendering a page, the cell text,
search, the results questions, the SQL tool's refusals, the question
loop against a stand-in API, the window offscreen, help mode and the
histories, the guest key, the Reader's own datasets folder, the
credits page, the Tools tab, a USB drive made, updated and installed
from, and housekeeping.

The tests read the sample and keep to a throwaway home folder of
their own (`WORD_ATLAS_READER_HOME`), so running them changes nothing
of the Reader's: its settings, its datasets and the file it opens
next are as they were.

## If it ever freezes

Start the Reader from a terminal. If the window stops answering, open
a second terminal and run

    kill -USR1 $(pgrep -f word_atlas_reader.py)

which makes the Reader print where every thread is to the first
terminal without stopping it; send that text along with what you were
doing. (Linux only; on Windows, Task Manager's "Create dump file" is
the nearest equivalent.)

## Versions

0.3.26: a quiet notice at start when GitHub holds a newer dataset than
the Reader keeps ("A newer dataset is on GitHub: Tools > Check for a
newer dataset"), asked off the main thread with a few seconds' patience,
silent when it fails; the setting `check_dataset_at_start` (default
true) in settings.json turns it off. README: the examples name the
0.10.117 pack and the tag form `dataset-<Word Atlas version>`, and a
list of the datasets published. reader_update.py gains
newer_dataset_waiting and a timeout on latest_dataset.

0.3.25: the Hebrew and the transliteration beside a Strong's number are
the form the text has (בֹהוּ vohu for H922, where a dictionary gives
בֹּהוּ bohu), for nouns, adjectives and names, from the translit_text and
script_text columns of a dataset packed by Word Atlas 0.10.117 or later;
a cell's tooltip names the dictionary form ("H922 בֹהוּ vohu (dictionary
בֹּהוּ bohu)"), and the search finds a number by either form. A page
written before it printed the dictionary form and is put right when the
box is ticked or unticked. atlas_report.py and atlas_pack.py from Word
Atlas 0.10.117.

0.3.24: View > Show Hebrew and Greek (on by default): the Hebrew or
Greek word and its transliteration after every Strong's number (hosts
H6635 צָבָא tsava) in every page cell, title, note and footer, the heat
spots, the theme terms and the constellations grid, from the
lexicon_forms table of a dataset packed by Word Atlas 0.10.115 or later;
untick it for narrow tables. The search, and the constellations' word
box, find a number by its transliteration (khesed finds H2617). The
strip notes say the divine names stay in the distance and verses lost in
import are not lacking. atlas_report.py and atlas_pack.py from Word
Atlas 0.10.115.

0.3.23: the help notes of the two translations strips (disagreement and
missing: what the distance is, names set aside, lacking and merged told
apart), and the Claude panel told of the renderings tables and
disagreement_verses, with two starter questions. atlas_report.py from
Word Atlas 0.10.114.

0.3.22: the Constellations tab (reader_constellations.py), from the
word_sets tables of a dataset packed by Word Atlas 0.10.112 or later; the
Claude panel told of those tables, with three starter questions; the
sample remade with the constellations of the New Testament, Ezra, 1 Kings
and Revelation and the King James text they need. atlas_report.py and
atlas_pack.py from Word Atlas 0.10.112.

0.3.21: every drop-down is sized by a few characters, not by its longest
entry. A long past question to Claude had made the Ask Claude tab, and
so the whole right side, wider than the window: the page list on the
left shrank to a sliver and its divider could not be moved.

0.3.20: the Themes tab (reader_themes.py): a theme's strip of the canon
and its verses, from the theme tables of a dataset packed by Word Atlas
0.10.109 or later; nothing is computed, every colour and figure is the
one stored. atlas_pack.py and atlas_report.py from Word Atlas 0.10.109.

0.3.19: the USB window's "Pack a fresh dataset first" packs with Word
Atlas's atlas_pack.py (the newest run, the passages, the King James
text, the sources), and is offered only when results.db holds a newer
run (atlas_usb.py and atlas_usb_dialog.py from Word Atlas 0.10.108).

0.3.18: the USB drive window can put Bible Search Lite and its bibles.db
on the drive (atlas_usb.py, atlas_usb_dialog.py and usb_install.py from
Word Atlas 0.10.107), and the drive's installer installs it beside the
Reader and Word Atlas on Ubuntu or Windows 11.

0.3.17: the window fits a smaller screen: the Run and Search boxes
take the room the top row gives them instead of the width of their
longest entry (the drop-down still shows each in full), and the long
sentences on the Ask Claude and Results tabs wrap. The window's least
width came down from about 1,050 pixels to about 770.

0.3.16: on the Page tab the notes under the title, each section's note
and the footers fold to the pane's width (they had run off the right
edge), and fold again when the window is resized; table rows are never
folded and keep their columns. Save as text and Ask Claude still get
the page exactly as rendered. "Wrap long lines" now folds everything,
table rows too.

0.3.15: while a dataset downloads or the tests run, the other Tools
buttons wait (their lines had landed among the download's), with a
Stop button for the job and a line saying what is running.

0.3.14: the About box shows the open dataset's sources table (Word Atlas
0.10.103 and later), and the credits page lists it; Dataset details
counts it and the Claude panel is told of it. ATTRIBUTION.md copied
in; atlas_report.py, atlas_pack.py, atlas_listed.py and atlas_usb.py
copied over from Word Atlas 0.10.103.

0.3.13: updates from GitHub (reader_update.py; Tools tab, "Updates
from GitHub"): a newer Reader replaces this copy's program files with
a backup of the old ones, or goes into another folder; a newer dataset
comes from the repository's releases. The installer writes an install
report and keeps a checksum of every file it copied; Check the install
on the Tools tab and `usb_install.py --check` check again without the
drive. A built copy making a USB drive finds its source folder, and
its own datasets folder stays off the drive.

0.3.12: the Heat tab (reader_heat.py): a book's heat strips drawn
from the heat rows of a dataset made by Word Atlas 0.10.101 or later,
the chosen strip's spots with the words that lit them, and the King
James text of a window, a spot, a named passage or a reference typed
in, with its Strong's numbers when asked. An older dataset opens as
before and the tab says why it is bare. The Claude panel is told about
the new tables and schema_notes. `atlas_report.py` and `atlas_pack.py`
copied over from Word Atlas 0.10.101. Three tests.

0.3.11: a credits and licences page (Help menu; reader_credits.py),
which names the sources a dataset rests on and says which of them the
open dataset draws on, and goes into a give-away zip as CREDITS.txt.
A last file that is not one of the Reader's own copies (one opened
before 0.3.10) is copied into `datasets/` when the Reader starts,
where 0.3.10 went on opening it from where it was.

0.3.10: the Reader keeps its own copy of every dataset it is given,
in `datasets/` beside the program, and opens that copy; at start it
opens the last file, else the newest of its own, else the newest in
Word Atlas's reports folder, and never the sample. Tools tab: Fetch
the newest dataset from Word Atlas, and Datasets kept by the Reader.
The tests use a home folder of their own and no longer leave the
Reader pointing at the sample; the drive's installer puts the dataset
in the installed Reader's `datasets/`; a zip made to give away
carries its dataset there too. The drive test no longer reaches for
the internet or flushes every disk (it took a minute on one machine).

0.3.9: a Tools tab (reader_tools.py) with the parts of the main
program's Workbench that are the Reader's own: the dataset's details,
a reading SQL query, this copy's tests and guest key, a zip of the
Reader with the open dataset; and a USB drive that installs the
Reader, with its data and PyQt6, on Windows or Linux, made and
brought up to date from the same tab (atlas_usb.py, shared with Word
Atlas 0.10.88). The window otherwise opens exactly as before.

0.3.8: atlas_results.py of Word Atlas 0.10.87 (the idiom question sets the Greek-held rows apart).

0.3.7: atlas_results.py of Word Atlas 0.10.86 (the idiom question reads a named pair).

0.3.6: the tests open the newest dataset in sample/, so a copy made by
Word Atlas's atlas_dist.py tests itself as it stands.

0.3.5: the grade help names the 'cited, N roots' rows (Word Atlas 0.10.82).

0.3.4: the `cited` question on the Results menu and the help for the
`cited` column (Word Atlas 0.10.81, the rabbinic library's pairs from
Sefaria).

0.3.3: the `idiom` question on the Results menu and the help for the
`translations` and `families` columns (Word Atlas 0.10.80).

0.3.2: the `unlisted` sample on the Results menu (atlas_results.py of
0.10.77).

0.3.1: the `listed` results question and column help, with the
main program's atlas_results.py and atlas_listed.py of 0.10.75.

0.3.0: a guest key for copies given away (reader_guest.py), used
until its end date, never shown, replaced by the user's own key;
Save answer as text on the Ask Claude tab; the Search and Ask
buttons turn green while their box holds something not yet sent;
the Questions list (reader_questions.py, 204 questions in 18 groups);
the open page is sent with every question.

0.2.2: starter questions in the Past questions box; Claude's
instructions say to explain the dataset and its sections when asked.

0.2.1: a stack dump on SIGUSR1, for a freeze report.

0.2.0: help mode (the ? button, F1) with notes for every control and
every column; drop-downs of earlier searches and questions, kept in
the settings; a jump lands the section title on the first line; a
wrap box for long lines; Claude's instructions name the tables by
number so it goes to 7d without searching for it.

0.1.0: the first version.
