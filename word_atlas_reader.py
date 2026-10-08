#!/usr/bin/env python3
"""
word_atlas_reader.py  -  a viewer for Word Atlas results

For a reader who has the dataset and not the program.  The Reader
opens one file, a results.db or a .wadb archive, and shows every page
the main Word Atlas program wrote into it: the page as text, laid out
by the same code the main program uses; any one of its tables as a
grid that sorts by column; a search across every cell; the results
questions (runs, shares, deltas, seams, declined, diff); and a panel
for asking Claude questions of the data with the reader's own API key.

    python3 word_atlas_reader.py [dataset.wadb | results.db]

It needs Python 3 and PyQt6 and nothing else: the two modules it
shares with the main program (atlas_report.py, atlas_results.py) are
standard library only and live beside it.
"""

import faulthandler
import os
import signal
import sys
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QFont, QKeySequence, QShortcut, QTextCursor
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
                             QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                             QListWidget, QListWidgetItem, QTabWidget, QTextEdit, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

import atlas_results
from atlas_report import render, is_numeric_cell
from reader_data import Dataset, load_settings, save_settings
from reader_claude import DEFAULT_MODEL, STARTER_QUESTIONS, ApiError, clipboard_prompt, list_models, start_worker
from reader_help import HelpMode, column_help
import reader_guest
import reader_questions

VERSION = "0.3.2"
KINDS = ["Book", "Chapter", "Section", "Passage", "Word", "Kin", "Testament", "Compare"]
HISTORY_MAX = 30        # how many earlier searches and questions a drop-down keeps
# A button turns this green while the box beside it holds something
# not yet sent: a reminder that a click or Enter is still wanted
READY_STYLE = "QPushButton { background-color: #3a9a3a; color: white; font-weight: bold; }"


def mark_ready(button, on):
    """Colour a button green (on) or restore its usual look (off)."""
    button.setStyleSheet(READY_STYLE if on else "")


def mono_font():
    """A fixed-width font so the text pages line up as they do in a file."""
    font = QFont("DejaVu Sans Mono" if sys.platform != "win32" else "Consolas")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(10)
    return font


# ---------------------------------------------------------------------------
# A grid that explains its columns in help mode, and a table item that
# sorts numbers as numbers
# ---------------------------------------------------------------------------

class HelpGrid(QTableWidget):
    """A QTableWidget whose help note names the column under the pointer."""

    def help_at(self, pos):
        """The help for the column heading at pos (a point in this widget), or the grid's own note."""
        header = self.horizontalHeader()
        local = self.viewport().mapFrom(self, pos)
        col = header.logicalIndexAt(local.x())
        if col < 0 or self.columnCount() == 0:
            return ""
        item = self.horizontalHeaderItem(col)
        heading = item.text() if item else ""
        own = self.property("help_columns") or {}
        if heading in own:
            return f"{heading}: {own[heading]}"
        return f"{heading}: {column_help(heading)}"


class CellItem(QTableWidgetItem):
    """A grid cell: numeric cells compare by value, others by text."""

    def __init__(self, value, number=None):
        super().__init__(str(value))
        self.number = number
        if number is not None or is_numeric_cell(value):
            self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other):
        a, b = self.number, getattr(other, "number", None)
        if a is not None and b is not None:
            return a < b
        # A number sorts before text, so a column of figures with a few
        # dashes keeps its dashes at one end
        if (a is None) != (b is None):
            return a is not None
        return self.text() < other.text()


