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
        # as pictures, with the table beneath; "strip" is a theme's strip
        # (atlas_pages.theme_page), drawn from the section's own .strip
        # list of every chapter, with the table of chapters beneath.
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
    kind        TEXT NOT NULL,           -- Book, Chapter, Section, Passage, Word, Kin, Testament, Compare, Theme
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

# The outside datasets the figures rest on, one row each, copied from
# the table at the end of ATTRIBUTION.md (read_attribution below) every
# time the results file is opened for writing, and carried in the pack,
# so the credit travels with the numbers (0.10.103)
SOURCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    position    INTEGER PRIMARY KEY,     -- the row's place in ATTRIBUTION.md's table
    name        TEXT NOT NULL,           -- the dataset
    supplies    TEXT NOT NULL,           -- what it supplies to the atlas
    license     TEXT NOT NULL,           -- the license it is used under
    credit      TEXT NOT NULL,           -- the credit line it asks for
    adapted     TEXT NOT NULL            -- 'yes: what was made' or 'no: why not'
);
"""

# The constellations (atlas_sets.py, 0.10.110): sets of two to five roots
# that occur together in one stretch of text far more often than their
# separate rates predict, with the stretches behind each set
SETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS word_sets (
    set_id       INTEGER PRIMARY KEY,
    run_id       INTEGER,                 -- the run it was written under (runs.run_id)
    scope        TEXT NOT NULL,           -- Old, New, or a book name
    norm         TEXT NOT NULL,           -- book (against the book itself) or testament (against its testament)
    scale        TEXT NOT NULL,           -- window, verse or chapter
    window_size  INTEGER NOT NULL,        -- verses per window; 1 for verse, 0 for chapter
    size         INTEGER NOT NULL,        -- roots in the set, 2 to 5
    roots        TEXT NOT NULL,           -- the Strong's numbers in canonical order, space-separated
    words        TEXT NOT NULL,           -- their commonest King James spellings, for reading
    support      INTEGER NOT NULL,        -- units the set occurs in
    stretches    INTEGER NOT NULL,        -- those units joined where they follow one another
    expected     REAL NOT NULL,           -- the support if the roots fell independently
    lift         REAL NOT NULL,           -- support / expected
    keyness      REAL NOT NULL,           -- Dunning's G2 of support against expected
    phrase_units INTEGER NOT NULL,        -- units in which the roots stand inside one formula run
    frame_units  INTEGER NOT NULL,        -- units in which they come in one order within twelve content words
    in_order     REAL NOT NULL,           -- frame_units / support: the share of units in that order
    kind         TEXT NOT NULL,           -- constellation, frame (three roots or more) or phrase
    closed       INTEGER NOT NULL,        -- 1 when no larger kept set has the same support
    folds        INTEGER NOT NULL,        -- for a closed set: how many smaller sets fold under it
    parent       INTEGER,                 -- for a set that is not closed: the closed set it folds under
    span         INTEGER NOT NULL,        -- chapters from the first stretch to the last
    inclusio     INTEGER NOT NULL         -- 1 when every stretch lies at the two ends of the book
);
CREATE TABLE IF NOT EXISTS word_set_members (
    set_id   INTEGER NOT NULL REFERENCES word_sets(set_id),
    root     TEXT NOT NULL,
    word     TEXT NOT NULL,
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS word_set_windows (
    set_id        INTEGER NOT NULL REFERENCES word_sets(set_id),
    book          TEXT NOT NULL,
    start_chapter INTEGER NOT NULL,
    start_verse   INTEGER NOT NULL,
    end_chapter   INTEGER NOT NULL,
    end_verse     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_word_sets_scope ON word_sets (run_id, scope, norm, scale, size, keyness);
CREATE INDEX IF NOT EXISTS idx_word_set_members_root ON word_set_members (root);
CREATE INDEX IF NOT EXISTS idx_word_set_windows_set ON word_set_windows (set_id);
"""

