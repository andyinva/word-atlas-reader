#!/usr/bin/env python3
"""
atlas_report.py

The reporting module of Word Atlas: one place that knows what a report
is and how it is laid out, used by the text renderer (atlas_query.py),
the window (word_atlas.py), the dossier, the test script and the
results writer, so that every report has the same head, the same
section numbering, the same footers, one set of trimming options and
one form in the results database.

A REPORT is a page: a file-safe name, a title, a few note lines under
the title, and a list of SECTIONS.  A section is one table: a title
whose first word is its number (1, 1a, 4a2, 7.2d, 7x), a note saying
what the table is and how to read it, columns, rows, the verse
references behind each row (for the click in the window, and for the
results database), a link a click can follow, and footer lines.  A
section that declined to measure keeps its title and says why in its
note, and prints no table.  That is the whole contract; the standard
the manual states (section 11a) is a reading of this file.

The text layout (render) prints a report as plain text, the trimming
options (--top, --only, --quiet) cut it down the same way for every
page, and the results writer (ResultsWriter) stores the same report
as rows of a SQLite file so that a question across the whole canon is
a query rather than a search through sixty-six text files.

Author: Andrew Hopkins (with Claude)
"""

import os
import re
import sqlite3
import time

# The separator between the pages of a dossier, and its line count
PAGE_SEPARATOR = "\n\n" + "=" * 110 + "\n\n"
TABLE_RULE_MAX = 110            # the dash line under a table's header is no wider than this
NUMBER = re.compile(r"-?\d{1,3}(,\d{3})*(\.\d+)?|-?\d+(\.\d+)?")   # a cell that is a number written as text
# A cell that looks like a figure even though it is text: "501 / 3261",
# "15/66", "12:3", "3.2x", "41%", "-".  Such cells line up on the right
# like numbers, so a column of them reads as a column of figures.
FIGURE = re.compile(r"[\d.,:%x/\s-]*")


