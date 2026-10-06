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
"""

import json
import os
import re
import shutil
import sqlite3
import zipfile

from atlas_report import Report, Section

# Where the Reader keeps its unpacked datasets and its settings.  One
# folder in the home directory works the same on Ubuntu and Windows.
HOME_DIR = os.path.join(os.path.expanduser("~"), ".word_atlas_reader")
DATASET_DIR = os.path.join(HOME_DIR, "datasets")
SETTINGS_PATH = os.path.join(HOME_DIR, "settings.json")

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
        return f"{os.path.basename(self.source_path)}: {len(runs)} run(s), {pages} pages{tail}"