# The renderings layer (atlas_renderings.py, 0.10.113): how each public
# domain English translation renders each Hebrew and Greek root, learned by
# aligning it with the King James, and how far the translations stand apart
# verse by verse.  Words and counts only, never text
RENDERINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS renderings (
    root        TEXT NOT NULL,            -- the Strong's number
    word        TEXT NOT NULL,            -- the King James's commonest spelling of it, for reading
    translation TEXT NOT NULL,            -- the translation's abbreviation (ASV, YLT ...)
    rendering   TEXT NOT NULL,            -- the word the translation uses for it, as spelled; '(other)' for the rest
    count       INTEGER NOT NULL,         -- tagged occurrences of the root rendered so
    share       REAL NOT NULL,            -- count / the root's tagged occurrences in the translation
    testament   TEXT NOT NULL             -- Old (a Hebrew root) or New (a Greek root)
);
CREATE TABLE IF NOT EXISTS renderings_summary (
    root        TEXT NOT NULL,
    translation TEXT NOT NULL,
    leading     TEXT NOT NULL,            -- the translation's commonest rendering of the root
    share       REAL NOT NULL,            -- its share
    distinct_renderings INTEGER NOT NULL, -- how many different spellings render the root
    renderings_folded INTEGER NOT NULL,   -- how many different words, endings and spellings folded
    tagged      INTEGER NOT NULL,         -- the root's tagged occurrences in the translation
    testament   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS renderings_translations (
    translation TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    year        INTEGER,
    verses      INTEGER NOT NULL,         -- verses it has
    words       INTEGER NOT NULL,         -- its content words (stop words set aside)
    tagged      INTEGER NOT NULL,         -- of them, those given a Strong's number through the alignment
    share       REAL NOT NULL,            -- tagged / words: how far to trust its rows
    pairs       INTEGER NOT NULL,         -- trusted pairings with the King James's words
    made        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS disagreement_verses (
    reference    TEXT PRIMARY KEY,
    book         TEXT NOT NULL,
    chapter      INTEGER NOT NULL,
    verse        INTEGER NOT NULL,
    mean_distance REAL,                   -- mean Jaccard distance over every pair of translations having the verse
    excess       REAL,                    -- the same less each pair's mean distance over the Bible: the crux order
    present      INTEGER NOT NULL,        -- translations having the verse
    expected     INTEGER NOT NULL,        -- translations having the book
    missing      REAL NOT NULL,           -- the share lacking the verse (merged ones not counted)
    merged       INTEGER NOT NULL,        -- translations holding the verse inside a neighbour (verse division)
    merged_with  TEXT NOT NULL,           -- each as translation>neighbour verse ("JPS>3:33"), space-separated
    names        INTEGER NOT NULL,        -- the King James's proper names in the verse, set aside from the distance
    far_a        TEXT NOT NULL,           -- the two translations furthest apart on it
    far_b        TEXT NOT NULL,
    far_distance REAL,
    outlier      TEXT NOT NULL,           -- the translation furthest beyond its usual distance from the rest
    unique_words TEXT NOT NULL            -- content words no two translations share, space-separated
);
CREATE INDEX IF NOT EXISTS idx_renderings_root ON renderings (root, translation);
CREATE INDEX IF NOT EXISTS idx_renderings_word ON renderings (rendering);
CREATE INDEX IF NOT EXISTS idx_renderings_summary ON renderings_summary (translation, share);
CREATE INDEX IF NOT EXISTS idx_disagreement ON disagreement_verses (excess);
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
    ("pages", "kind", "Book, Chapter, Section, Passage, Word, Kin, Testament, Compare or Theme.", "text"),
    ("pages", "notes", "The lines printed under the title, one per line.", "text"),
    ("sections", "", "One row per table on a page.", ""),
    ("sections", "section_id", "The table's number.", "integer"),
    ("sections", "page_id", "The page it is on (pages.page_id).", "integer"),
    ("sections", "position", "Its place on the page, from 0.", "integer"),
    ("sections", "number", "The section number as printed: 1, 1a, 4e, 7.2d, 7v.", "text"),
    ("sections", "title", "The section's title as printed.", "text"),
    ("sections", "note", "The note under the title: what the table is and how to read it, or why it declined.", "text"),
    ("sections", "kind", "How a display draws it: table, heatmap, bars, scatter or strip (a theme's strip).", "text"),
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
    ("sources", "", "The outside datasets the figures rest on, with the license and the credit each asks for, "
                    "copied from the table at the end of ATTRIBUTION.md in the Word Atlas folder.", ""),
    ("sources", "position", "The row's place in that table.", "integer"),
    ("sources", "name", "The dataset.", "text"),
    ("sources", "supplies", "What it supplies to the atlas: a text, a column, a table, a footer.", "text"),
    ("sources", "license", "The license it is used under.", "text"),
    ("sources", "credit", "The credit line it asks for, to be given with any figure resting on it.", "text"),
    ("sources", "adapted", "Whether the atlas's figures are an adaptation of it (counts, reduced tables, derived pairs "
                           "or maps): 'yes' and what was made, or 'no' and why not.", "text"),
    ("schema_notes", "", "This table: what every table and column of the file holds, in plain words.", ""),
    ("schema_notes", "table_name", "The table.", "text"),
    ("schema_notes", "column_name", "The column, or empty for the table as a whole.", "text"),
    ("schema_notes", "meaning", "What it holds.", "text"),
    ("schema_notes", "units", "Its units.", "text"),
    ("theme", "", "One row per theme: a hand-made set of verses that belong together (themes/*.json), "
                  "copied from atlas.db, where atlas_themes.py loaded it.", ""),
    ("theme", "theme_id", "The theme's short id (land_inheritance).", "text"),
    ("theme", "name", "The name the pages show (Land and inheritance).", "text"),
    ("theme", "created", "When the theme file was made.", "date"),
    ("theme", "source_file", "The verse list the theme was imported from.", "text"),
    ("theme", "require_patterns", "The patterns every core verse holds, as a JSON list of regular expressions.", "JSON"),
    ("theme", "home", "The home range as the file gives it: empty for the whole Bible, Old, New, books or passage:NAME.", "text"),
    ("theme", "home_label", "The home range in words.", "text"),
    ("theme", "cushion", "The cushion of the lift per chapter (2, as atlas_lift.py).", "verses"),
    ("theme", "notes", "The theme's own notes.", "text"),
    ("theme", "file", "The theme file in themes/.", "text"),
    ("theme", "loaded", "When it was loaded into atlas.db.", "date and time"),
    ("theme", "build", "The build it was loaded into: its label and date.", "text"),
    ("theme", "n_core", "Its core verses.", "verses"),
    ("theme", "n_borderline", "Its borderline verses.", "verses"),
    ("theme", "n_excluded", "Its excluded verses.", "verses"),
    ("theme", "n_chapters", "The chapters holding a counted verse.", "chapters"),
    ("theme_verse", "", "Every verse of every theme with its role, in canonical order.", ""),
    ("theme_verse", "theme_id", "The theme (theme.theme_id).", "text"),
    ("theme_verse", "book", "The book.", "book name"),
    ("theme_verse", "chapter", "The chapter.", "chapter"),
    ("theme_verse", "verse", "The verse.", "verse"),
    ("theme_verse", "reference", "The reference as the theme file has it (Deu 4:1).", "text"),
    ("theme_verse", "verse_id", "The atlas verse it was matched to; empty when the atlas does not hold it.", "integer"),
    ("theme_verse", "role", "core (the theme is about it), borderline (matches but stands apart) or excluded "
                            "(a false match, never counted).", "text"),
    ("theme_verse", "reason", "Why a verse is borderline or excluded.", "text"),
    ("theme_verse", "source_refs", "The references as the verse list wrote them, a JSON list.", "JSON"),
    ("theme_verse", "texts", "The texts the verse list gave, a JSON list.", "JSON"),
    ("theme_verse", "position", "The verse's place in canonical order within its theme, from 0.", "integer"),
    ("theme_verse", "text", "The King James text of the verse as the atlas holds it.", "text"),
    ("theme_verse", "as_written", "The references as written, when the list used another numbering.", "text"),
    ("theme_strip", "", "Every theme's strip: one row per chapter of the canon in order, with the counts, "
                        "the lift per chapter and the colour to draw, all worked out by the main program.", ""),
    ("theme_strip", "theme_id", "The theme (theme.theme_id).", "text"),
    ("theme_strip", "position", "The chapter's place in canonical order: 0 is Genesis 1, 1188 Revelation 22.", "integer"),
    ("theme_strip", "book", "The book.", "book name"),
    ("theme_strip", "chapter", "The chapter.", "chapter"),
    ("theme_strip", "chapter_verses", "The verses of the chapter.", "verses"),
    ("theme_strip", "in_home", "1 when the chapter is in the theme's home range, 0 when not (drawn grey).", "0 or 1"),
    ("theme_strip", "core", "The theme's core verses in the chapter.", "verses"),
    ("theme_strip", "all_verses", "Core plus borderline verses in the chapter.", "verses"),
    ("theme_strip", "expected_core", "The core verses the chapter would hold by chance: the theme's core verses in "
                                     "the home range times the chapter's share of its verses.", "verses"),
    ("theme_strip", "expected_all", "The same for core plus borderline.", "verses"),
    ("theme_strip", "lift_core", "The lift per chapter: (core + cushion) / (expected_core + cushion); 1.0 is ordinary.", "ratio"),
    ("theme_strip", "lift_all", "The same for core plus borderline.", "ratio"),
    ("theme_strip", "section", "The chapter's section of its book (atlas_sections.py); empty when the book has none.", "text"),
    ("theme_strip", "section_start", "1 when a section of the book begins at this chapter.", "0 or 1"),
    ("theme_strip", "colour_core", "The cell's colour for core verses, ready to draw: grey outside the home range, "
                                   "plain for none, else blue through grey to red by the lift.", "#rrggbb"),
    ("theme_strip", "colour_all", "The same for core plus borderline.", "#rrggbb"),
    ("theme_term", "", "A theme's companion terms, by Strong's number and root; not searched yet.", ""),
    ("theme_term", "theme_id", "The theme.", "text"),
    ("theme_term", "strongs", "The Strong's number (H5159, G2817).", "Strong's number"),
    ("theme_term", "root", "The root, where it is not a Strong's number.", "text"),
    ("theme_term", "note", "A note on the term.", "text"),
    ("theme_problem", "", "References of a theme file the atlas could not place: reported, not counted.", ""),
    ("theme_problem", "theme_id", "The theme.", "text"),
    ("theme_problem", "reference", "The reference as the theme file has it.", "text"),
    ("theme_problem", "problem", "Why it could not be placed.", "text"),
    ("word_sets", "", "The constellations (atlas_sets.py): sets of two to five roots that occur together in one "
                      "stretch of text far more often than their separate rates predict, found by the frequent "
                      "itemset search; a set whose roots stand inside one formula in most of its units is kept "
                      "as a phrase instead.", ""),
    ("word_sets", "set_id", "The set's number.", "integer"),
    ("word_sets", "run_id", "The run it was written under (runs.run_id).", "integer"),
    ("word_sets", "scope", "Where it was searched: Old, New, or a book.", "text"),
    ("word_sets", "norm", "What the expected count is measured against: book (the book's own windows) or "
                          "testament (the testament's rates, so a book's pervasive words can stand out); a "
                          "testament's own sets have norm testament.", "text"),
    ("word_sets", "scale", "The unit of co-occurrence: window (verses moving one at a time inside a book), verse "
                           "or chapter.", "text"),
    ("word_sets", "window_size", "Verses per window; 1 at the verse scale, 0 at the chapter scale.", "verses"),
    ("word_sets", "size", "How many roots the set holds.", "roots"),
    ("word_sets", "roots", "Its Strong's numbers in canonical order, separated by spaces.", "Strong's numbers"),
    ("word_sets", "words", "Their commonest King James spellings, for reading.", "text"),
    ("word_sets", "support", "The units the set occurs in: every one of its roots has a token there.", "units"),
    ("word_sets", "stretches", "Those units joined where they follow one another or overlap: the separate places "
                               "the set gathers (a ten-verse window moving a verse at a time counts one place up "
                               "to ten times in support).", "stretches"),
    ("word_sets", "expected", "The support if the roots fell independently: units times the product of each "
                              "root's share of the units.", "units"),
    ("word_sets", "lift", "support / expected.  Against the book itself the expected count is the units times "
                          "the product of each root's share; the floor grows with the size: 3 for pairs, 10 for "
                          "triples, 30 for four and five.  Against the testament it is the set's concentration in "
                          "the book (expected = the book's units times the set's testament rate), at least 3.",
     "ratio"),
    ("word_sets", "keyness", "Dunning's G2 of support against expected; at least 10.8.", "G2"),
    ("word_sets", "phrase_units", "Units in which all the roots stand inside one formula run.", "units"),
    ("word_sets", "frame_units", "Units in which the roots come in one same order within twelve content words "
                                 "(stop words not counted).", "units"),
    ("word_sets", "in_order", "frame_units / support: the share of the set's units in which its roots keep one "
                              "order.", "share"),
    ("word_sets", "kind", "phrase (inside one formula run in more than half its units), frame (three roots or "
                          "more, not a phrase, and in one same order within twelve content words in more than "
                          "half: a formula with gaps), or constellation (a pair in order stays one).", "text"),
    ("word_sets", "closed", "1 when no larger kept set has the same support; a set with 0 says nothing its "
                            "larger set does not.", "0 or 1"),
    ("word_sets", "folds", "For a closed set, how many smaller sets of the same support fold under it.", "sets"),
    ("word_sets", "parent", "For a set that is not closed, the closed set it folds under (word_sets.set_id); "
                            "empty for a closed set.", "integer"),
    ("word_sets", "span", "Chapters from the start of the set's first stretch to the end of its last.", "chapters"),
    ("word_sets", "inclusio", "1 when, in a book, every stretch lies in the first or last 15% of its "
                              "chapters, with one at each end: a frame found by counting.", "0 or 1"),
    ("word_set_members", "", "Each root of each set, so every set holding one root can be found.", ""),
    ("word_set_members", "set_id", "The set (word_sets.set_id).", "integer"),
    ("word_set_members", "root", "The Strong's number.", "Strong's number"),
    ("word_set_members", "word", "Its commonest King James spelling.", "text"),
    ("word_set_members", "position", "Its place in the set, from 0, in canonical order.", "integer"),
    ("word_set_windows", "", "The stretches of text behind each set: its units, joined where they follow one "
                             "another, each a verse range to open.", ""),
    ("word_set_windows", "set_id", "The set (word_sets.set_id).", "integer"),
    ("word_set_windows", "book", "The book.", "book name"),
    ("word_set_windows", "start_chapter", "The chapter of the stretch's first verse.", "chapter"),
    ("word_set_windows", "start_verse", "The stretch's first verse.", "verse"),
    ("word_set_windows", "end_chapter", "The chapter of its last verse.", "chapter"),
    ("word_set_windows", "end_verse", "Its last verse.", "verse"),
    ("renderings", "", "How each public domain English translation renders each Hebrew and Greek root, learned by "
                       "aligning it with the King James verse by verse (atlas_renderings.py, IBM Model 1 read both "
                       "ways) and borrowing the King James's Strong's tags.  Approximate: see "
                       "renderings_translations.share.", ""),
    ("renderings", "root", "The Strong's number.", "Strong's number"),
    ("renderings", "word", "The King James's commonest spelling of the root, for reading.", "text"),
    ("renderings", "translation", "The translation (renderings_translations.translation).", "abbreviation"),
    ("renderings", "rendering", "A word the translation uses for the root, as it spells it; '(other)' holds the "
                                "renderings used fewer than three times.", "text"),
    ("renderings", "count", "The root's tagged occurrences in the translation rendered so.", "occurrences"),
    ("renderings", "share", "count over the root's tagged occurrences in the translation; a root's rows in one "
                            "translation sum to one.", "share"),
    ("renderings", "testament", "Old for a Hebrew root, New for a Greek one.", "text"),
    ("renderings_summary", "", "One row per root and translation: its leading rendering and how many words "
                               "render it, so a translation's most varied and most uniform renderings can be "
                               "found.", ""),
    ("renderings_summary", "root", "The Strong's number.", "Strong's number"),
    ("renderings_summary", "translation", "The translation.", "abbreviation"),
    ("renderings_summary", "leading", "Its commonest rendering of the root.", "text"),
    ("renderings_summary", "share", "The leading rendering's share of the root's tagged occurrences.", "share"),
    ("renderings_summary", "distinct_renderings", "How many different renderings, as printed, render the root "
                                                  "in it.", "renderings"),
    ("renderings_summary", "renderings_folded", "The same with each rendering folded to its word by the atlas's "
                                                "spelling table and stemmer (dwelt, dwell and dwelleth one): how "
                                                "many different words render the root.", "words"),
    ("renderings_summary", "tagged", "The root's tagged occurrences in the translation.", "occurrences"),
    ("renderings_summary", "testament", "Old or New.", "text"),
    ("renderings_translations", "", "The translations aligned, with the share of their content words tagged: "
                                    "the measure of how far to trust their renderings rows.", ""),
    ("renderings_translations", "translation", "Its abbreviation.", "abbreviation"),
    ("renderings_translations", "title", "Its name.", "text"),
    ("renderings_translations", "year", "Its date (metadata.db translation_families).", "year"),
    ("renderings_translations", "verses", "The verses it has.", "verses"),
    ("renderings_translations", "words", "Its content words, the stop words set aside.", "words"),
    ("renderings_translations", "tagged", "Of them, those given a Strong's number through the alignment.", "words"),
    ("renderings_translations", "share", "tagged / words.", "share"),
    ("renderings_translations", "pairs", "Its trusted pairings with the King James's words (both directions, two "
                                         "verses, no proper name with a common word).", "pairings"),
    ("renderings_translations", "made", "When it was aligned.", "date and time"),
    ("disagreement_verses", "", "How far the English translations stand apart on each verse; sorted by "
                                "excess it is the list of cruxes.", ""),
    ("disagreement_verses", "reference", "The verse, as the King James numbers it.", "reference"),
    ("disagreement_verses", "book", "The book.", "book name"),
    ("disagreement_verses", "chapter", "The chapter.", "chapter"),
    ("disagreement_verses", "verse", "The verse.", "verse"),
    ("disagreement_verses", "mean_distance", "The mean, over every pair of translations having the verse, of one "
                                             "minus the share of content words they share (words compared "
                                             "through the alignment).",
     "0 to 1"),
    ("disagreement_verses", "excess", "The mean, over the same pairs, of each pair's distance on the verse less "
                                      "its mean distance over every verse both have: how much further apart than "
                                      "usual the translations stand here.  The cruxes are sorted by it.  Empty "
                                      "when fewer than three King James content words remain once names are "
                                      "set aside and no translation lacks the verse.",
     "distance, about -0.3 to 0.6"),
    ("disagreement_verses", "present", "Translations having the verse.", "translations"),
    ("disagreement_verses", "expected", "Translations having the book (half its verses or more).", "translations"),
    ("disagreement_verses", "missing", "The share of the translations having the book that lack the verse; a "
                                       "verse merged into a neighbour is not counted as lacking.", "share"),
    ("disagreement_verses", "merged", "Translations that hold the verse inside the verse before or after it "
                                      "(more than half of the King James verse's content words stand there): "
                                      "a difference of verse division, not an omission.", "translations"),
    ("disagreement_verses", "merged_with", "Each merged translation and the neighbour holding the verse, as "
                                           "translation>chapter:verse, separated by spaces.", "list"),
    ("disagreement_verses", "names", "The King James's distinct proper names in the verse; names are set aside "
                                     "from the distance on the rule that bars them from the alignment.", "words"),
    ("disagreement_verses", "far_a", "One of the two translations furthest apart on the verse.", "abbreviation"),
    ("disagreement_verses", "far_b", "The other.", "abbreviation"),
    ("disagreement_verses", "far_distance", "Their distance (the pair furthest beyond its usual distance).",
     "0 to 1"),
    ("disagreement_verses", "outlier", "The translation whose distances from the others on the verse stand "
                                       "furthest beyond its usual distances from them (empty with fewer than "
                                       "three translations).", "abbreviation"),
    ("disagreement_verses", "unique_words", "Content words no two translations share, separated by spaces.", "words"),
]


ATTRIBUTION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ATTRIBUTION.md")
SOURCES_HEADING = "## The sources table"
SOURCES_COLUMNS = ["name", "supplies", "license", "credit", "adapted"]


def read_attribution(path=ATTRIBUTION_PATH):
    """
    The rows of the sources table at the end of ATTRIBUTION.md: a list
    of (name, supplies, license, credit, adapted).  Only the Markdown
    table under the heading '## The sources table' is read; the prose
    above it is for people.  Returns [] when the file or the table is
    not there.  A row with the wrong number of cells, or an 'adapted'
    cell not beginning yes or no, raises ValueError naming the row, so
    a slip in the file is caught when the results are written rather
    than shipped.
    """
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    rows, inside, header_seen = [], False, False
    for number, line in enumerate(lines, 1):
        if line.strip() == SOURCES_HEADING:
            inside = True
            continue
        if not inside:
            continue
        if line.startswith("## "):
            break                                   # the next section: the table is over
        text = line.strip()
        if not text.startswith("|"):
            if rows:
                break                               # the first line after the table
            continue
        cells = [c.strip() for c in text.strip("|").split("|")]
        if not header_seen:
            header_seen = True                      # | Name | Supplies | ... |
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue                                # | --- | --- | ... |
        if len(cells) != len(SOURCES_COLUMNS):
            raise ValueError(f"{path} line {number}: {len(cells)} cells, the sources table has "
                             f"{len(SOURCES_COLUMNS)} ({', '.join(SOURCES_COLUMNS)})")
        if not cells[4].lower().startswith(("yes", "no")):
            raise ValueError(f"{path} line {number}: the 'adapted' cell must begin with yes or no")
        rows.append(tuple(cells))
    return rows


def write_sources(db, path=ATTRIBUTION_PATH):
    """
    Fill the sources table from ATTRIBUTION.md, replacing what was
    there.  When the file is missing (a copy of the program without it)
    the rows already in the table are left as they are.  Returns the
    number of rows the table holds.
    """
    db.executescript(SOURCES_SCHEMA)
    rows = read_attribution(path)
    if rows:
        db.execute("DELETE FROM sources")
        db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)",
                       [(i + 1,) + row for i, row in enumerate(rows)])
    db.commit()
    return db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]