def is_numeric_cell(value):
    """
    True when a table cell should be right-aligned: a number, an empty
    cell, or text made only of digits and figure punctuation.  A column
    is right-aligned when every one of its cells passes this test, so
    one word in a column turns the whole column left-aligned.
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and FIGURE.fullmatch(value) is not None


# ---------------------------------------------------------------------------
# Report and Section: what a page is made of
# ---------------------------------------------------------------------------

class Section:
    """One table on a page."""

    def __init__(self, title, columns, note="", kind="table"):
        self.title = title
        self.note = note
        self.columns = list(columns)
        self.rows = []      # list of lists, one value per column
        self.refs = []      # per row: verse references behind it
        self.links = []     # per row: dict describing where a click can lead, or None
        self.footer = []    # lines printed under the table
        # How a display should draw it.  "table" is the default.  The
        # text renderer prints every kind as a table; the window draws
        # "heatmap" (rows x columns of numbers, colour for size) and
        # "bars" (one bar per row from the column named value_column)
        # as pictures, with the table beneath.
        self.kind = kind
        self.value_column = None    # bars: which column holds the bar length
        self.cell_refs = {}         # heatmap: (row index, column index) -> verse refs
        self.cell_links = {}        # heatmap: (row, column) -> link dict, looked up on click
        self.value_label = "weight" # heatmap: what a cell's number is (tooltips, help)
        self.x_column = None        # scatter: which columns give the point's place
        self.y_column = None

    def add(self, row, refs=None, link=None):
        """Add a row with its verse references and link."""
        self.rows.append(list(row))
        self.refs.append(list(refs or []))
        self.links.append(link)

    def merge_duplicates(self, key_column=0, score_column=None):
        """
        Merge rows whose text in key_column is identical, keeping the
        row with the higher score (the column named score_column, or
        the first numeric column) and the union of the verse references.
        Two phrase keys can render to one display text (Deuteronomy 25's
        "husband's brother" is a formula under H2993 and again under
        H2992; an echo found by root and again by wording), and a
        reader sees the same row twice with the same figures.
        """
        if score_column is None:
            score = next((i for i, c in enumerate(self.columns) if c.startswith("keyness") or c == "weight"), None)
        else:
            score = self.columns.index(score_column) if score_column in self.columns else None
        if score is None:
            score = next((i for i, c in enumerate(self.columns)
                          if self.rows and isinstance(self.rows[0][i], (int, float))), None)
        seen = {}
        rows, refs, links = [], [], []
        for row, ref, link in zip(self.rows, self.refs, self.links):
            key = str(row[key_column])
            if key in seen:
                i = seen[key]
                kept = rows[i]
                better = (score is not None and isinstance(row[score], (int, float))
                          and isinstance(kept[score], (int, float)) and row[score] > kept[score])
                merged_refs = list(dict.fromkeys(refs[i] + ref))
                if better:
                    rows[i], links[i] = row, link
                refs[i] = merged_refs
                continue
            seen[key] = len(rows)
            rows.append(row)
            refs.append(ref)
            links.append(link)
        self.rows, self.refs, self.links = rows, refs, links


class Report:
    """A whole page: title, notes, sections."""

    def __init__(self, name, title):
        self.name = name        # file-safe name used for reports/<name>.txt
        self.title = title
        self.notes = []
        self.sections = []
        self.started = time.perf_counter()
        self.timings = []       # (section title, start time), for --time

    def section(self, title, columns, note="", kind="table"):
        """Create, attach and return a new Section."""
        s = Section(title, columns, note, kind)
        self.sections.append(s)
        # When each section was begun, for --time: the gap to the next
        # section's start is roughly what this one cost to build
        self.timings.append((title, time.perf_counter()))
        return s

    def timing_line(self, finished=None):
        """
        One line of seconds per section, for --time.  A section's time
        is the gap from its start to the next section's start, the last
        section's to the page's end (finished, or now).
        """
        if not self.timings:
            return ""
        end = finished if finished is not None else time.perf_counter()
        starts = [t for _, t in self.timings] + [end]
        parts = []
        for (title, _), t0, t1 in zip(self.timings, starts, starts[1:]):
            number = title.split(" ")[0].rstrip(".")
            parts.append(f"{number} {t1 - t0:.2f}")
        return f"Timing (seconds per section, page {end - self.started:.2f}): " + ", ".join(parts)


def number_of(title):
    """
    The number a section title begins with: "1", "1a", "4a2", "7.2d",
    "7x", "3.5".  It is what stands before the first space, less a
    final dot: "7.2d. Function words" gives "7.2d" and "3.1 Neighbors"
    gives "3.1".
    """
    return title.split(" ")[0].rstrip(".")


def plain_title(report, translation=None):
    """The title without the translation tag, for a contents list."""
    title = report.title
    if translation:
        title = title.replace(f" ({translation})", "")
    return title


# ---------------------------------------------------------------------------
# The text layout
# ---------------------------------------------------------------------------

def render(report, atlas=None, timing=False):
    """
    Lay a Report out as plain text.  With the atlas given, the build
    line (program version, build label and date, roots rule, window)
    is printed under the title, so the file says what made it.
    """
    lines = ["WORD ATLAS  -  " + report.title]
    lines.append("#" * len(lines[0]))
    if atlas is not None:
        lines.append(atlas.build_line())
    lines.extend(report.notes)
    if timing:
        # The seconds each section took, printed to the terminal as the
        # page is laid out and kept in the file, so a slow page names
        # its slow table in one run
        line = report.timing_line()
        print(f"  {report.title}: {line}")
        lines.append(line)
    # The book page lists its sections by number and title at the head,
    # since it is the page a first reader opens and its numbering (1 to
    # 1f, 3.1 to 3.5, 4 to 4f, 7 and its letters, 7x) is not one a
    # reader can guess; the shorter, regular pages do without
    if (report.title.startswith("Book page") or getattr(report, "list_sections", False)) and report.sections:
        lines.append("")
        lines.append("Sections on this page:")
        for sec in report.sections:
            number, _, rest = sec.title.partition(" ")
            lines.append(f"  {number:<6} {rest}")

    for sec in report.sections:
        lines.append("")
        lines.append(sec.title)
        lines.append("=" * len(sec.title))
        if sec.note:
            lines.append(sec.note)
        # A section that declined (a 'Not measured' note and no rows)
        # keeps its title and reason and prints no table: a lone header
        # over a dash line said the opposite of what the note said
        if sec.columns and sec.rows:
            lines.append("")
            # Column widths: wide enough for the header and every value
            cells = [[str(v) for v in row] for row in sec.rows]
            widths = [len(c) for c in sec.columns]
            for row in cells:
                for i, v in enumerate(row):
                    widths[i] = max(widths[i], len(v))
            # Numbers and figure-like text right-aligned, words left-aligned
            numeric = [all(is_numeric_cell(row[i]) for row in sec.rows)
                       for i in range(len(sec.columns))]

            def fmt(values):
                out = []
                for i, v in enumerate(values):
                    out.append(v.rjust(widths[i]) if numeric[i] else v.ljust(widths[i]))
                return "  ".join(out).rstrip()

            lines.append(fmt(sec.columns))
            lines.append("-" * min(sum(widths) + 2 * len(widths), 110))
            for row in cells:
                lines.append(fmt(row))
        lines.append("")
        lines.extend(sec.footer)
    return "\n".join(lines).rstrip() + "\n"


def trim(report, top=None, only=None, quiet=False):
    """
    Cut a page down for reading at a glance: --top N keeps the first N
    rows of every table, --only 1,2,4a keeps only the sections whose
    number begins so (the number is what stands before the first dot
    or space in the title: 1, 1a, 4a2, 6b), and --quiet drops the
    section notes and footers.  The saved file is the trimmed page too.
    """
    if only:
        wanted = [s.strip().lower().rstrip(".") for s in only.split(",") if s.strip()]

        def number_of(title):
            return title.split(".")[0].split(" ")[0].lower()
        report.sections = [s for s in report.sections if number_of(s.title) in wanted]
    for sec in report.sections:
        if top is not None:
            sec.rows = sec.rows[:top]
        if quiet:
            # A section with no rows is a header with its reason in the
            # note (Revelation's 1b: the kind is in the other testament),
            # and the reason is the finding; --quiet keeps it and drops
            # the rest.  Without this the quiet page showed an empty table
            if sec.rows:
                sec.note = ""
            sec.footer = []
    if quiet:
        report.notes = report.notes[:1]
    return report


def save(report, text, out_dir=None):
    """Write the page under reports/ beside this script (or out_dir) and return the path."""
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, report.name + ".txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def dossier_text(head, pages):
    """
    A dossier's text from its head lines and its pages [(title, text)]:
    the head, then a list of the pages by the line each begins on and
    its length, then the pages joined by PAGE_SEPARATOR.  The head's own
    length is known before the numbers are (the fixed lines plus one
    per page), so each page's first line is the head, the separators
    and the pages before it added up; a reader with the file in an
    editor goes to the line, and a program reading the dossier finds
    the page the same way.
    """
    sep_lines = PAGE_SEPARATOR.count("\n")
    n_head = len(head) + 2 + len(pages)
    contents = ["", "Pages, by the line each begins on, and their length:"]
    line = n_head + sep_lines
    for title, text in pages:
        n_lines = text.count("\n")
        contents.append(f"  line {line:>7}, {n_lines:>5} lines: {title}")
        line += n_lines + sep_lines
    return PAGE_SEPARATOR.join(["\n".join(head + contents)] + [text for title, text in pages])


# ---------------------------------------------------------------------------
# The results database
# ---------------------------------------------------------------------------

RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY,
    version     TEXT NOT NULL,           -- the program version
    build       TEXT NOT NULL,           -- the atlas's build line
    started     TEXT NOT NULL,           -- when the run began
    note        TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pages (
    page_id     INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES runs(run_id),
    name        TEXT NOT NULL,           -- the report's file-safe name
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL,           -- Book, Chapter, Section, Passage, Word, Kin, Testament, Compare
    notes       TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sections (
    section_id  INTEGER PRIMARY KEY,
    page_id     INTEGER NOT NULL REFERENCES pages(page_id),
    position    INTEGER NOT NULL,        -- the section's place on the page
    number      TEXT NOT NULL,           -- 1, 1a, 4e, 7.2d
    title       TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'table',
    columns     TEXT NOT NULL,           -- the column names, tab-separated
    n_rows      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cells (
    section_id  INTEGER NOT NULL REFERENCES sections(section_id),
    row         INTEGER NOT NULL,
    col         INTEGER NOT NULL,
    column      TEXT NOT NULL,
    value       TEXT NOT NULL,           -- the cell as the page prints it
    number      REAL,                    -- the cell as a number, when it is one
    PRIMARY KEY (section_id, row, col)
);
CREATE TABLE IF NOT EXISTS refs (
    section_id  INTEGER NOT NULL REFERENCES sections(section_id),
    row         INTEGER NOT NULL,
    reference   TEXT NOT NULL            -- a verse behind the row, as the page keeps it for the click
);
CREATE TABLE IF NOT EXISTS footers (
    section_id  INTEGER NOT NULL REFERENCES sections(section_id),
    position    INTEGER NOT NULL,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pages_run ON pages (run_id, kind, title);
CREATE INDEX IF NOT EXISTS idx_sections_page ON sections (page_id, number);
CREATE INDEX IF NOT EXISTS idx_cells_section ON cells (section_id, column);
CREATE INDEX IF NOT EXISTS idx_refs_section ON refs (section_id, row);
"""


