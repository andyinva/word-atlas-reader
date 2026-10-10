# Word Atlas Reader

A viewer for the results of a Word Atlas run, for a reader who has the
dataset and not the program. The Reader opens one file and needs
nothing else: no Bible build, no databases, no main program. Every
page the main program wrote is there, as text laid out by the same
code the main program uses, as a grid that sorts by any column, and
as rows that a search or a question can reach.

Version 0.3.7. Andrew Hopkins, with Claude.

## What you need

Python 3.9 or later and PyQt6:

    pip install PyQt6

On Ubuntu that may be `pip3 install PyQt6` or `sudo apt install
python3-pyqt6`. On Windows, install Python from python.org (tick "Add
to PATH") and run the same pip command in a terminal. A built copy of
the Reader (see Building below) needs neither.

## Running it

    python3 word_atlas_reader.py
    python3 word_atlas_reader.py word_atlas_0.10.69_2026-10-05.wadb

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
3. In the Reader's folder run

       python3 reader_guest.py make sk-ant-... 15

   which writes `guest_key.dat` good for 15 days from today. The
   `.gitignore` keeps that file out of the repository.
4. Hand over the Reader's folder (or the PyInstaller build) with
   `guest_key.dat` and the `.wadb` inside.
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
| `reader_help.py` | help mode and the column explanations (copied from the main program's atlas_help.py) |
| `atlas_report.py` | the page layout, shared with the main program |
| `atlas_results.py` | the results questions, shared with the main program |
| `atlas_listed.py` | reads the listed-links footers back (shared with the main program) |
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

Thirteen tests: opening the sample, rendering a page, the cell text,
search, the results questions, the SQL tool's refusals, the question
loop against a stand-in API, the window offscreen, help mode and the
histories, the guest key, and housekeeping.

## If it ever freezes

Start the Reader from a terminal. If the window stops answering, open
a second terminal and run

    kill -USR1 $(pgrep -f word_atlas_reader.py)

which makes the Reader print where every thread is to the first
terminal without stopping it; send that text along with what you were
doing. (Linux only; on Windows, Task Manager's "Create dump file" is
the nearest equivalent.)

## Versions

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
