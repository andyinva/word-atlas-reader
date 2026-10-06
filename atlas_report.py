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
        self.db.executescript(RESULTS_SCHEMA)

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