# ---------------------------------------------------------------------------
# Settings dialog: the API key and the model
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """Where the reader enters a Claude API key and picks a model."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Claude settings")
        self.settings = dict(settings)
        form = QFormLayout(self)
        self.key_edit = QLineEdit(self.settings.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-ant-...")
        form.addRow("Your API key", self.key_edit)
        # A guest key built into this copy is named by its end date only;
        # the key itself is never shown, and a key typed above replaces it
        self.guest_key, until = reader_guest.load()
        if self.guest_key:
            guest = QLabel(f"This copy carries a guest key good until {until} "
                           f"({reader_guest.days_left(until)} days left).  Leave the box above empty to use it; "
                           "a key of your own, entered above, is used instead.")
        elif until:
            guest = QLabel(f"This copy's guest key ended on {until}.  Enter a key of your own above.")
        else:
            guest = QLabel("No guest key in this copy; enter a key of your own above.")
        guest.setWordWrap(True)
        form.addRow(guest)
        row = QHBoxLayout()
        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.addItem(self.settings.get("model", DEFAULT_MODEL))
        fetch = QPushButton("Fetch models")
        fetch.clicked.connect(self.fetch_models)
        row.addWidget(self.model_box, 1)
        row.addWidget(fetch)
        form.addRow("Model", row)
        note = QLabel("The key is kept in the Reader's settings file in your home folder and is sent only to "
                      "api.anthropic.com.  Each question costs a few cents on your own account.")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def fetch_models(self):
        """Ask the API which models this key may use and list them."""
        key = self.key_edit.text().strip() or self.guest_key
        if not key:
            QMessageBox.information(self, "Fetch models", "Enter the API key first.")
            return
        try:
            models = list_models(key)
        except ApiError as e:
            QMessageBox.warning(self, "Fetch models", str(e))
            return
        current = self.model_box.currentText()
        self.model_box.clear()
        self.model_box.addItems(models)
        if current in models:
            self.model_box.setCurrentText(current)

    def result_settings(self):
        self.settings["api_key"] = self.key_edit.text().strip()
        self.settings["model"] = self.model_box.currentText().strip() or DEFAULT_MODEL
        return self.settings


# ---------------------------------------------------------------------------
# The Questions dialog: a long list to pick from, grouped by subject
# ---------------------------------------------------------------------------

class QuestionsDialog(QDialog):
    """Two hundred questions to put to the dataset, filtered by a word, chosen by a double-click."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Questions to ask")
        self.resize(760, 560)
        self.chosen = None
        box = QVBoxLayout(self)
        box.addWidget(QLabel("Double-click a question to put it in the box, then change the book or the word "
                             "to suit.  'This book' means the page open in the Reader."))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("show only questions containing ...")
        self.filter_edit.textChanged.connect(self.fill)
        box.addWidget(self.filter_edit)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(self.pick)
        box.addWidget(self.list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Use this question")
        buttons.accepted.connect(self.accept_current)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        self.fill()

    def fill(self, text=""):
        """List the questions, each group under a heading, keeping only those containing the filter text."""
        text = (text or "").strip().lower()
        self.list.clear()
        for group, questions in reader_questions.QUESTIONS.items():
            kept = [q for q in questions if text in q.lower()]
            if not kept:
                continue
            head = QListWidgetItem(group)
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            self.list.addItem(head)
            for q in kept:
                item = QListWidgetItem("    " + q)
                item.setData(Qt.ItemDataRole.UserRole, q)
                self.list.addItem(item)

    def pick(self, item):
        if item.data(Qt.ItemDataRole.UserRole):
            self.chosen = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def accept_current(self):
        item = self.list.currentItem()
        if item is not None and item.data(Qt.ItemDataRole.UserRole):
            self.chosen = item.data(Qt.ItemDataRole.UserRole)
            self.accept()


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

class ReaderWindow(QMainWindow):
    """The Reader's one window: pages on the left, views on the right."""

    def __init__(self, path=None):
        super().__init__()
        self.setWindowTitle(f"Word Atlas Reader {VERSION}")
        self.resize(1300, 850)
        self.settings = load_settings()
        self.data = None            # the open Dataset
        self.run_id = None          # the run shown
        self.report = None          # the Report of the page shown
        self.page_text = ""         # its rendered text
        self.worker = None          # the Claude question in flight, if any
        self.thread = None
        self._build_menus()
        self._build_body()
        self.statusBar().showMessage("Open a dataset: File > Open (a .wadb or a results.db)")
        # Open the file named on the command line, else the last one opened;
        # a last file that has gone (moved, renamed) is named, not passed
        # over in silence
        path = path or self.settings.get("last_file")
        if path and os.path.exists(path):
            QTimer.singleShot(0, lambda: self.open_path(path))
        elif path:
            self.statusBar().showMessage(f"The last dataset, {path}, is no longer there: open another with File > Open")

    # --- building --------------------------------------------------------------
    def _build_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        self._action(file_menu, "&Open dataset...", self.open_dialog, QKeySequence.StandardKey.Open)
        self._action(file_menu, "&Save page as text...", self.save_page, QKeySequence.StandardKey.Save)
        file_menu.addSeparator()
        self._action(file_menu, "&Claude settings...", self.edit_settings)
        file_menu.addSeparator()
        self._action(file_menu, "&Quit", self.close, QKeySequence.StandardKey.Quit)
        results = self.menuBar().addMenu("&Results")
        for name, label in [("runs", "&Runs in this file"), ("shares", "Septuagint &shares (1f)"),
                            ("deltas", "Function-word &Deltas (7d)"), ("seams", "Echo s&eams (4e)"),
                            ("declined", "Tables that &declined"),
                            ("listed", "Echo tables against the cross references (&listed)"),
                            ("unlisted", "A sample of &unlisted echoes to grade by hand")]:
            self._action(results, label, lambda checked=False, n=name: self.run_results(n))
        results.addSeparator()
        self._action(results, "&Diff two runs...", self.diff_runs)
        help_menu = self.menuBar().addMenu("&Help")
        self._action(help_menu, "&About", self.about)

    def _action(self, menu, label, slot, shortcut=None):
        action = QAction(label, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _build_body(self):
        body = QWidget()
        self.setCentralWidget(body)
        outer = QVBoxLayout(body)
        # The bar across the top: the run, and the search box
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Run:"))
        self.run_box = QComboBox()
        self.run_box.setProperty("help", "run")
        self.run_box.currentIndexChanged.connect(self.run_changed)
        bar.addWidget(self.run_box, 2)
        bar.addSpacing(20)
        bar.addWidget(QLabel("Search every cell:"))
        # An editable box whose drop-down lists earlier searches
        self.search_box = QComboBox()
        self.search_box.setEditable(True)
        self.search_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.search_box.setProperty("help", "search")
        self.search_edit = self.search_box.lineEdit()
        self.search_edit.setPlaceholderText("a word, a Strong's number, a phrase ...")
        self.search_edit.returnPressed.connect(self.search)
        self.search_box.activated.connect(lambda i: self.search())
        self.fill_history(self.search_box, "search")
        bar.addWidget(self.search_box, 2)
        self.search_button = QPushButton("Search")
        self.search_button.setProperty("help", "search")
        self.search_button.clicked.connect(self.search)
        bar.addWidget(self.search_button)
        # Green while the box holds a search not yet run
        self.search_edit.textChanged.connect(self.search_text_changed)
        bar.addSpacing(12)
        # The help switch: a checkable ? button, or F1
        self.help_btn = QPushButton("?")
        self.help_btn.setCheckable(True)
        self.help_btn.setFixedWidth(32)
        self.help_btn.setToolTip("Help mode (F1): point at anything to read what it is")
        self.help_btn.setProperty("help", "help")
        bar.addWidget(self.help_btn)
        outer.addLayout(bar)
        # Left: the pages of the run, grouped by kind.  Right: the views.
        split = QSplitter()
        outer.addWidget(split, 1)
        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("filter pages by title")
        self.filter_edit.setProperty("help", "filter")
        self.filter_edit.textChanged.connect(self.filter_pages)
        left_box.addWidget(self.filter_edit)
        self.page_tree = QTreeWidget()
        self.page_tree.setHeaderHidden(True)
        self.page_tree.setProperty("help", "pages")
        self.page_tree.currentItemChanged.connect(self.page_chosen)
        left_box.addWidget(self.page_tree, 1)
        split.addWidget(left)
        self.tabs = QTabWidget()
        self.tabs.setProperty("help", "tabs")
        split.addWidget(self.tabs)
        split.setSizes([340, 960])
        self._build_page_tab()
        self._build_table_tab()
        self._build_search_tab()
        self._build_results_tab()
        self._build_claude_tab()
        # Help mode: the ? button, F1, and the event filter that shows the notes
        self.help_mode = HelpMode(self, self.help_btn)
        self.help_btn.toggled.connect(self.help_mode.set_active)
        QShortcut(QKeySequence("F1"), self, activated=lambda: self.help_btn.toggle())

    def _build_page_tab(self):
        """The page as text, with a box to jump to a section."""
        tab = QWidget()
        box = QVBoxLayout(tab)
        row = QHBoxLayout()
        row.addWidget(QLabel("Jump to section:"))
        self.jump_box = QComboBox()
        self.jump_box.setProperty("help", "jump")
        self.jump_box.activated.connect(self.jump_to_section)
        row.addWidget(self.jump_box, 1)
        self.wrap_check = QCheckBox("Wrap long lines")
        self.wrap_check.setProperty("help", "wrap")
        self.wrap_check.toggled.connect(self.set_wrap)
        row.addWidget(self.wrap_check)
        box.addLayout(row)
        self.page_view = QPlainTextEdit()
        self.page_view.setReadOnly(True)
        self.page_view.setFont(mono_font())
        self.page_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.page_view.setProperty("help", "page_view")
        box.addWidget(self.page_view, 1)
        self.tabs.addTab(tab, "Page")

    def _build_table_tab(self):
        """One table of the page as a sortable grid."""
        tab = QWidget()
        box = QVBoxLayout(tab)
        row = QHBoxLayout()
        row.addWidget(QLabel("Table:"))
        self.table_box = QComboBox()
        self.table_box.setProperty("help", "table_box")
        self.table_box.currentIndexChanged.connect(self.show_table)
        row.addWidget(self.table_box, 1)
        box.addLayout(row)
        self.table_note = QLabel()
        self.table_note.setWordWrap(True)
        self.table_note.setProperty("help", "table_note")
        box.addWidget(self.table_note)
        self.grid = HelpGrid()
        self.grid.setProperty("help", "grid")
        self.grid.setSortingEnabled(True)
        self.grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.grid.verticalHeader().setDefaultSectionSize(22)   # rows as tight as a text page's lines
        self.grid.cellClicked.connect(self.grid_clicked)
        box.addWidget(self.grid, 1)
        self.table_footer = QPlainTextEdit()
        self.table_footer.setReadOnly(True)
        self.table_footer.setMaximumHeight(140)
        self.table_footer.setProperty("help", "table_footer")
        box.addWidget(self.table_footer)
        self.tabs.addTab(tab, "Table")

    def _build_search_tab(self):
        tab = QWidget()
        box = QVBoxLayout(tab)
        self.search_note = QLabel("Type in the search box above and press Enter.")
        box.addWidget(self.search_note)
        self.search_grid = HelpGrid()
        self.search_grid.setColumnCount(5)
        self.search_grid.setHorizontalHeaderLabels(["page", "table", "row", "column", "value"])
        self.search_grid.setProperty("help", "search_grid")
        self.search_grid.setProperty("help_columns", {
            "page": "The page the hit is on.", "table": "The number of the table on that page.",
            "row": "The row of the table, counted from 1; empty for a hit in a title or footer.",
            "column": "The column the hit is in; 'title' or 'footer' for a hit outside the table.",
            "value": "The cell, title or footer that holds the search text."})
        self.search_grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.search_grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.search_grid.cellDoubleClicked.connect(self.search_hit_opened)
        box.addWidget(self.search_grid, 1)
        box.addWidget(QLabel("Double-click a hit to open its page at that table."))
        self.tabs.addTab(tab, "Search")

    def _build_results_tab(self):
        tab = QWidget()
        box = QVBoxLayout(tab)
        box.addWidget(QLabel("The Results menu asks the questions atlas_results.py asks; the answer prints here."))
        self.results_view = QPlainTextEdit()
        self.results_view.setReadOnly(True)
        self.results_view.setFont(mono_font())
        self.results_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.results_view.setProperty("help", "results_view")
        box.addWidget(self.results_view, 1)
        save = QPushButton("Save as text...")
        save.clicked.connect(self.save_results)
        box.addWidget(save, 0, Qt.AlignmentFlag.AlignRight)
        self.tabs.addTab(tab, "Results")

    def _build_claude_tab(self):
        tab = QWidget()
        box = QVBoxLayout(tab)
        guest_key, until = reader_guest.load()
        if guest_key:
            heading = (f"Ask a question of the dataset.  Claude answers by running read-only SQL queries against "
                       f"it.  This copy carries a guest key good until {until}; after that, or sooner if you "
                       "like, enter a key of your own under File > Claude settings.")
        else:
            heading = ("Ask a question of the dataset.  Claude answers by running read-only SQL "
                       "queries against it with your own API key (File > Claude settings).")
        box.addWidget(QLabel(heading))
        # Earlier questions in a drop-down; choosing one puts it back in the box
        row = QHBoxLayout()
        row.addWidget(QLabel("Past questions:"))
        self.past_box = QComboBox()
        self.past_box.setProperty("help", "past_questions")
        self.past_box.activated.connect(self.past_question_chosen)
        self.fill_history(self.past_box, "questions", blank_first=True, starters=STARTER_QUESTIONS)
        row.addWidget(self.past_box, 1)
        box.addLayout(row)
        self.question_edit = QTextEdit()
        self.question_edit.setPlaceholderText("Which part of Revelation stands furthest from the rest of the book "
                                              "in its function words?")
        self.question_edit.setMaximumHeight(90)
        self.question_edit.setProperty("help", "question")
        box.addWidget(self.question_edit)
        row = QHBoxLayout()
        self.question_edit.textChanged.connect(self.question_text_changed)
        self.ask_button = QPushButton("Ask Claude")
        self.ask_button.setProperty("help", "ask")
        self.ask_button.clicked.connect(self.ask_claude)
        row.addWidget(self.ask_button)
        copy = QPushButton("Copy as a prompt for claude.ai")
        copy.setProperty("help", "copy_prompt")
        copy.setToolTip("No API key?  Copy the question with the schema and the open page, and paste it into "
                        "claude.ai or any assistant.")
        copy.clicked.connect(self.copy_prompt)
        row.addWidget(copy)
        questions = QPushButton("Questions...")
        questions.setProperty("help", "questions")
        questions.setToolTip("A long list of questions to pick from, grouped by subject")
        questions.clicked.connect(self.pick_question)
        row.addWidget(questions)
        self.save_answer_button = QPushButton("Save answer as text...")
        self.save_answer_button.setProperty("help", "save_answer")
        self.save_answer_button.setToolTip("Write the question, the answer and the queries to a text file")
        self.save_answer_button.setEnabled(False)
        self.save_answer_button.clicked.connect(self.save_answer)
        row.addWidget(self.save_answer_button)
        row.addStretch(1)
        box.addLayout(row)
        self.answer_view = QTextEdit()
        self.answer_view.setReadOnly(True)
        self.answer_view.setProperty("help", "answer")
        box.addWidget(self.answer_view, 2)
        box.addWidget(QLabel("The queries Claude ran:"))
        self.queries_view = QPlainTextEdit()
        self.queries_view.setReadOnly(True)
        self.queries_view.setFont(mono_font())
        self.queries_view.setMaximumHeight(160)
        self.queries_view.setProperty("help", "queries")
        box.addWidget(self.queries_view)
        self.tabs.addTab(tab, "Ask Claude")

    # --- histories: earlier searches and questions, kept in the settings ------------
    def history(self, name):
        return list(self.settings.get("history", {}).get(name, []))

    def remember(self, name, text):
        """Put text at the head of a history, dropping an older copy, and save."""
        text = text.strip()
        if not text:
            return
        items = [t for t in self.history(name) if t != text]
        items.insert(0, text)
        self.settings.setdefault("history", {})[name] = items[:HISTORY_MAX]
        save_settings(self.settings)

    def fill_history(self, box, name, blank_first=False, starters=None):
        """
        Fill a combo box from a history, keeping any text being typed.
        With starters, those follow the history under a separator, so a
        reader who has asked nothing yet still has questions to pick
        from and a seasoned one keeps them within reach.
        """
        current = box.currentText() if box.isEditable() else ""
        box.blockSignals(True)
        box.clear()
        if blank_first:
            box.addItem("")
        items = self.history(name)
        box.addItems(items)
        if starters:
            if items:
                box.insertSeparator(box.count())
            box.addItems([q for q in starters if q not in items])
        if box.isEditable():
            box.setEditText(current)
        box.blockSignals(False)

    def pick_question(self):
        """Open the Questions list and put the chosen one in the box."""
        dialog = QuestionsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.chosen:
            self.question_edit.setPlainText(dialog.chosen)
            self.tabs.setCurrentIndex(4)

    def past_question_chosen(self, index):
        text = self.past_box.itemText(index)
        if text:
            self.question_edit.setPlainText(text)

    def set_wrap(self, on):
        """Wrap the page text to the window, or keep it as the file lays it out."""
        mode = QPlainTextEdit.LineWrapMode.WidgetWidth if on else QPlainTextEdit.LineWrapMode.NoWrap
        self.page_view.setLineWrapMode(mode)

    # --- opening a file ------------------------------------------------------------
    def open_dialog(self):
        start = os.path.dirname(self.settings.get("last_file", "")) or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Open a Word Atlas dataset", start,
                                              "Word Atlas datasets (*.wadb *.db);;All files (*)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        """Open the file, remember it, and show its newest run."""
        try:
            data = Dataset.open(path)
        except Exception as e:
            QMessageBox.warning(self, "Open dataset", f"Could not open {path}:\n{e}")
            return
        if self.data is not None:
            self.data.close()
        self.data = data
        self.settings["last_file"] = path
        save_settings(self.settings)
        self.setWindowTitle(f"Word Atlas Reader {VERSION}  -  {os.path.basename(path)}")
        self.statusBar().showMessage(data.describe())
        self.run_box.blockSignals(True)
        self.run_box.clear()
        for run_id, version, started, note, n in data.runs():
            label = f"run {run_id}: Word Atlas {version}, {started}, {n} pages"
            if note:
                label += f"  ({note})"
            self.run_box.addItem(label, run_id)
        self.run_box.blockSignals(False)
        self.run_changed(0)

    def run_changed(self, index):
        """Fill the page tree for the chosen run."""
        if self.data is None or index < 0:
            return
        self.run_id = self.run_box.itemData(index)
        self.page_tree.blockSignals(True)
        self.page_tree.clear()
        groups = {}
        for page_id, kind, title in self.data.pages(self.run_id):
            if kind not in groups:
                groups[kind] = QTreeWidgetItem([kind])
                groups[kind].setFlags(Qt.ItemFlag.ItemIsEnabled)
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, page_id)
            groups[kind].addChild(item)
        # Kinds in the main program's order, any unknown kind after
        for kind in KINDS + sorted(k for k in groups if k not in KINDS):
            if kind in groups:
                self.page_tree.addTopLevelItem(groups[kind])
                groups[kind].setExpanded(True)
        self.page_tree.blockSignals(False)
        self.filter_pages(self.filter_edit.text())
        # Show the first page straight away
        first = next((groups[k].child(0) for k in KINDS if k in groups and groups[k].childCount()), None)
        if first is not None:
            self.page_tree.setCurrentItem(first)

    def filter_pages(self, text):
        """Hide the pages whose title lacks the filter text."""
        text = text.strip().lower()
        for g in range(self.page_tree.topLevelItemCount()):
            group = self.page_tree.topLevelItem(g)
            shown = 0
            for c in range(group.childCount()):
                child = group.child(c)
                hide = bool(text) and text not in child.text(0).lower()
                child.setHidden(hide)
                shown += not hide
            group.setHidden(shown == 0)

    # --- showing a page ----------------------------------------------------------------
    def page_chosen(self, item, previous=None):
        if item is None or item.data(0, Qt.ItemDataRole.UserRole) is None:
            return
        self.show_page(item.data(0, Qt.ItemDataRole.UserRole))

    def show_page(self, page_id, section_number=None):
        """Render the page, fill the section boxes, and jump to a section when asked."""
        self.report = self.data.report(page_id)
        self.page_text = render(self.report, atlas=self.data.build_of(self.run_id))
        self.page_view.setPlainText(self.page_text)
        self.jump_box.blockSignals(True)
        self.table_box.blockSignals(True)
        self.jump_box.clear()
        self.table_box.clear()
        for sec in self.report.sections:
            self.jump_box.addItem(sec.title)
            self.table_box.addItem(sec.title)
        self.jump_box.blockSignals(False)
        self.table_box.blockSignals(False)
        if section_number is not None:
            for i, sec in enumerate(self.report.sections):
                if sec.title.split(" ")[0].rstrip(".") == section_number:
                    self.jump_box.setCurrentIndex(i)
                    self.table_box.setCurrentIndex(i)
                    self.jump_to_section(i)
                    break
        else:
            self.page_view.moveCursor(QTextCursor.MoveOperation.Start)
        self.show_table(self.table_box.currentIndex())

    def jump_to_section(self, index):
        """Scroll the text view so the section's title is at the top."""
        if self.report is None or index < 0 or index >= len(self.report.sections):
            return
        title = self.report.sections[index].title
        pos = self.page_text.find("\n" + title + "\n")
        if pos < 0:
            return
        # Scroll so the title's line is the first one shown: the line
        # number is the count of newlines before it, and the vertical
        # scroll bar of a plain text view counts in lines
        line = self.page_text.count("\n", 0, pos + 1)
        cursor = self.page_view.textCursor()
        cursor.setPosition(pos + 1)
        self.page_view.setTextCursor(cursor)
        self.page_view.verticalScrollBar().setValue(line)
        self.tabs.setCurrentIndex(0)

    def show_table(self, index):
        """Fill the grid with one section's rows."""
        self.grid.setSortingEnabled(False)
        self.grid.clear()
        self.grid.setRowCount(0)
        self.grid.setColumnCount(0)
        self.table_note.setText("")
        self.table_footer.setPlainText("")
        if self.report is None or index < 0 or index >= len(self.report.sections):
            return
        sec = self.report.sections[index]
        self.table_note.setText(sec.note)
        self.grid.setColumnCount(len(sec.columns))
        self.grid.setHorizontalHeaderLabels([str(c) for c in sec.columns])
        self.grid.setRowCount(len(sec.rows))
        for r, row in enumerate(sec.rows):
            for c, value in enumerate(row):
                item = CellItem(value, getattr(sec, "cell_numbers", {}).get((r, c)))
                if sec.refs[r]:
                    item.setToolTip("; ".join(sec.refs[r][:20]) + (" ..." if len(sec.refs[r]) > 20 else ""))
                self.grid.setItem(r, c, item)
        self.grid.setSortingEnabled(True)
        self.table_footer.setPlainText("\n".join(sec.footer))

    def grid_clicked(self, row, col):
        """Show the verses behind the clicked row in the status bar."""
        index = self.table_box.currentIndex()
        if self.report is None or index < 0:
            return
        item = self.grid.item(row, 0)
        sec = self.report.sections[index]
        # The grid may be sorted, so find the row by its first cell
        for r, src in enumerate(sec.rows):
            if item is not None and str(src[0]) == item.text():
                refs = sec.refs[r]
                self.statusBar().showMessage(f"{len(refs)} verse(s): " + ", ".join(refs[:30])
                                             if refs else "No verse references behind this row")
                return

    # --- search --------------------------------------------------------------------------
    def search_text_changed(self, text):
        """The Search button goes green while the box holds something not yet searched."""
        text = text.strip()
        mark_ready(self.search_button, bool(text) and text != getattr(self, "last_search", None))

    def search(self):
        text = self.search_edit.text().strip()
        if self.data is None or not text:
            return
        hits = self.data.search(self.run_id, text)
        self.last_search = text
        mark_ready(self.search_button, False)
        self.remember("search", text)
        self.fill_history(self.search_box, "search")
        self.search_grid.setRowCount(0)
        self.search_grid.setRowCount(len(hits))
        for i, (page_id, page, number, row, column, value) in enumerate(hits):
            cells = [page, number, "" if row < 0 else str(row + 1), column, value]
            for c, v in enumerate(cells):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, (page_id, number))
                self.search_grid.setItem(i, c, item)
        self.search_note.setText(f"{len(hits)} hit(s) for '{text}' in run {self.run_id}"
                                 + (" (the first 500 cells)" if len(hits) >= 500 else ""))
        self.tabs.setCurrentIndex(2)

    def search_hit_opened(self, row, col):
        item = self.search_grid.item(row, 0)
        if item is None:
            return
        page_id, number = item.data(Qt.ItemDataRole.UserRole)
        self.select_page(page_id)
        self.show_page(page_id, number)

    def select_page(self, page_id):
        """Highlight the page in the tree without re-rendering it twice."""
        self.page_tree.blockSignals(True)
        for g in range(self.page_tree.topLevelItemCount()):
            group = self.page_tree.topLevelItem(g)
            for c in range(group.childCount()):
                child = group.child(c)
                if child.data(0, Qt.ItemDataRole.UserRole) == page_id:
                    self.page_tree.setCurrentItem(child)
        self.page_tree.blockSignals(False)

    # --- the results questions ----------------------------------------------------------
    def run_results(self, name):
        """Run one of atlas_results.py's questions against the open run."""
        if self.data is None:
            return
        question = {"runs": atlas_results.q_runs, "shares": atlas_results.q_shares,
                    "deltas": atlas_results.q_deltas, "seams": atlas_results.q_seams,
                    "declined": atlas_results.q_declined, "listed": atlas_results.q_listed,
                    "unlisted": atlas_results.q_unlisted}[name]
        try:
            head, body = question(self.data.db, self.run_id)
        except Exception as e:
            QMessageBox.warning(self, "Results", f"The question failed: {e}")
            return
        self.results_view.setPlainText(f"Results: {name} (run {self.run_id})\n{'#' * 60}\n{head}\n\n{body}\n")
        self.tabs.setCurrentIndex(3)

    def diff_runs(self):
        """Compare two runs cell by cell."""
        if self.data is None:
            return
        runs = self.data.runs()
        if len(runs) < 2:
            QMessageBox.information(self, "Diff two runs", "This file holds only one run; a diff needs two.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Diff two runs")
        form = QFormLayout(dialog)
        a_box, b_box = QComboBox(), QComboBox()
        for run_id, version, started, note, n in runs:
            for box in (a_box, b_box):
                box.addItem(f"run {run_id}: {version}, {started}", run_id)
        b_box.setCurrentIndex(1)
        form.addRow("Earlier run", b_box)
        form.addRow("Later run", a_box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        head, body = atlas_results.q_diff(self.data.db, b_box.currentData(), a_box.currentData())
        self.results_view.setPlainText(f"Results: diff\n{'#' * 60}\n{head}\n\n{body}\n")
        self.tabs.setCurrentIndex(3)

    # --- saving ---------------------------------------------------------------------------
    def save_page(self):
        if self.report is None:
            return
        self._save_text(self.page_text, f"{self.report.name}.txt", "Save page as text")

    def save_results(self):
        text = self.results_view.toPlainText()
        if text:
            self._save_text(text, "results.txt", "Save results as text")

    def _save_text(self, text, suggested, title):
        start = os.path.join(os.path.dirname(self.settings.get("last_file", "")) or os.path.expanduser("~"),
                             suggested)
        path, _ = QFileDialog.getSaveFileName(self, title, start, "Text files (*.txt);;All files (*)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.statusBar().showMessage(f"Saved {path}")

    # --- Claude ------------------------------------------------------------------------------
    def edit_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.result_settings()
            save_settings(self.settings)

    def ask_claude(self):
        """Send the question to Claude on a worker thread."""
        question = self.question_edit.toPlainText().strip()
        if self.data is None or not question:
            return
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.information(self, "Ask Claude", "A question is still being answered.")
            return
        key = self.settings.get("api_key", "") or reader_guest.load()[0]
        if not key:
            _, until = reader_guest.load()
            ended = f"  This copy's guest key ended on {until}." if until else ""
            QMessageBox.information(self, "Ask Claude",
                                    "Enter your API key under File > Claude settings first, or use "
                                    "'Copy as a prompt' and paste the question into claude.ai." + ended)
            return
        model = self.settings.get("model", DEFAULT_MODEL)
        self.remember("questions", question)
        self.last_question = question
        mark_ready(self.ask_button, False)
        self.fill_history(self.past_box, "questions", blank_first=True, starters=STARTER_QUESTIONS)
        self.ask_button.setEnabled(False)
        self.answer_view.setPlainText("Asking " + model + " ...")
        self.queries_view.setPlainText("")
        # The open page goes with the question, so "this book" and "this
        # page" mean what the reader is looking at
        sent = question
        if self.report is not None:
            sent += f"\n\n(The page open in the Reader is: {self.report.title}.)"
        self.thread, self.worker = start_worker(self, self.data.db_path, sent, key, model, self.run_id,
                                                self.data.schema_text())
        self.worker.progress.connect(self.query_ran)
        self.worker.finished.connect(self.answered)
        self.worker.failed.connect(self.ask_failed)

    def query_ran(self, sql):
        self.queries_view.appendPlainText(sql.strip() + "\n")

    def question_text_changed(self):
        """The Ask button goes green while the box holds a question not yet asked."""
        text = self.question_edit.toPlainText().strip()
        mark_ready(self.ask_button, bool(text) and text != getattr(self, "last_question", None))

    def answered(self, answer, queries):
        self.answer_view.setMarkdown(answer)
        # Kept as written for the saved file: the view's markdown has
        # been turned into formatting, and the plain text is what a
        # text file wants
        self.last_answer = {"question": self.question_edit.toPlainText().strip(), "answer": answer,
                            "queries": list(queries), "model": self.settings.get("model", DEFAULT_MODEL),
                            "asked": time.strftime("%Y-%m-%d %H:%M")}
        self.save_answer_button.setEnabled(True)
        self.ask_button.setEnabled(True)

    def ask_failed(self, message):
        self.answer_view.setPlainText("The question could not be answered.\n\n" + message)
        self.ask_button.setEnabled(True)

    def save_answer(self):
        """Write the last question, its answer and the queries behind it to a text file."""
        last = getattr(self, "last_answer", None)
        if not last:
            return
        dataset = os.path.basename(self.data.source_path) if self.data else ""
        lines = ["WORD ATLAS READER  -  a question answered by Claude",
                 "#" * 52,
                 f"Dataset: {dataset}, run {self.run_id}.  Asked {last['asked']}, model {last['model']}.",
                 "",
                 "Question",
                 "========",
                 last["question"],
                 "",
                 "Answer",
                 "======",
                 last["answer"],
                 "",
                 "The queries Claude ran",
                 "======================"]
        lines.extend(q.strip() + "\n" for q in last["queries"])
        # A file name from the question's first words
        words = "".join(c if c.isalnum() or c == " " else " " for c in last["question"]).split()[:6]
        suggested = "answer_" + "_".join(w.lower() for w in words) + ".txt" if words else "answer.txt"
        self._save_text("\n".join(lines).rstrip() + "\n", suggested, "Save answer as text")

    def copy_prompt(self):
        """Put a ready-made prompt on the clipboard for a reader without a key."""
        question = self.question_edit.toPlainText().strip()
        if self.data is None or not question:
            return
        prompt = clipboard_prompt(question, self.data.schema_text(), self.page_text or None)
        QApplication.clipboard().setText(prompt)
        self.statusBar().showMessage(f"Copied a prompt of {len(prompt):,} characters; paste it into claude.ai")

    # --- about ------------------------------------------------------------------------------
    def about(self):
        QMessageBox.about(self, "Word Atlas Reader",
                          f"Word Atlas Reader {VERSION}\n\nA viewer for the results a Word Atlas run wrote: "
                          "every page, every table, every figure, in one file.\n\nAndrew Hopkins, with Claude.")

    def closeEvent(self, event):
        # The help mode's filter sits on the application, not the window,
        # so it must be taken off before the window goes, or the next
        # event would reach a filter whose window is gone
        self.help_mode.set_active(False)
        QApplication.instance().removeEventFilter(self.help_mode)
        if self.data is not None:
            self.data.close()
        event.accept()


def main():
    # A way to see where the program is if it ever stops answering: on
    # Linux,  kill -USR1 <pid>  prints every thread's stack to the
    # terminal the Reader was started from, without stopping it
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    app = QApplication(sys.argv)
    app.setApplicationName("Word Atlas Reader")
    window = ReaderWindow(sys.argv[1] if len(sys.argv) > 1 else None)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