# The theme tables a reader needs (atlas_themes.py writes them into
# atlas.db when a theme is loaded).  They are copied whole, colours,
# sections and verse texts included, so a reader draws the strip and
# lists the verses from stored rows and never works anything out.
THEME_TABLES = ("theme", "theme_verse", "theme_strip", "theme_term", "theme_problem")


def write_themes(db, atlas_path):
    """
    Copy the themes of an atlas.db into a results file (or the packed
    copy of one), replacing any copy already there.  A build made before
    themes (0.10.109) has no theme tables: then empty ones are written,
    so a reader finds the tables and says there are no themes.  Returns
    the number of themes copied.
    """
    db.commit()                          # ATTACH is refused inside an open transaction
    for table in THEME_TABLES:
        db.execute(f"DROP TABLE IF EXISTS {table}")
    copied = 0
    if atlas_path and os.path.exists(atlas_path):
        db.execute("ATTACH DATABASE ? AS atlas_src",
                   ("file:" + os.path.abspath(atlas_path).replace("\\", "/") + "?mode=ro",))
        try:
            have = {r[0] for r in db.execute("SELECT name FROM atlas_src.sqlite_master WHERE type = 'table'")}
            if all(t in have for t in THEME_TABLES):
                cols = {r[1] for r in db.execute("PRAGMA atlas_src.table_info(theme_strip)")}
                if "colour_core" in cols:          # loaded by 0.10.109's ThemeStore, with colours stored
                    for table in THEME_TABLES:
                        db.execute(f"CREATE TABLE {table} AS SELECT * FROM atlas_src.{table}")
                    copied = db.execute("SELECT COUNT(*) FROM theme").fetchone()[0]
            db.commit()
        finally:
            db.execute("DETACH DATABASE atlas_src")
    if not copied:
        # No themes to carry: the empty tables, with the columns a reader asks for
        for table in THEME_TABLES:
            db.execute(f"DROP TABLE IF EXISTS {table}")
        db.executescript(THEME_EMPTY_SCHEMA)
    db.execute("CREATE INDEX IF NOT EXISTS idx_theme_strip ON theme_strip (theme_id, position)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_theme_verse ON theme_verse (theme_id, position)")
    try:
        db.executemany("INSERT OR REPLACE INTO schema_notes VALUES (?, ?, ?, ?)",
                       [n for n in SCHEMA_NOTES if n[0] in THEME_TABLES])
    except sqlite3.Error:
        pass                             # an old results file without schema_notes
    db.commit()
    return copied


