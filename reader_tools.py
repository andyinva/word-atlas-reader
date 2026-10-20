#!/usr/bin/env python3
"""
reader_tools.py  -  the Reader's Tools tab

The things a reader does now and then rather than every day, kept
behind one tab so the window opens as plain as before:

    This dataset      what the open file holds, a box for a reading
                      SQL query of one's own against it, fetching the
                      newest dataset from Word Atlas, and tidying the
                      datasets the Reader has kept
    This copy         what this copy of the Reader is made of, its
                      tests, and the guest key it carries
    Passing it on     a zip of the Reader with the open dataset, and a
                      USB drive that installs the Reader (and Word
                      Atlas, when it is on this computer) on a Windows
                      or Linux machine

Everything here is about the Reader and the dataset it has open.  The
tools that build the atlas, the databases behind it and the results
are Word Atlas's own and live on its Workbench tab, not here.

Until 0.3.9 these were menu items of the Word Atlas Workbench, a
separate window; the ones that belong to the Reader moved here.

Author: Andrew Hopkins (with Claude)
"""

import os
import sqlite3
import sys
import time
import zipfile

from PyQt6.QtCore import QProcess, QProcessEnvironment, QT_VERSION_STR, PYQT_VERSION_STR
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

import reader_guest
from reader_claude import run_sql
from reader_data import (HOME_DIR, atlas_reports_dir, forget_dataset, kept_datasets, library_dir,
                         newest_from_atlas)

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = bool(getattr(sys, "frozen", False))      # a built copy (PyInstaller): no Python to run a script with

# The files a copy of the Reader is made of; "Check this copy" says which are here
EXPECTED_FILES = ["word_atlas_reader.py", "reader_data.py", "reader_claude.py", "reader_guest.py", "reader_help.py",
                  "reader_questions.py", "reader_tools.py", "reader_credits.py", "reader_heat.py", "atlas_report.py", "atlas_results.py", "atlas_listed.py",
                  "atlas_usb.py", "atlas_usb_dialog.py", "usb_install.py"]


def make_reader_zip(reader_dir, dataset, out, guest_key=False):
    """
    Zip the Reader's program files with a dataset in its datasets
    folder (where the Reader looks first when it starts) and a
    START.txt saying how to run it: a copy to hand on by email or on a
    stick.  The credits page goes in as CREDITS.txt, written for the
    dataset in the zip, so it is the first thing anyone opening the
    zip can read.  Returns the number of files written.
    """
    import atlas_usb
    import reader_credits
    names = atlas_usb.reader_files(reader_dir, guest_key)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in names:
            z.write(os.path.join(reader_dir, name), "word_atlas_reader/" + name)
        if dataset:
            # A .wadb is a zip already: stored as it is, not squeezed again
            z.write(dataset, "word_atlas_reader/datasets/" + os.path.basename(dataset), compress_type=zipfile.ZIP_STORED)
        # The credits, saying which sources this dataset draws on
        db = reader_credits.open_dataset(dataset) if dataset else None
        z.writestr("word_atlas_reader/CREDITS.txt",
                   reader_credits.credits_text(db, os.path.basename(dataset) if dataset else ""))
        if db is not None:
            db.close()
        z.writestr("word_atlas_reader/START.txt",
                   "Word Atlas Reader\n\nInstall Python 3.10 or later and PyQt6 (pip install PyQt6), then run\n\n"
                   "    python3 word_atlas_reader.py\n\n"
                   + (f"It opens the dataset in the datasets folder ({os.path.basename(dataset)}) by itself.  "
                      if dataset else "")
                   + "README.md says the rest.\n")
    return len(names) + (1 if dataset else 0)


def columns_text(text, widest=60):
    """
    Lay tab-separated lines out in columns that line up: each column as
    wide as its longest cell (to a limit), figures to the right.  A
    line with no tab in it (a refusal, an error, a cut-off note) is
    left as it is.
    """
    rows = [line.split("\t") for line in text.split("\n")]
    table = [r for r in rows if len(r) > 1]
    if not table:
        return text
    n = max(len(r) for r in table)
    widths = [min(max(len(r[c]) for r in table if c < len(r)), widest) for c in range(n)]

    def is_number(cell):
        try:
            float(cell)
            return True
        except ValueError:
            return False

    out = []
    for r in rows:
        if len(r) == 1:
            out.append(r[0])
            continue
        cells = [(cell.rjust(widths[c]) if is_number(cell) else cell.ljust(widths[c])) for c, cell in enumerate(r)]
        out.append("  ".join(cells).rstrip())
        if r is table[0]:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