# The heat tables (0.10.101): written by atlas_heat.py on every run, so
# the strips a heat report prints and charts are rows the Reader can
# draw from, and Eval_data/ransom_rest_report.py reads its tables from
# them instead of counting afresh.  A strip's figures depend on how it
# was measured (the scale, what "ordinary" is, the window), so those
# three stand in every key beside the book and the strip.
HEAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS heat_strips (
    strip       TEXT NOT NULL,           -- the strip's name as the report heads it: density, emotion, ransom, persons
    testament   TEXT NOT NULL,           -- Old or New: the testament whose books it is drawn for
    kind        TEXT NOT NULL,           -- measure, feeling, feeling family, word list, names, context, voice
    description TEXT NOT NULL,           -- one sentence saying what it measures
    roots       TEXT NOT NULL DEFAULT '',-- a word list's roots with their plain words, one 'H3701 silver' per line
    updated     TEXT NOT NULL,           -- when a run last wrote it
    PRIMARY KEY (strip, testament)
);
CREATE TABLE IF NOT EXISTS heat_windows (
    book          TEXT NOT NULL,
    scale         TEXT NOT NULL,         -- z, percentile or g2 (atlas_heat.py --scale)
    norm          TEXT NOT NULL,         -- what ordinary is: bible, book, group or group:NAME (--norm)
    window_size   INTEGER NOT NULL,      -- verses per window (--window)
    strip         TEXT NOT NULL,
    position      INTEGER NOT NULL,      -- the window's place in the book, from 0
    start_chapter INTEGER NOT NULL,
    start_verse   INTEGER NOT NULL,
    end_chapter   INTEGER NOT NULL,
    end_verse     INTEGER NOT NULL,
    z             REAL NOT NULL,         -- the window's score in z-like units
    PRIMARY KEY (book, scale, norm, window_size, strip, position)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS heat_spots (
    book          TEXT NOT NULL,
    scale         TEXT NOT NULL,
    norm          TEXT NOT NULL,
    window_size   INTEGER NOT NULL,
    strip         TEXT NOT NULL,
    line          TEXT NOT NULL,         -- 'spot' at the run's threshold, 'near' at three quarters of it
    threshold     REAL NOT NULL,         -- the line in z-like units
    hot           INTEGER NOT NULL,      -- 1 for a hot spot, 0 for a cool one
    span          TEXT NOT NULL,         -- the verse range as the report prints it: 'Genesis 23:7-24:2'
    start_chapter INTEGER NOT NULL,
    start_verse   INTEGER NOT NULL,
    end_chapter   INTEGER NOT NULL,
    end_verse     INTEGER NOT NULL,
    peak_z        REAL NOT NULL,         -- the highest (or, cool, the lowest) window's score
    peak_shown    TEXT NOT NULL,         -- the peak as the report prints it: 'z +3.29'
    peak_at       TEXT NOT NULL,         -- the middle verse of the peak window: '23:12'
    words         TEXT NOT NULL DEFAULT ''  -- the words that lit it, with their counts, as the report prints them
);
CREATE INDEX IF NOT EXISTS idx_heat_spots ON heat_spots (book, strip, scale, norm, window_size, line);
"""

# The tables atlas_pack.py adds to the packed copy, so that the .wadb
# holds everything the Reader shows: the named passages of metadata.db
# and the King James text with its Strong's tags from atlas_source.db.
PACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS passages (
    passage_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    source_note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS passage_ranges (
    passage_id    INTEGER NOT NULL REFERENCES passages(passage_id),
    book_num      INTEGER NOT NULL,
    chapter_start INTEGER NOT NULL,
    verse_start   INTEGER NOT NULL,
    chapter_end   INTEGER NOT NULL,
    verse_end     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kjv_books (
    book_num    INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    abbreviation TEXT NOT NULL,
    testament   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kjv_verses (
    verse_id    INTEGER PRIMARY KEY,
    book_num    INTEGER NOT NULL,
    chapter     INTEGER NOT NULL,
    verse       INTEGER NOT NULL,
    text        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kjv_tags (
    verse_id    INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    strongs     TEXT NOT NULL,
    morphology  TEXT,
    word        TEXT
);
CREATE INDEX IF NOT EXISTS idx_kjv_verses ON kjv_verses (book_num, chapter, verse);
CREATE INDEX IF NOT EXISTS idx_kjv_tags ON kjv_tags (verse_id);
"""

SCHEMA_NOTES_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_notes (
    table_name  TEXT NOT NULL,
    column_name TEXT NOT NULL,           -- '' for a line about the table as a whole
    meaning     TEXT NOT NULL,           -- what it holds, in plain words
    units       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (table_name, column_name)
);
"""

# (table, column, what it holds, units).  A column of '' describes the
# table.  Kept here, beside the schemas, so a new column gets its line
# in the same edit; test_atlas.py checks the pack refuses a file without
# the table.
SCHEMA_NOTES = [
    ("runs", "", "One row per run of the program that wrote pages into this file.", ""),
    ("runs", "run_id", "The run's number.", "integer"),
    ("runs", "version", "The Word Atlas version that made the run.", "version number"),
    ("runs", "build", "The atlas's build line: its label, when it was built, how roots were counted.", "text"),
    ("runs", "started", "When the run began.", "date and time"),
    ("runs", "note", "What the run was, as given when it began (dossier all, a test).", "text"),
    ("pages", "", "One row per page a run wrote: a book page, a chapter page, a word page and so on.", ""),
    ("pages", "page_id", "The page's number.", "integer"),
    ("pages", "run_id", "The run that wrote it (runs.run_id).", "integer"),
    ("pages", "name", "The page's file-safe name, as reports/<name>.txt would have it.", "text"),
    ("pages", "title", "The page's title as printed at its head.", "text"),
    ("pages", "kind", "Book, Chapter, Section, Passage, Word, Kin, Testament or Compare.", "text"),
    ("pages", "notes", "The lines printed under the title, one per line.", "text"),
    ("sections", "", "One row per table on a page.", ""),
    ("sections", "section_id", "The table's number.", "integer"),
    ("sections", "page_id", "The page it is on (pages.page_id).", "integer"),
    ("sections", "position", "Its place on the page, from 0.", "integer"),
    ("sections", "number", "The section number as printed: 1, 1a, 4e, 7.2d, 7v.", "text"),
    ("sections", "title", "The section's title as printed.", "text"),
    ("sections", "note", "The note under the title: what the table is and how to read it, or why it declined.", "text"),
    ("sections", "kind", "How a display draws it: table, heatmap, bars or scatter.", "text"),
    ("sections", "columns", "The column names, separated by tabs.", "text"),
    ("sections", "n_rows", "How many rows the table has.", "count"),
    ("cells", "", "Every cell of every table, one row per cell.", ""),
    ("cells", "section_id", "The table (sections.section_id).", "integer"),
    ("cells", "row", "The row, from 0.", "integer"),
    ("cells", "col", "The column, from 0.", "integer"),
    ("cells", "column", "The column's name.", "text"),
    ("cells", "value", "The cell exactly as the page prints it.", "text"),
    ("cells", "number", "The cell as a number when it is one, for sums and sorting; empty otherwise.", "number"),
    ("refs", "", "The verses behind a table row, as a click in the window opens them.", ""),
    ("refs", "section_id", "The table (sections.section_id).", "integer"),
    ("refs", "row", "The row, from 0.", "integer"),
    ("refs", "reference", "A verse reference: 'Genesis 23:7'.", "verse reference"),
    ("footers", "", "The lines printed under a table.", ""),
    ("footers", "section_id", "The table (sections.section_id).", "integer"),
    ("footers", "position", "The line's place, from 0.", "integer"),
    ("footers", "text", "The line as printed.", "text"),
    ("heat_strips", "", "One row per heat strip and testament: what the strip measures, written by atlas_heat.py.", ""),
    ("heat_strips", "strip", "The strip's name as the heat report heads it.", "text"),
    ("heat_strips", "testament", "The testament whose books the strip is drawn for: Old or New.", "text"),
    ("heat_strips", "kind", "measure, feeling, feeling family, word list, names, context (what a passage is about) "
                            "or voice (who speaks to whom).", "text"),
    ("heat_strips", "description", "One sentence saying what the strip measures.", "text"),
    ("heat_strips", "roots", "For a word-list strip, its roots with their plain words, one per line, copied from "
                             "metadata.db's word_lists when the run was made; empty for other strips.", "Strong's number and word"),
    ("heat_strips", "updated", "When a run last wrote the row.", "date and time"),
    ("heat_windows", "", "Every window's score on every strip a heat run drew: the numbers behind the strip charts.", ""),
    ("heat_windows", "book", "The book.", "book name"),
    ("heat_windows", "scale", "How the score was measured: z (distance from ordinary in spreads), percentile or g2 "
                              "(log-likelihood); all three are stored in the same z-like units.", "text"),
    ("heat_windows", "norm", "What 'ordinary' was: bible (every book of the same language), book (the book itself), "
                             "group (the other books of its kind) or group:NAME.", "text"),
    ("heat_windows", "window_size", "Verses in each window.", "verses"),
    ("heat_windows", "strip", "The strip (heat_strips.strip).", "text"),
    ("heat_windows", "position", "The window's place in the book, from 0; the window moves one verse at a time.", "integer"),
    ("heat_windows", "start_chapter", "The chapter of the window's first verse.", "chapter"),
    ("heat_windows", "start_verse", "The window's first verse.", "verse"),
    ("heat_windows", "end_chapter", "The chapter of the window's last verse.", "chapter"),
    ("heat_windows", "end_verse", "The window's last verse.", "verse"),
    ("heat_windows", "z", "The window's score: 0 is ordinary, +2 far above (about the top 2.3%), -2 far below.",
     "z-like units"),
    ("heat_spots", "", "The hot and cool spots of each strip: runs of windows past a line, joined when they share "
                       "half a window, as the heat report lists them.", ""),
    ("heat_spots", "book", "The book.", "book name"),
    ("heat_spots", "scale", "As in heat_windows.", "text"),
    ("heat_spots", "norm", "As in heat_windows.", "text"),
    ("heat_spots", "window_size", "As in heat_windows.", "verses"),
    ("heat_spots", "strip", "The strip (heat_strips.strip).", "text"),
    ("heat_spots", "line", "spot: past the run's threshold, as the report lists them; near: past three quarters of "
                           "it (z 1.5 when the threshold is 2), for 'near miss' readings.", "text"),
    ("heat_spots", "threshold", "The line the windows had to pass.", "z-like units"),
    ("heat_spots", "hot", "1 for a hot spot (above), 0 for a cool one (below).", "0 or 1"),
    ("heat_spots", "span", "The verses from the first window's start to the last window's end, as printed.", "verse range"),
    ("heat_spots", "start_chapter", "The chapter where the spot begins.", "chapter"),
    ("heat_spots", "start_verse", "The verse where the spot begins.", "verse"),
    ("heat_spots", "end_chapter", "The chapter where the spot ends.", "chapter"),
    ("heat_spots", "end_verse", "The verse where the spot ends.", "verse"),
    ("heat_spots", "peak_z", "The score of the spot's strongest window.", "z-like units"),
    ("heat_spots", "peak_shown", "The peak as the report prints it, with its scale's own figure.", "text"),
    ("heat_spots", "peak_at", "The middle verse of the strongest window.", "chapter:verse"),
    ("heat_spots", "words", "The words that lit the spot with their counts, as the report prints them: the hammered "
                            "word, a family's categories and words, or a names or word-list strip's words.", "text"),
    ("passages", "", "The named passages of the catalogue (metadata.db), copied in when the file is packed.", ""),
    ("passages", "passage_id", "The passage's number.", "integer"),
    ("passages", "name", "Its name: Harlot city, Ransom and rest.", "text"),
    ("passages", "description", "What it is.", "text"),
    ("passages", "source_note", "Where its ranges come from.", "text"),
    ("passage_ranges", "", "The verse ranges of each named passage.", ""),
    ("passage_ranges", "passage_id", "The passage (passages.passage_id).", "integer"),
    ("passage_ranges", "book_num", "The book: 1 is Genesis, 66 Revelation.", "book number"),
    ("passage_ranges", "chapter_start", "The range's first chapter.", "chapter"),
    ("passage_ranges", "verse_start", "The range's first verse.", "verse"),
    ("passage_ranges", "chapter_end", "The range's last chapter.", "chapter"),
    ("passage_ranges", "verse_end", "The range's last verse.", "verse"),
    ("kjv_books", "", "The books of the King James text, copied from atlas_source.db when the file is packed.", ""),
    ("kjv_books", "book_num", "The book's number: 1 is Genesis, 66 Revelation.", "book number"),
    ("kjv_books", "name", "The book's name.", "text"),
    ("kjv_books", "abbreviation", "Its short name.", "text"),
    ("kjv_books", "testament", "Old or New.", "text"),
    ("kjv_verses", "", "The King James text, one row per verse, as Word Atlas builds on it.", ""),
    ("kjv_verses", "verse_id", "The verse's number in atlas_source.db (kjv_tags.verse_id).", "integer"),
    ("kjv_verses", "book_num", "The book (kjv_books.book_num).", "book number"),
    ("kjv_verses", "chapter", "The chapter.", "chapter"),
    ("kjv_verses", "verse", "The verse.", "verse"),
    ("kjv_verses", "text", "The verse's text.", "text"),
    ("kjv_tags", "", "The Strong's numbers tagged on the King James words.", ""),
    ("kjv_tags", "verse_id", "The verse (kjv_verses.verse_id).", "integer"),
    ("kjv_tags", "position", "The word's place in the verse.", "integer"),
    ("kjv_tags", "strongs", "The Strong's number: H3701, G3056.", "Strong's number"),
    ("kjv_tags", "morphology", "The tag's grammar code, where the source gives one.", "code"),
    ("kjv_tags", "word", "The English word or words the number is tagged on.", "text"),
    ("schema_notes", "", "This table: what every table and column of the file holds, in plain words.", ""),
    ("schema_notes", "table_name", "The table.", "text"),
    ("schema_notes", "column_name", "The column, or empty for the table as a whole.", "text"),
    ("schema_notes", "meaning", "What it holds.", "text"),
    ("schema_notes", "units", "Its units.", "text"),
]


def ensure_results_schema(db):
    """
    Create every table of the results file that is missing (the pages,
    the heat tables, schema_notes) and write schema_notes afresh, so a
    file written by any part of the program describes itself.  The
    pack's own tables (passages, the King James text) are added by
    atlas_pack.py to the packed copy only.
    """
    db.executescript(RESULTS_SCHEMA + HEAT_SCHEMA + SCHEMA_NOTES_SCHEMA)
    db.executemany("INSERT OR REPLACE INTO schema_notes VALUES (?, ?, ?, ?)", SCHEMA_NOTES)
    db.commit()


def results_path():
    """reports/results.db beside the program, where the dossier and the heat runs write."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "results.db")


class ResultsWriter:
    """
    Writes reports to a SQLite results file, the same Report objects
    the text renderer prints, so that every figure on every page is a
    row that a query can reach: all the 7d Deltas of the canon, every
    1f share, every seam 4e found, every declined table with its
    reason.  One run (a version, a build, a start time) holds many
    pages; the runs table lets two runs be compared row by row, which
    is the reviewer's diff of two dossiers made exact.

        writer = ResultsWriter("reports/results.db")
        run = writer.begin(atlas, note="dossier all")
        writer.write(report, run)
        writer.close()
    """

    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path)
        # Every table, the heat tables and schema_notes among them, so
        # the file describes itself whichever program wrote it first
        ensure_results_schema(self.db)

    def begin(self, atlas, note=""):
        """Open a run and return its id."""
        from atlas_pages import VERSION
        cur = self.db.execute("INSERT INTO runs (version, build, started, note) VALUES (?, ?, ?, ?)",
                              (VERSION, atlas.build_line(), time.strftime("%Y-%m-%d %H:%M:%S"), note))
        self.db.commit()
        return cur.lastrowid

    def write(self, report, run_id):
        """
        Write one report under a run; returns its page_id.  A page is
        stored once per run, keyed by its title: a cross-book section
        page is rendered into the dossier of every book it takes, and
        the first copy stands for all of them.
        """
        existing = self.db.execute("SELECT page_id FROM pages WHERE run_id = ? AND title = ?",
                                   (run_id, report.title)).fetchone()
        if existing:
            return existing[0]
        kind = report.title.split(" ")[0]
        cur = self.db.execute("INSERT INTO pages (run_id, name, title, kind, notes) VALUES (?, ?, ?, ?, ?)",
                              (run_id, report.name, report.title, kind, "\n".join(report.notes)))
        page_id = cur.lastrowid
        for position, sec in enumerate(report.sections):
            cur = self.db.execute(
                "INSERT INTO sections (page_id, position, number, title, note, kind, columns, n_rows) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (page_id, position, number_of(sec.title), sec.title, sec.note, sec.kind,
                 "\t".join(str(c) for c in sec.columns), len(sec.rows)))
            section_id = cur.lastrowid
            cells = []
            for r, row in enumerate(sec.rows):
                for c, value in enumerate(row):
                    # A number, or a string that is one ("235.4" in a run
                    # column), fills the number column for arithmetic
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        number = float(value)
                    elif isinstance(value, str) and NUMBER.fullmatch(value.strip()):
                        number = float(value.strip().replace(",", ""))
                    else:
                        number = None
                    cells.append((section_id, r, c, str(sec.columns[c]) if c < len(sec.columns) else "", str(value), number))
            self.db.executemany("INSERT INTO cells VALUES (?, ?, ?, ?, ?, ?)", cells)
            refs = [(section_id, r, ref) for r, row_refs in enumerate(sec.refs) for ref in row_refs]
            if refs:
                self.db.executemany("INSERT INTO refs VALUES (?, ?, ?)", refs)
            if sec.footer:
                self.db.executemany("INSERT INTO footers VALUES (?, ?, ?)",
                                    [(section_id, i, text) for i, text in enumerate(sec.footer)])
        self.db.commit()
        return page_id

    def close(self):
        self.db.close()