# The theme tables as they stand empty (the same columns atlas_themes.py writes)
THEME_EMPTY_SCHEMA = """
CREATE TABLE theme (theme_id TEXT, name TEXT, created TEXT, source_file TEXT, require_patterns TEXT, home TEXT,
                    home_label TEXT, cushion REAL, notes TEXT, file TEXT, loaded TEXT, build TEXT,
                    n_core INTEGER, n_borderline INTEGER, n_excluded INTEGER, n_chapters INTEGER);
CREATE TABLE theme_verse (theme_id TEXT, book TEXT, chapter INTEGER, verse INTEGER, reference TEXT,
                          verse_id INTEGER, role TEXT, reason TEXT, source_refs TEXT, texts TEXT,
                          position INTEGER, text TEXT, as_written TEXT);
CREATE TABLE theme_strip (theme_id TEXT, position INTEGER, book TEXT, chapter INTEGER, chapter_verses INTEGER,
                          in_home INTEGER, core INTEGER, all_verses INTEGER, expected_core REAL,
                          expected_all REAL, lift_core REAL, lift_all REAL, section TEXT,
                          section_start INTEGER, colour_core TEXT, colour_all TEXT);
CREATE TABLE theme_term (theme_id TEXT, strongs TEXT, root TEXT, note TEXT);
CREATE TABLE theme_problem (theme_id TEXT, reference TEXT, problem TEXT);
"""


