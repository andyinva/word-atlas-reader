#!/usr/bin/env python3
"""
reader_data.py  -  the dataset behind the Word Atlas Reader

The Reader opens one file and needs nothing else: either a results.db
written by the main Word Atlas program (atlas_query.py dossier ...
--results), or a .wadb, which is that same database zipped together
with a small manifest.  This module turns the file into Report objects
that the shared text layout (atlas_report.render) prints exactly as the
main program prints them, and answers the Reader's other questions:
which runs the file holds, which pages a run holds, where a word
appears, and what a run's build line was.

Nothing here touches the Bible build.  The only imports are the
standard library and atlas_report, which is itself standard library
only, so the Reader can be handed to someone who has never installed
the main program.

    data = Dataset.open("word_atlas_0.10.72.wadb")
    for run in data.runs(): ...
    report = data.report(page_id)
    text = render(report, atlas=data.build_of(run_id))

The Reader keeps its own copy of every dataset it is given (0.3.10):
keep_dataset() copies a .wadb into the datasets folder beside the
program, and the Reader opens that copy.  The file it was given can
then be moved, renamed or replaced, on a drive that is unplugged or in
the main program's reports folder, and the Reader still has its data.
"""

import json
import os
import re
import shutil
import sqlite3
import sys
import zipfile

from atlas_report import Report, Section

# Where the Reader keeps its unpacked datasets and its settings.  One
# folder in the home directory works the same on Ubuntu and Windows.
# WORD_ATLAS_READER_HOME names another folder instead, and then the
# Reader keeps everything under it and looks nowhere else: the tests
# set it to a throwaway folder, so a test run leaves the real settings
# (the last file opened, the histories, the API key) and the real
# datasets exactly as they were.
ISOLATED = bool(os.environ.get("WORD_ATLAS_READER_HOME"))
HOME_DIR = os.environ.get("WORD_ATLAS_READER_HOME") or os.path.join(os.path.expanduser("~"), ".word_atlas_reader")
DATASET_DIR = os.path.join(HOME_DIR, "datasets")
SETTINGS_PATH = os.path.join(HOME_DIR, "settings.json")

# The folder the program is in: this file's folder, or, for a built
# copy (PyInstaller), the folder its program file is in
PROGRAM_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
# The sample dataset the repository carries for the tests.  It is never
# what the Reader opens of its own accord.
SAMPLE_DIR = os.path.join(PROGRAM_DIR, "sample")

# The kinds of heat strip, in the order the heat reports draw them, and
# the five measures in their own order (atlas_heat.py's MEASURES)
HEAT_KINDS = ["measure", "feeling", "feeling family", "word list", "names", "context", "voice"]
HEAT_MEASURE_ORDER = ["density", "variety", "rare", "hammer", "action", "feeling",
                      "emotion", "senses", "body", "violence", "sacred", "wealth", "harlotry",
                      "nations", "persons", "home", "numbers"]

# The names inside a .wadb archive
DB_MEMBER = "results.db"
MANIFEST_MEMBER = "manifest.json"


# ---------------------------------------------------------------------------
# Settings: a small JSON file in the Reader's home folder
# ---------------------------------------------------------------------------

