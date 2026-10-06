# Word Atlas Reader

A viewer for the results of a Word Atlas run, for a reader who has the
dataset and not the program. The Reader opens one file and needs
nothing else: no Bible build, no databases, no main program. Every
page the main program wrote is there, as text laid out by the same
code the main program uses, as a grid that sorts by any column, and
as rows that a search or a question can reach.

Version 0.2.0. Andrew Hopkins, with Claude.

## What you need

Python 3.9 or later and PyQt6:

    pip install PyQt6

On Ubuntu that may be `pip3 install PyQt6` or `sudo apt install
python3-pyqt6`. On Windows, install Python from python.org (tick "Add
to PATH") and run the same pip command in a terminal. A built copy of
the Reader (see Building below) needs neither.

## Running it

    python3 word_atlas_reader.py
    python3 word_atlas_reader.py word_atlas_0.10.72.wadb

The Reader remembers the last file opened and opens it again on the
next start. A sample dataset is in `sample/`.

## The file it opens

A Word Atlas dataset is a `.wadb` file: a zip archive holding
`results.db`, the SQLite database the main program writes with
`python3 atlas_query.py dossier all --results`, and a small manifest
(the program version, the runs inside, when it was packed). The main
program's `atlas_pack.py` makes one. The Reader also opens a bare
`results.db`.

The first time a `.wadb` is opened the Reader unpacks it into
`~/.word_atlas_reader/datasets/` and reads from there afterwards; a
changed archive is unpacked again. The Reader never writes to a
dataset: the database is opened read-only.

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
table. The arrow at the box's right lists earlier searches.

The **Results** menu asks the questions `atlas_results.py` asks of the
main program's database: the runs in the file, the Septuagint shares
of every New Testament book (1f), every part's function-word Delta
against its rest (7d), the echo seams (4e), the tables that declined
and why, and a diff of two runs cell by cell when the file holds more
than one run.

The **Ask Claude** tab sends a question about the dataset to Claude;
a "Past questions" box above it lists earlier ones.
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

## The files

| file | what it is |
|---|---|
| `word_atlas_reader.py` | the window |
| `reader_data.py` | opens a `.wadb` or `results.db`, rebuilds pages, searches |
| `reader_claude.py` | the Claude panel's API call, the SQL tool, the worker thread |
| `reader_help.py` | help mode and the column explanations (copied from the main program's atlas_help.py) |
| `atlas_report.py` | the page layout, shared with the main program |
| `atlas_results.py` | the results questions, shared with the main program |
| `test_reader.py` | the test script: `python3 test_reader.py` before every commit |
| `word_atlas_reader.spec` | the PyInstaller build file |
| `sample/` | a sample dataset (Ezra, Revelation, 1 Kings from Word Atlas 0.10.69) |

`atlas_report.py` and `atlas_results.py` are copies of the main
program's files and are standard library only; the column help in
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

## Testing

    python3 test_reader.py

Twelve tests: opening the sample, rendering a page, the cell text,
search, the results questions, the SQL tool's refusals, the question
loop against a stand-in API, the window offscreen, help mode and the
histories, and housekeeping.

## Versions

0.2.0: help mode (the ? button, F1) with notes for every control and
every column; drop-downs of earlier searches and questions, kept in
the settings; a jump lands the section title on the first line; a
wrap box for long lines; Claude's instructions name the tables by
number so it goes to 7d without searching for it.

0.1.0: the first version.