def ensure_results_schema(db, attribution_path=ATTRIBUTION_PATH):
    """
    Create every table of the results file that is missing (the pages,
    the heat tables, sources, schema_notes), write schema_notes afresh
    and the sources from ATTRIBUTION.md, so a file written by any part
    of the program describes itself and names whose data it rests on.
    The pack's own tables (passages, the King James text) are added by
    atlas_pack.py to the packed copy only.
    """
    # Set tables written before 0.10.112 lack its columns (norm, closed,
    # folds, parent, in_order ...): they are dropped and made afresh, and the next
    # atlas_sets.py --all (or canon run) fills them again
    cols = {r[1] for r in db.execute("PRAGMA table_info(word_sets)")}
    if cols and "folds" not in cols:
        for table in ("word_set_members", "word_set_windows", "word_sets"):
            db.execute(f"DROP TABLE IF EXISTS {table}")
    # disagreement_verses written before 0.10.114 lacks merged and names;
    # atlas_renderings.py strips writes it whole, so it is made afresh
    cols = {r[1] for r in db.execute("PRAGMA table_info(disagreement_verses)")}
    if cols and "names" not in cols:
        db.execute("DROP TABLE disagreement_verses")
    # renderings_summary written before 0.10.114 lacks renderings_folded;
    # atlas_renderings.py align writes it whole, so it is made afresh
    cols = {r[1] for r in db.execute("PRAGMA table_info(renderings_summary)")}
    if cols and "renderings_folded" not in cols:
        db.execute("DROP TABLE renderings_summary")
    db.executescript(RESULTS_SCHEMA + HEAT_SCHEMA + SOURCES_SCHEMA + SETS_SCHEMA + RENDERINGS_SCHEMA
                     + SCHEMA_NOTES_SCHEMA)
    db.executemany("INSERT OR REPLACE INTO schema_notes VALUES (?, ?, ?, ?)", SCHEMA_NOTES)
    db.commit()
    write_sources(db, attribution_path)