def load_settings():
    """The saved settings as a dict, empty when there are none yet."""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    """Write the settings back; the folder is made on the first save."""
    os.makedirs(HOME_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


# ---------------------------------------------------------------------------
# The Reader's own datasets folder
# ---------------------------------------------------------------------------

def library_dir():
    """
    The folder the Reader keeps its own copies of datasets in:
    datasets/ beside the program.  Where the program's folder cannot
    be written to (a copy installed for all users, a read-only drive)
    it is library/ in the Reader's home folder instead, as it is while
    the tests run.  The folder is made if it is not there.
    """
    folder = os.path.join(PROGRAM_DIR, "datasets")
    try:
        if not ISOLATED:
            os.makedirs(folder, exist_ok=True)
            if os.access(folder, os.W_OK):
                return folder
    except OSError:
        pass
    folder = os.path.join(HOME_DIR, "library")
    os.makedirs(folder, exist_ok=True)
    return folder


def in_library(path):
    """True when a file is already one of the Reader's own copies."""
    return os.path.abspath(os.path.dirname(path)) == os.path.abspath(library_dir())


def is_sample(path):
    """True when a file is in the sample folder the tests use."""
    return os.path.abspath(os.path.dirname(path)) == os.path.abspath(SAMPLE_DIR)


def keep_dataset(path):
    """
    Copy a .wadb into the Reader's datasets folder and return the
    copy's path, which is the one to open.  Returns (path, copied):
    copied is False when nothing had to be copied, because the file is
    already there (the same size, and no older than the one given), is
    already in the folder, or is not a .wadb at all.  A bare results.db
    is not copied: it is the main program's working file, opened where
    it stands.

    The copy keeps the date of the file it was made from, so a dataset
    already unpacked once is not unpacked again for being copied.
    """
    if not zipfile.is_zipfile(path) or in_library(path):
        return path, False
    target = os.path.join(library_dir(), os.path.basename(path))
    if os.path.exists(target) and os.path.getsize(target) == os.path.getsize(path) \
            and os.path.getmtime(target) >= os.path.getmtime(path) - 2:
        return target, False
    part = target + ".part"
    try:
        shutil.copy2(path, part)          # copy2: the contents and the date
        os.replace(part, target)
    except OSError:
        if os.path.exists(part):
            os.remove(part)
        raise
    return target, True


def kept_datasets():
    """The Reader's own copies, newest first: [(path, size in bytes)]."""
    folder = library_dir()
    files = [os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(".wadb")]
    files.sort(key=os.path.getmtime, reverse=True)
    return [(f, os.path.getsize(f)) for f in files]


def atlas_reports_dir():
    """
    The reports folder of the main program, when Word Atlas is in the
    folder beside the Reader's (as it is on the computer the datasets
    are made on): where atlas_pack.py writes each new .wadb.  None
    anywhere else, and while the tests run.
    """
    folder = os.path.join(os.path.dirname(PROGRAM_DIR), "word_atlas", "reports")
    return folder if os.path.isdir(folder) and not ISOLATED else None


def newest_from_atlas():
    """The newest .wadb in Word Atlas's reports folder, or None."""
    folder = atlas_reports_dir()
    if not folder:
        return None
    files = [os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(".wadb")]
    return max(files, key=os.path.getmtime) if files else None


def forget_dataset(path):
    """Delete one of the Reader's own copies and the unpacked database made from it."""
    if not in_library(path):
        raise ValueError(f"{path} is not in the Reader's datasets folder")
    os.remove(path)
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.splitext(os.path.basename(path))[0])
    shutil.rmtree(os.path.join(DATASET_DIR, base), ignore_errors=True)


# ---------------------------------------------------------------------------
# A build line stand-in: render() asks the atlas for build_line(), and
# the Reader has no atlas, only the line the run stored
# ---------------------------------------------------------------------------

class BuildLine:
    """Carries a run's stored build line to atlas_report.render."""

    def __init__(self, line):
        self.line = line

    def build_line(self):
        return self.line


# ---------------------------------------------------------------------------
# The dataset
# ---------------------------------------------------------------------------