class GuestKeyDialog(QDialog):
    """Asks for a guest API key and the days it should last."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Guest key for copies given away")
        form = QFormLayout(self)
        note = QLabel("A copy of the Reader can carry a guest API key, so the person given it can ask Claude "
                      "questions for a while without a key of their own.  Make the key in a separate, capped "
                      "workspace at console.anthropic.com, and delete it there on its end date: the limit and "
                      "the deletion are the real protection (README.md, 'Giving copies away with a guest key').")
        note.setWordWrap(True)
        form.addRow(note)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-ant-...")
        form.addRow("Guest API key", self.key_edit)
        self.days = QSpinBox()
        self.days.setRange(1, 365)
        self.days.setValue(15)
        form.addRow("Days it lasts", self.days)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Write guest_key.dat")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class ToolsTab(QWidget):
    """The Tools tab: buttons down the left, what they say on the right."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window            # the ReaderWindow: its open dataset, its run, its settings
        self.process = None             # the tests, while they run
        row = QHBoxLayout(self)
        left = QVBoxLayout()
        row.addLayout(left)

        # --- this dataset ---
        group = QGroupBox("This dataset")
        g = QVBoxLayout(group)
        self.details_button = self._button(g, "Dataset details", self.dataset_details, "tools_dataset",
                                           "What the open file holds: its runs, its pages, how it was packed, "
                                           "and whether it reads back sound")
        g.addWidget(QLabel("A reading query of your own (SELECT ...):"))
        self.sql_edit = QLineEdit()
        self.sql_edit.setPlaceholderText("SELECT run_id, version, started FROM runs")
        self.sql_edit.setProperty("help", "tools_sql")
        self.sql_edit.returnPressed.connect(self.run_query)
        g.addWidget(self.sql_edit)
        self.sql_button = self._button(g, "Run the query", self.run_query, "tools_sql",
                                       "Run the query against the open dataset.  Only a SELECT runs: the dataset "
                                       "is never written to")
        self._button(g, "The tables and their columns", self.show_schema, "tools_sql",
                     "The dataset's tables, as the statements that made them, for writing a query")
        # Offered only where Word Atlas is in the folder beside the Reader's
        self.fetch_button = self._button(g, "Fetch the newest dataset from Word Atlas", self.fetch_newest,
                                         "tools_fetch",
                                         "Copy the newest .wadb in Word Atlas's reports folder into the Reader's "
                                         "own datasets folder and open it")
        self.fetch_button.setVisible(atlas_reports_dir() is not None)
        self._button(g, "Datasets kept by the Reader...", self.kept, "tools_kept",
                     "The datasets in the Reader's own folder, and removing the ones no longer wanted")
        left.addWidget(group)

        # --- this copy of the Reader ---
        group = QGroupBox("This copy of the Reader")
        g = QVBoxLayout(group)
        self._button(g, "Check this copy", self.check_copy, "tools_copy",
                     "What this copy is made of: versions, files, the guest key, where settings are kept")
        self.tests_button = self._button(g, "Run the Reader's tests", self.run_tests, "tools_tests",
                                         "python3 test_reader.py: about a minute, one line per test")
        # The tests come with the source, not with a built copy
        self.tests_button.setVisible(not FROZEN and os.path.exists(os.path.join(HERE, "test_reader.py")))
        self._button(g, "Guest key...", self.guest_key, "tools_guest",
                     "See the guest key this copy carries, or write one for copies to be given away")
        left.addWidget(group)

        # --- passing it on ---
        group = QGroupBox("Passing it on")
        g = QVBoxLayout(group)
        self.zip_button = self._button(g, "Zip the Reader with this dataset...", self.make_zip, "tools_zip",
                                       "One zip file of the program and the open dataset, to send to someone "
                                       "who has Python")
        self.zip_button.setVisible(not FROZEN)
        self._button(g, "Build or update a USB drive...", self.usb_drive, "tools_usb",
                     "A drive that installs the Reader, with its data, on a Windows or Linux computer")
        left.addWidget(group)
        left.addStretch(1)

        # --- what the tools say ---
        right = QVBoxLayout()
        row.addLayout(right, 1)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        font = QFont("DejaVu Sans Mono" if sys.platform != "win32" else "Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.output.setFont(font)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setPlaceholderText("What a tool on the left reports is printed here.")
        self.output.setProperty("help", "tools_output")
        right.addWidget(self.output, 1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.output.clear)
        foot.addWidget(clear)
        save = QPushButton("Save as text...")
        save.clicked.connect(self.save_output)
        foot.addWidget(save)
        right.addLayout(foot)

    def _button(self, layout, label, slot, help_key, tip):
        button = QPushButton(label)
        button.setToolTip(tip)
        button.setProperty("help", help_key)
        button.clicked.connect(slot)
        layout.addWidget(button)
        return button

    # --- printing -------------------------------------------------------------------------
    def say(self, text=""):
        self.output.appendPlainText(text)
        self.output.moveCursor(QTextCursor.MoveOperation.End)

    def heading(self, text):
        if self.output.toPlainText():
            self.say("")
        self.say(text)
        self.say("=" * len(text))

    def need_dataset(self):
        """The open dataset, or None after saying that one is needed."""
        if self.window.data is None:
            self.say("Open a dataset first: File > Open.")
            return None
        return self.window.data

    def save_output(self):
        text = self.output.toPlainText()
        if text:
            self.window._save_text(text, "reader_tools.txt", "Save as text")

    # --- this dataset ---------------------------------------------------------------------
    def dataset_details(self):
        data = self.need_dataset()
        if data is None:
            return
        self.heading("Dataset details")
        self.say(f"File       {data.source_path}  ({os.path.getsize(data.source_path) / 1e6:.1f} MB)")
        if data.db_path != data.source_path:
            self.say(f"Read from  {data.db_path}  ({os.path.getsize(data.db_path) / 1e6:.1f} MB, unpacked once)")
        if data.manifest:
            m = data.manifest
            self.say(f"Packed     {m.get('packed', '?')} by Word Atlas {m.get('program_version', '?')}"
                     + (f"; note: {m['note']}" if m.get("note") else ""))
        else:
            self.say("Packed     not packed: a bare results database")
        self.say("")
        self.say("Runs (a run is one pass of Word Atlas over the books):")
        for run_id, version, started, note, pages in data.runs():
            self.say(f"  run {run_id}: Word Atlas {version}, started {started}, {pages} pages"
                     + (f"  ({note})" if note else ""))
        self.say("")
        self.say("Rows in each table:")
        # The pages' tables, then those a dataset of Word Atlas 0.10.101
        # or later adds (the heat rows, the passages, the King James text,
        # schema_notes), each only when the file has it
        present = {r[0] for r in data.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in ("runs", "pages", "sections", "cells", "refs", "footers", "heat_strips", "heat_windows",
                      "heat_spots", "passages", "passage_ranges", "kjv_books", "kjv_verses", "kjv_tags",
                      "schema_notes"):
            if table not in present:
                continue
            n = data.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            self.say(f"  {table:14} {n:>12,}")
        if "heat_windows" not in present:
            self.say("  (no heat strips, passages or King James text: a dataset made before Word Atlas 0.10.101)")
        kinds = data.db.execute("SELECT kind, COUNT(*) FROM pages WHERE run_id = ? GROUP BY kind ORDER BY 2 DESC",
                                (self.window.run_id,)).fetchall()
        self.say("")
        self.say(f"Pages of run {self.window.run_id} by kind: " + ", ".join(f"{k} {n}" for k, n in kinds))
        # SQLite's own check that the file is whole (quick: it does not re-read every index)
        try:
            verdict = data.db.execute("PRAGMA quick_check").fetchone()[0]
        except sqlite3.Error as e:
            verdict = str(e)
        self.say("")
        self.say("The file reads back sound." if verdict == "ok" else f"THE FILE IS DAMAGED: {verdict}")

    def run_query(self):
        data = self.need_dataset()
        sql = self.sql_edit.text().strip()
        if data is None or not sql:
            return
        self.heading("Query")
        self.say(sql)
        self.say("")
        # The same guard the Ask Claude tab uses: one reading statement, rows and length capped
        self.say(columns_text(run_sql(data.db, sql)))

    def fetch_newest(self):
        """Bring the newest dataset Word Atlas has packed into the Reader's own folder and open it."""
        newest = newest_from_atlas()
        self.heading("Fetch the newest dataset from Word Atlas")
        if newest is None:
            self.say(f"No .wadb in {atlas_reports_dir() or 'a Word Atlas reports folder'}.")
            self.say("Pack one in Word Atlas: Workbench tab > Dossiers > Pack results.db for the Reader.")
            return
        had = {os.path.basename(p) for p, _ in kept_datasets()}
        open_now = self.window.data.source_path if self.window.data is not None else ""
        self.say(f"Newest there: {newest} ({os.path.getsize(newest) / 1e6:.1f} MB)")
        if not self.window.open_chosen(newest):
            self.say("It could not be opened.")
            return
        now = self.window.data.source_path
        if os.path.basename(newest) in had and os.path.abspath(now) == os.path.abspath(open_now):
            self.say("The Reader already has it, and it is the dataset that is open.")
        elif os.path.basename(newest) in had:
            self.say(f"The Reader had it already; it is open now: {now}")
        else:
            self.say(f"Copied into {library_dir()} and opened.")

    def kept(self):
        """List the Reader's own datasets and offer to remove those that are not open."""
        self.heading("Datasets kept by the Reader")
        files = kept_datasets()
        self.say(f"Folder: {library_dir()}")
        if not files:
            self.say("None yet.  A .wadb opened with File > Open is copied here and kept.")
            return
        open_now = os.path.abspath(self.window.data.source_path) if self.window.data is not None else ""
        others = []
        for path, size in files:
            mark = "   <- open now" if os.path.abspath(path) == open_now else ""
            self.say(f"  {os.path.basename(path)}  ({size / 1e6:.1f} MB){mark}")
            if not mark:
                others.append((path, size))
        if not others:
            self.say("Only the open dataset is kept: nothing to remove.")
            return
        total = sum(size for _, size in others) / 1e6
        names = "\n".join("    " + os.path.basename(p) for p, _ in others)
        answer = QMessageBox.question(
            self, "Datasets kept by the Reader",
            f"Remove the {len(others)} dataset(s) that are not open ({total:.0f} MB) from the Reader's folder?\n\n"
            f"{names}\n\nThe files they were copied from are not touched.")
        if answer != QMessageBox.StandardButton.Yes:
            self.say("Nothing removed.")
            return
        for path, _ in others:
            try:
                forget_dataset(path)
                self.say(f"  removed {os.path.basename(path)}")
            except (OSError, ValueError) as e:
                self.say(f"  could not remove {os.path.basename(path)}: {e}")

    def show_schema(self):
        data = self.need_dataset()
        if data is None:
            return
        self.heading("The tables and their columns")
        self.say(data.schema_text())

    # --- this copy ------------------------------------------------------------------------
    def check_copy(self):
        import word_atlas_reader
        self.heading("This copy of the Reader")
        self.say(f"Word Atlas Reader {word_atlas_reader.VERSION}" + ("  (a built copy: no Python needed)" if FROZEN else ""))
        self.say(f"Python {sys.version.split()[0]}, PyQt {PYQT_VERSION_STR}, Qt {QT_VERSION_STR}, on {sys.platform}")
        self.say(f"Program folder   {HERE}")
        self.say(f"Settings folder  {HOME_DIR}  (the API key, the histories, unpacked datasets)")
        if not FROZEN:
            missing = [n for n in EXPECTED_FILES if not os.path.exists(os.path.join(HERE, n))]
            self.say(f"Program files    {len(EXPECTED_FILES) - len(missing)} of {len(EXPECTED_FILES)} present"
                     + (": MISSING " + ", ".join(missing) if missing else ""))
        key, until = reader_guest.load()
        if key:
            self.say(f"Guest key        present, good until {until} ({reader_guest.days_left(until)} days left)")
        elif until:
            self.say(f"Guest key        ended on {until} (or the file is damaged)")
        else:
            self.say("Guest key        none in this copy")
        own = bool(self.window.settings.get("api_key"))
        self.say("Your own key     " + ("entered (File > Claude settings)" if own else "not entered"))
        data = self.window.data
        self.say("Open dataset     " + (data.describe() if data is not None else "none"))
        # The Reader's own copies of the datasets it has been given
        files = kept_datasets()
        self.say(f"Datasets kept    {len(files)} in {library_dir()}"
                 + (f" ({sum(s for _, s in files) / 1e6:.0f} MB)" if files else ""))
        for path, size in files:
            self.say(f"    {os.path.basename(path)}  ({size / 1e6:.1f} MB)")
        # Each dataset opened is also unpacked once, for a quick start
        folder = os.path.join(HOME_DIR, "datasets")
        if os.path.isdir(folder):
            sizes = []
            for name in sorted(os.listdir(folder)):
                db = os.path.join(folder, name, "results.db")
                if os.path.exists(db):
                    sizes.append((name, os.path.getsize(db)))
            if sizes:
                self.say(f"Unpacked for use in {folder}:")
                for name, size in sizes:
                    self.say(f"    {name}  ({size / 1e6:.0f} MB)")
                self.say("    ('Datasets kept by the Reader' removes a dataset and its unpacked copy together)")

    def run_tests(self):
        """Run test_reader.py as its own process, its lines arriving here as they are printed."""
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.information(self, "Tests", "The tests are still running.")
            return
        self.heading(f"python3 test_reader.py   ({time.strftime('%H:%M:%S')})")
        self.tests_button.setEnabled(False)
        self.process = QProcess(self)
        self.process.setWorkingDirectory(HERE)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # This program's own environment, plus unbuffered output so the lines arrive as they are printed
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(env)
        self.process.readyReadStandardOutput.connect(self._tests_output)
        self.process.finished.connect(self._tests_finished)
        self.process.errorOccurred.connect(lambda err: self.say(f"(could not run: {err.name})"))
        python = sys.executable
        # Under pythonw.exe (no terminal) the tests would have nowhere to print
        if os.path.basename(python).lower() == "pythonw.exe":
            python = os.path.join(os.path.dirname(python), "python.exe")
        self.process.start(python, ["test_reader.py"])

    def _tests_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.MoveOperation.End)

    def _tests_finished(self, code, status):
        self._tests_output()
        self.say("The tests passed." if code == 0 else f"The tests ended with code {code}: see the FAIL lines above.")
        self.tests_button.setEnabled(True)

    def guest_key(self):
        """Say what guest key this copy carries, and offer to write a new one."""
        key, until = reader_guest.load()
        if key:
            state = f"This copy carries a guest key good until {until} ({reader_guest.days_left(until)} days left)."
        elif until:
            state = f"This copy's guest key ended on {until}."
        else:
            state = "This copy carries no guest key."
        box = QMessageBox(self)
        box.setWindowTitle("Guest key")
        box.setText(state)
        box.setInformativeText("A guest key lets a copy given away ask Claude questions until its end date.  "
                               "The key itself is never shown.")
        make = box.addButton("Write a new one...", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is not make:
            return
        dialog = GuestKeyDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        key = dialog.key_edit.text().strip()
        if not key.startswith("sk-ant-"):
            QMessageBox.warning(self, "Guest key", "That does not look like an Anthropic API key (they begin sk-ant-).")
            return
        try:
            until = reader_guest.make(key, dialog.days.value())
        except OSError as e:
            QMessageBox.warning(self, "Guest key", f"guest_key.dat could not be written: {e}")
            return
        self.heading("Guest key")
        self.say(f"Wrote {reader_guest.GUEST_PATH}, good until {until}.")
        self.say("Remember to delete the key in the console on that day.")
        self.say("It goes into a zip or onto a USB drive only when its box is ticked there.")

    # --- passing it on --------------------------------------------------------------------
    def open_wadb(self):
        """The open dataset when it is a packed .wadb (the kind worth handing on), else None."""
        data = self.window.data
        if data is not None and data.source_path.lower().endswith(".wadb"):
            return data.source_path
        return None

    def make_zip(self):
        dataset = self.open_wadb()
        if self.window.data is not None and dataset is None:
            QMessageBox.information(self, "Zip the Reader", "The open file is a bare results.db, not a packed "
                                    ".wadb; the zip will carry the program without a dataset.")
        guest = False
        if os.path.exists(reader_guest.GUEST_PATH):
            guest = QMessageBox.question(self, "Zip the Reader", "Include the guest key (guest_key.dat) in the zip?") \
                == QMessageBox.StandardButton.Yes
        import word_atlas_reader
        suggested = os.path.join(os.path.expanduser("~"),
                                 f"word_atlas_reader_{word_atlas_reader.VERSION}_{time.strftime('%Y-%m-%d')}.zip")
        out, _ = QFileDialog.getSaveFileName(self, "Zip the Reader with this dataset", suggested, "Zip files (*.zip)")
        if not out:
            return
        try:
            n = make_reader_zip(HERE, dataset, out, guest)
        except OSError as e:
            QMessageBox.warning(self, "Zip the Reader", f"The zip could not be written: {e}")
            return
        self.heading("Zip the Reader")
        self.say(f"Wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB): {n} files"
                 + (f", with {os.path.basename(dataset)}" if dataset else ", no dataset")
                 + (", with the guest key" if guest else "") + ".")
        self.say("Whoever gets it unzips it, installs Python and PyQt6, and runs word_atlas_reader.py (START.txt says how).")

    def usb_drive(self):
        """The USB drive window, offering the dataset that is open."""
        try:
            from atlas_usb_dialog import UsbDialog
        except ImportError as e:
            QMessageBox.warning(self, "USB drive", f"atlas_usb_dialog.py could not be loaded: {e}")
            return
        UsbDialog(self, dataset=self.open_wadb()).exec()

    def stop(self):
        """Called as the window closes: no test run is left behind."""
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(2000)