def delete_runs(db, run_ids, vacuum=True):
    """
    Delete the given runs from a results file, with their pages and the
    pages' sections, cells, refs and footers, then (by default) VACUUM
    so the file gives the space back.  The heat rows, sources and
    schema_notes belong to no run and are left; the constellations
    (word_sets and its two tables) go with their run.  Used by
    atlas_results.py prune and by atlas_pack.py's one-run pack.
    """
    run_ids = list(run_ids)
    if not run_ids:
        return
    marks = ",".join("?" * len(run_ids))
    pages = f"SELECT page_id FROM pages WHERE run_id IN ({marks})"
    sections = f"SELECT section_id FROM sections WHERE page_id IN ({pages})"
    # The rows hang from sections, sections from pages, pages from runs:
    # removed from the bottom up
    for table in ("cells", "refs", "footers"):
        db.execute(f"DELETE FROM {table} WHERE section_id IN ({sections})", run_ids)
    db.execute(f"DELETE FROM sections WHERE page_id IN ({pages})", run_ids)
    # The constellations written under those runs (atlas_sets.py), when the file has them
    if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'word_sets'").fetchone():
        sets = f"SELECT set_id FROM word_sets WHERE run_id IN ({marks})"
        for table in ("word_set_members", "word_set_windows"):
            db.execute(f"DELETE FROM {table} WHERE set_id IN ({sets})", run_ids)
        db.execute(f"DELETE FROM word_sets WHERE run_id IN ({marks})", run_ids)
    db.execute(f"DELETE FROM pages WHERE run_id IN ({marks})", run_ids)
    db.execute(f"DELETE FROM runs WHERE run_id IN ({marks})", run_ids)
    db.commit()
    if vacuum:
        db.execute("VACUUM")


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
        run_id = cur.lastrowid
        # The build's themes go into the results file with the run: like the
        # passages they belong to no run, so the newest copy stands
        write_themes(self.db, getattr(atlas, "path", None))
        return run_id

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