class Dataset:
    """
    One results database, opened read-only.  open() takes a .db or a
    .wadb; a .wadb is unpacked into the Reader's datasets folder the
    first time and reused after that, so a large archive is unzipped
    once, not on every start.
    """

    def __init__(self, db_path, source_path, manifest=None):
        self.db_path = db_path          # the SQLite file actually opened
        self.source_path = source_path  # the file the user chose
        self.manifest = manifest or {}  # from the .wadb, when there was one
        # mode=ro: the Reader never writes to a dataset, and a read-only
        # connection makes that a promise the database itself keeps
        uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
        self.db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._check_schema()

    # --- opening -----------------------------------------------------------
    @classmethod
    def open(cls, path):
        """Open a .db directly, or unpack a .wadb and open what is inside."""
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if zipfile.is_zipfile(path):
            db_path, manifest = cls._unpack(path)
            return cls(db_path, path, manifest)
        return cls(path, path)

    @staticmethod
    def _unpack(archive_path):
        """
        Unpack results.db (and the manifest) from a .wadb into a folder
        named after the archive.  The archive's size and modification
        time are recorded beside the unpacked copy, so a changed archive
        is unpacked again and an unchanged one is not.
        """
        stamp = f"{os.path.getsize(archive_path)}:{int(os.path.getmtime(archive_path))}"
        base = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.splitext(os.path.basename(archive_path))[0])
        folder = os.path.join(DATASET_DIR, base)
        stamp_path = os.path.join(folder, "source.stamp")
        db_path = os.path.join(folder, DB_MEMBER)
        manifest = {}
        fresh = os.path.exists(db_path) and os.path.exists(stamp_path) \
            and open(stamp_path, encoding="utf-8").read().strip() == stamp
        if not fresh:
            if os.path.isdir(folder):
                shutil.rmtree(folder)
            os.makedirs(folder, exist_ok=True)
            with zipfile.ZipFile(archive_path) as z:
                names = z.namelist()
                if DB_MEMBER not in names:
                    raise ValueError(f"{archive_path} holds no {DB_MEMBER}: not a Word Atlas dataset")
                z.extract(DB_MEMBER, folder)
                if MANIFEST_MEMBER in names:
                    z.extract(MANIFEST_MEMBER, folder)
            with open(stamp_path, "w", encoding="utf-8") as f:
                f.write(stamp)
        manifest_path = os.path.join(folder, MANIFEST_MEMBER)
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)
            except ValueError:
                manifest = {}
        return db_path, manifest

    def _check_schema(self):
        """Refuse a SQLite file that is not a Word Atlas results database."""
        names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        needed = {"runs", "pages", "sections", "cells", "refs", "footers"}
        if not needed <= names:
            missing = ", ".join(sorted(needed - names))
            raise ValueError(f"{self.db_path} is not a Word Atlas results database (missing tables: {missing})")

    def close(self):
        self.db.close()

    # --- runs and pages ---------------------------------------------------
    def runs(self):
        """Every run, newest first: (run_id, version, started, note, pages)."""
        out = []
        for r in self.db.execute("SELECT * FROM runs ORDER BY run_id DESC"):
            n = self.db.execute("SELECT COUNT(*) FROM pages WHERE run_id = ?", (r["run_id"],)).fetchone()[0]
            out.append((r["run_id"], r["version"], r["started"], r["note"], n))
        return out

    def latest_run(self):
        row = self.db.execute("SELECT MAX(run_id) FROM runs").fetchone()
        return row[0]

    def build_of(self, run_id):
        """The run's build line, wrapped for render()."""
        row = self.db.execute("SELECT build FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return BuildLine(row["build"] if row else "")

    def pages(self, run_id):
        """The run's pages in the order they were written: (page_id, kind, title)."""
        return [(r["page_id"], r["kind"], r["title"])
                for r in self.db.execute("SELECT page_id, kind, title FROM pages WHERE run_id = ? ORDER BY page_id",
                                         (run_id,))]

    def page_by_title(self, run_id, title):
        row = self.db.execute("SELECT page_id FROM pages WHERE run_id = ? AND title = ?", (run_id, title)).fetchone()
        return row["page_id"] if row else None

    # --- a page back as a Report ------------------------------------------
    def report(self, page_id):
        """
        Rebuild the Report the main program wrote, so atlas_report.render
        lays it out the same way: every cell as the text the page
        printed, with the cell's number kept beside it for sorting.
        """
        p = self.db.execute("SELECT * FROM pages WHERE page_id = ?", (page_id,)).fetchone()
        if p is None:
            raise KeyError(page_id)
        report = Report(p["name"], p["title"])
        report.notes = p["notes"].split("\n") if p["notes"] else []
        report.page_id = page_id
        report.kind = p["kind"]
        # A Section page that spans books (the cross-book pages) lists
        # its sections at the head like a book page; the stored page
        # cannot say which it was, so every Section page with more than
        # a handful of tables gets the list, which costs a few lines
        # and spares the reader a guess
        for s in self.db.execute("SELECT * FROM sections WHERE page_id = ? ORDER BY position", (page_id,)):
            columns = s["columns"].split("\t") if s["columns"] else []
            sec = Section(s["title"], columns, s["note"], s["kind"])
            sec.section_id = s["section_id"]
            rows = [[""] * len(columns) for _ in range(s["n_rows"])]
            # Every cell keeps the text the page printed ("0.50" stays
            # "0.50", not 0.5), so the Reader's page matches the main
            # program's file to the character; the number beside it,
            # when the cell had one, goes to cell_numbers for sorting
            sec.cell_numbers = {}
            for c in self.db.execute("SELECT row, col, value, number FROM cells WHERE section_id = ?",
                                     (s["section_id"],)):
                if c["col"] >= len(columns) or c["row"] >= len(rows):
                    continue
                rows[c["row"]][c["col"]] = c["value"]
                if c["number"] is not None:
                    sec.cell_numbers[(c["row"], c["col"])] = c["number"]
            refs = [[] for _ in rows]
            for r in self.db.execute("SELECT row, reference FROM refs WHERE section_id = ? ORDER BY rowid",
                                     (s["section_id"],)):
                if r["row"] < len(refs):
                    refs[r["row"]].append(r["reference"])
            for row, row_refs in zip(rows, refs):
                sec.add(row, row_refs)
            sec.footer = [f["text"] for f in self.db.execute(
                "SELECT text FROM footers WHERE section_id = ? ORDER BY position", (s["section_id"],))]
            report.sections.append(sec)
        report.list_sections = p["kind"] == "Section" and len(report.sections) > 6
        return report

    # --- search --------------------------------------------------------------
    def search(self, run_id, text, limit=500):
        """
        Every cell in the run whose text contains the search text (case
        does not matter), plus the section titles and footers that do:
        (page_id, page title, section number, row, column, value).
        A footer hit has column 'footer' and a title hit column 'title'.
        """
        like = f"%{text}%"
        hits = []
        for r in self.db.execute(
                "SELECT p.page_id, p.title AS page, s.number, c.row, c.column, c.value "
                "FROM cells c JOIN sections s USING (section_id) JOIN pages p USING (page_id) "
                "WHERE p.run_id = ? AND c.value LIKE ? COLLATE NOCASE ORDER BY p.page_id, s.position, c.row, c.col "
                "LIMIT ?", (run_id, like, limit)):
            hits.append((r["page_id"], r["page"], r["number"], r["row"], r["column"], r["value"]))
        for r in self.db.execute(
                "SELECT p.page_id, p.title AS page, s.number, s.title FROM sections s JOIN pages p USING (page_id) "
                "WHERE p.run_id = ? AND s.title LIKE ? COLLATE NOCASE ORDER BY p.page_id, s.position", (run_id, like)):
            hits.append((r["page_id"], r["page"], r["number"], -1, "title", r["title"]))
        for r in self.db.execute(
                "SELECT p.page_id, p.title AS page, s.number, f.text FROM footers f JOIN sections s USING (section_id) "
                "JOIN pages p USING (page_id) WHERE p.run_id = ? AND f.text LIKE ? COLLATE NOCASE "
                "ORDER BY p.page_id, s.position, f.position", (run_id, like)):
            hits.append((r["page_id"], r["page"], r["number"], -1, "footer", r["text"]))
        return hits

    # --- the heat strips, the passages and the King James text (0.10.101) -----
    # A dataset packed by Word Atlas 0.10.101 or later holds the heat
    # tables (heat_strips, heat_windows, heat_spots), the named passages
    # and the King James text with its tags.  An older one holds none of
    # them: every method below then answers empty, and has_heat() and
    # the others say so, so the window can say why the Heat tab is bare.

    def _has(self, *tables):
        names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return all(t in names for t in tables)

    def has_heat(self):
        """True when the file holds heat rows."""
        if not self._has("heat_strips", "heat_windows", "heat_spots"):
            return False
        return self.db.execute("SELECT 1 FROM heat_windows LIMIT 1").fetchone() is not None

    def has_passages(self):
        return self._has("passages", "passage_ranges")

    def has_kjv(self):
        return self._has("kjv_books", "kjv_verses", "kjv_tags")

    # --- the sources (0.10.103) ------------------------------------------
    # A dataset packed by Word Atlas 0.10.103 or later carries a sources
    # table: the outside datasets its figures rest on, the license of
    # each and the credit line it asks for, copied from ATTRIBUTION.md.
    SOURCE_COLUMNS = ("name", "supplies", "license", "credit", "adapted")

    def has_sources(self):
        return self._has("sources")

    def sources(self):
        """The sources table's rows as dicts in its order, or [] for a dataset packed before 0.10.103."""
        if not self.has_sources():
            return []
        rows = self.db.execute("SELECT name, supplies, license, credit, adapted FROM sources ORDER BY position")
        return [dict(zip(self.SOURCE_COLUMNS, row)) for row in rows]

    def heat_books(self):
        """The books with heat rows, in Bible order when the file holds the King James books."""
        if not self.has_heat():
            return []
        books = [r[0] for r in self.db.execute("SELECT DISTINCT book FROM heat_windows")]
        if self.has_kjv():
            order = {r[0]: r[1] for r in self.db.execute("SELECT name, book_num FROM kjv_books")}
            return sorted(books, key=lambda b: (order.get(b, 999), b))
        return sorted(books)

    def heat_views(self, book):
        """The ways a book's strips were measured: [(scale, norm, window size)], the usual one first."""
        rows = [tuple(r) for r in self.db.execute(
            "SELECT DISTINCT scale, norm, window_size FROM heat_windows WHERE book = ?", (book,))]
        first = {("z", "bible"): 0, ("percentile", "book"): 1, ("g2", "bible"): 2, ("g2", "group"): 3}
        return sorted(rows, key=lambda v: (first.get(v[:2], 9), v))

    def heat_strips(self, book, view):
        """
        The strips drawn for a book in one view, in the order the heat
        reports draw them: [(strip, kind, description, roots)].
        """
        scale, norm, size = view
        names = [r[0] for r in self.db.execute(
            "SELECT DISTINCT strip FROM heat_windows WHERE book = ? AND scale = ? AND norm = ? AND window_size = ?",
            (book, scale, norm, size))]
        testament = None
        if self.has_kjv():
            row = self.db.execute("SELECT testament FROM kjv_books WHERE name = ?", (book,)).fetchone()
            testament = row[0] if row else None
        info = {}
        for strip, tst, kind, description, roots in self.db.execute(
                "SELECT strip, testament, kind, description, roots FROM heat_strips"):
            if strip in names and (strip not in info or tst == testament):
                info[strip] = (kind, description, roots)
        kinds = HEAT_KINDS
        measures = HEAT_MEASURE_ORDER

        def key(strip):
            kind = info.get(strip, ("",))[0]
            within = measures.index(strip) if strip in measures else len(measures)
            return (kinds.index(kind) if kind in kinds else len(kinds), within, strip.lower())
        return [(s,) + info.get(s, ("", "", "")) for s in sorted(names, key=key)]

    def heat_windows(self, book, view, strip):
        """[(position, start chapter, start verse, end chapter, end verse, z)] in book order."""
        scale, norm, size = view
        return [tuple(r) for r in self.db.execute(
            "SELECT position, start_chapter, start_verse, end_chapter, end_verse, z FROM heat_windows "
            "WHERE book = ? AND scale = ? AND norm = ? AND window_size = ? AND strip = ? ORDER BY position",
            (book, scale, norm, size, strip))]

    def heat_spots(self, book, view, strip, line="spot"):
        """
        The spots of one strip at one line ('spot' or 'near'), hot first
        then cool, in book order: [dict of the heat_spots columns].
        """
        scale, norm, size = view
        cur = self.db.execute(
            "SELECT * FROM heat_spots WHERE book = ? AND scale = ? AND norm = ? AND window_size = ? AND strip = ? "
            "AND line = ? ORDER BY hot DESC, start_chapter, start_verse", (book, scale, norm, size, strip, line))
        return [dict(r) for r in cur]

    def passages(self):
        """The named passages: [(passage_id, name, description)]."""
        if not self.has_passages():
            return []
        return [tuple(r) for r in self.db.execute("SELECT passage_id, name, description FROM passages ORDER BY name")]

    def passage_ranges(self, passage_id):
        """[(book name, chapter start, verse start, chapter end, verse end)] of one passage."""
        names = self.book_names()
        return [(names.get(r[0], str(r[0])),) + tuple(r)[1:] for r in self.db.execute(
            "SELECT book_num, chapter_start, verse_start, chapter_end, verse_end FROM passage_ranges "
            "WHERE passage_id = ? ORDER BY rowid", (passage_id,))]

    def book_names(self):
        """{book number: name} from the King James books, empty without them."""
        if not self.has_kjv():
            return {}
        return {r[0]: r[1] for r in self.db.execute("SELECT book_num, name FROM kjv_books")}

    def book_number(self, name):
        """The book's number (1 Genesis ... 66 Revelation), by name or abbreviation, any case; None if unknown."""
        if not self.has_kjv():
            return None
        key = name.strip().lower().replace(" ", "")
        for num, book, abbr in self.db.execute("SELECT book_num, name, abbreviation FROM kjv_books"):
            if key in (book.lower().replace(" ", ""), (abbr or "").lower().replace(" ", "")):
                return num
        for num, book in self.db.execute("SELECT book_num, name FROM kjv_books ORDER BY book_num"):
            if book.lower().replace(" ", "").startswith(key):
                return num
        return None

    def kjv_range(self, book_num, c1, v1, c2, v2, tags=False):
        """
        The King James verses from c1:v1 to c2:v2 of one book:
        [(chapter, verse, text, tags)], tags a list of (word, Strong's
        number, morphology) when asked for, else [].
        """
        if not self.has_kjv():
            return []
        rows = self.db.execute(
            "SELECT verse_id, chapter, verse, text FROM kjv_verses WHERE book_num = ? "
            "AND (chapter * 1000 + verse) BETWEEN ? AND ? ORDER BY chapter, verse",
            (book_num, c1 * 1000 + v1, c2 * 1000 + v2)).fetchall()
        out = []
        for vid, ch, v, text in rows:
            t = [tuple(r) for r in self.db.execute(
                "SELECT word, strongs, morphology FROM kjv_tags WHERE verse_id = ? ORDER BY position", (vid,))] \
                if tags else []
            out.append((ch, v, text, t))
        return out

    # --- the themes (Word Atlas 0.10.109) ---------------------------------
    # A theme is a hand-made set of verses (land and inheritance).  The
    # main program worked out everything about it when it loaded the
    # theme: every verse with its role and text, and per chapter the
    # counts, the expected counts, the lift and the colour to draw.  The
    # Reader only reads those rows; nothing here counts or divides.

    def has_themes(self):
        """True when the file holds at least one theme."""
        if not self._has("theme", "theme_verse", "theme_strip"):
            return False
        return self.db.execute("SELECT 1 FROM theme LIMIT 1").fetchone() is not None

    def themes(self):
        """The themes, by name: [dict of the theme table's columns]."""
        if not self.has_themes():
            return []
        return [dict(r) for r in self.db.execute("SELECT * FROM theme ORDER BY name")]

    def theme_strip(self, theme_id):
        """The strip of one theme, one dict per chapter in canonical order, as stored."""
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM theme_strip WHERE theme_id = ? ORDER BY position", (theme_id,))]

    def theme_verses(self, theme_id, book=None, chapter=None):
        """The verses of one theme in canonical order (of one chapter when asked), as stored."""
        sql = "SELECT * FROM theme_verse WHERE theme_id = ?"
        args = [theme_id]
        if book is not None:
            sql += " AND book = ? AND chapter = ?"
            args += [book, chapter]
        return [dict(r) for r in self.db.execute(sql + " ORDER BY position", args)]

    def theme_problems(self, theme_id):
        """[(reference, problem)] the main program could not place."""
        if not self._has("theme_problem"):
            return []
        return [tuple(r) for r in self.db.execute(
            "SELECT reference, problem FROM theme_problem WHERE theme_id = ?", (theme_id,))]

    def theme_terms(self, theme_id):
        """[(Strong's number, root, note)] of one theme's companion terms."""
        if not self._has("theme_term"):
            return []
        return [tuple(r) for r in self.db.execute(
            "SELECT strongs, root, note FROM theme_term WHERE theme_id = ? ORDER BY strongs, root", (theme_id,))]

    # --- the constellations (Word Atlas 0.10.112) ---------------------------
    # Sets of two to five roots that gather in one stretch of text far more
    # often than chance, found by the main program's atlas_sets.py and
    # written with every figure the Constellations tab shows: support,
    # places, lift, keyness, kind, in-order share, closed, folds, the closed
    # set a smaller one folds under, span and the inclusio mark.  The Reader
    # only selects rows; nothing is counted here.
    SET_COLUMNS = ("set_id", "scope", "norm", "size", "roots", "words", "support", "stretches", "expected", "lift",
                   "keyness", "kind", "in_order", "closed", "folds", "parent", "span", "inclusio")

    def has_sets(self):
        """True when the file holds constellation rows (a dataset packed by Word Atlas 0.10.112 or later)."""
        if not self._has("word_sets", "word_set_members", "word_set_windows"):
            return False
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(word_sets)")}
        if "folds" not in cols:
            return False                     # written by 0.10.110 or 0.10.111, before the Reader's columns
        return self.db.execute("SELECT 1 FROM word_sets LIMIT 1").fetchone() is not None

    def set_run(self, run_id=None):
        """The run whose sets to show: run_id when it has sets, else the newest run that has them."""
        if run_id is not None and self.db.execute("SELECT 1 FROM word_sets WHERE run_id IS ? LIMIT 1",
                                                  (run_id,)).fetchone():
            return run_id
        row = self.db.execute("SELECT run_id FROM word_sets ORDER BY run_id DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def set_scopes(self, run_id):
        """The scopes with sets in a run: Old and New first, then the books in Bible order."""
        scopes = [r[0] for r in self.db.execute("SELECT DISTINCT scope FROM word_sets WHERE run_id IS ?", (run_id,))]
        order = {}
        if self.has_kjv():
            order = {r[0]: r[1] for r in self.db.execute("SELECT name, book_num FROM kjv_books")}
        first = {"Old": -2, "New": -1}
        return sorted(scopes, key=lambda s: (first.get(s, order.get(s, 999)), s))

    def set_norms(self, run_id, scope):
        """The norms a scope's sets were measured against: book first, then testament."""
        norms = [r[0] for r in self.db.execute("SELECT DISTINCT norm FROM word_sets WHERE run_id IS ? AND scope = ?",
                                               (run_id, scope))]
        return sorted(norms, key=lambda n: (n != "book", n))

    def sets(self, run_id, scope, norm, kind=None, size=None, closed_only=True, root=None, limit=500):
        """
        The sets of one scope and norm, strongest first, filtered as asked:
        ([dict per set], how many the filter matched).  root is a Strong's
        number (H1285) or a word (covenant), matched against the stored members.
        """
        where = ["run_id IS ?", "scope = ?", "norm = ?"]
        args = [run_id, scope, norm]
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if size:
            where.append("size = ?")
            args.append(int(size))
        if closed_only:
            where.append("closed = 1")
        if root:
            where.append("set_id IN (SELECT set_id FROM word_set_members WHERE upper(root) = upper(?) "
                         "OR lower(word) = lower(?))")
            args += [root.strip(), root.strip()]
        sql = " AND ".join(where)
        total = self.db.execute(f"SELECT COUNT(*) FROM word_sets WHERE {sql}", args).fetchone()[0]
        cols = ", ".join(self.SET_COLUMNS)
        rows = self.db.execute(f"SELECT {cols} FROM word_sets WHERE {sql} ORDER BY keyness DESC, set_id LIMIT ?",
                               args + [limit]).fetchall()
        return [dict(zip(self.SET_COLUMNS, r)) for r in rows], total

    def set_windows(self, set_id):
        """The places of one set: [(book, start chapter, start verse, end chapter, end verse)] in order."""
        return [tuple(r) for r in self.db.execute(
            "SELECT book, start_chapter, start_verse, end_chapter, end_verse FROM word_set_windows "
            "WHERE set_id = ? ORDER BY rowid", (set_id,))]

    def set_folded(self, set_id):
        """The smaller sets folded under a closed set, largest first: [dict]."""
        cols = ", ".join(self.SET_COLUMNS)
        return [dict(zip(self.SET_COLUMNS, r)) for r in self.db.execute(
            f"SELECT {cols} FROM word_sets WHERE parent = ? ORDER BY size DESC, keyness DESC", (set_id,))]

    def scope_verses(self, scope):
        """
        The verses of a scope in Bible order, for the strip under the grid:
        [(book, chapter, verse)].  A book's own verses, or every book of a
        testament ('Old', 'New').  Empty without the King James text.
        """
        if not self.has_kjv():
            return []
        if scope in ("Old", "New"):
            books = [r[0] for r in self.db.execute("SELECT book_num FROM kjv_books WHERE testament = ? "
                                                   "ORDER BY book_num", (scope,))]
        else:
            num = self.book_number(scope)
            books = [num] if num else []
        names = self.book_names()
        out = []
        for num in books:
            out.extend((names[num], c, v) for c, v in self.db.execute(
                "SELECT chapter, verse FROM kjv_verses WHERE book_num = ? ORDER BY chapter, verse", (num,)))
        return out

    # --- the schema, as words, for the Claude panel ----------------------------
    def schema_text(self):
        """The CREATE statements of the database, for a question-answerer that writes SQL."""
        return "\n\n".join(r[0] for r in self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL"))

    def describe(self):
        """A few lines about the open file for the window's status bar."""
        runs = self.runs()
        pages = sum(r[4] for r in runs)
        made = self.manifest.get("packed", "")
        tail = f", packed {made}" if made else ""
        heat = "" if self.has_heat() else ", no heat strips (made before Word Atlas 0.10.101)"
        return f"{os.path.basename(self.source_path)}: {len(runs)} run(s), {pages} pages{tail}{heat}"
