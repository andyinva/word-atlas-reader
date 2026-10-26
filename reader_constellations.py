#!/usr/bin/env python3
"""
reader_constellations.py  -  the Constellations tab of the Word Atlas Reader

A constellation is a set of two to five roots that gather in one stretch
of text far more often than their separate rates predict.  The main
program (Word Atlas 0.10.112 or later, atlas_sets.py) finds them and
writes every figure into the dataset: the word_sets, word_set_members and
word_set_windows tables.  This tab only selects those rows and draws
them.  It counts nothing afresh.

    the top row    the scope (a book, or the Old or New Testament), which
                   follows the page chosen on the left; the norm (against
                   the book itself, or against its testament); the kind
                   (constellations, frames, phrases); the size; closed
                   sets only; and a root box, where a word or a Strong's
                   number (covenant, H1285) keeps only the sets that hold
                   it: every set a word belongs to, strongest first
    the grid       one row per set, sorted by keyness, any column sortable
    the strip      for the chosen set, one cell per verse of the scope,
                   lit where the set's places lie, so its places and an
                   inclusio can be seen at a glance
    the places     the set's verse ranges; clicking one shows its King
                   James text on the right; the smaller sets folded under
                   it are listed below the ranges

A dataset packed before Word Atlas 0.10.112 has no such tables (or the
first ones, without the columns this tab reads); the tab then says which
dataset to open.

Author: Andrew Hopkins (with Claude)
"""

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPainter
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter,
                             QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget)

# The grid's columns, with the help note each shows in help mode (the
# definitions of atlas_sets.py's settings, in plain words)
COLUMNS = [
    ("words", "The set's roots by their commonest King James spellings, in the stored (canonical) order.  "
              "Point at a row for the Strong's numbers."),
    ("size", "How many roots the set holds: 2 to 5."),
    ("kind", "constellation: words that gather without standing in order.  frame: three roots or more that "
             "come in one same order within twelve content words in most of their windows, a formula with "
             "gaps.  phrase: the roots stand inside one formula (adjacent words) in most of their windows."),
    ("support", "The ten-verse windows (moving a verse at a time) in which every root of the set occurs."),
    ("places", "The separate places the set gathers: its windows joined where they touch.  A set must "
               "gather in 3 places in a book, 6 in a testament."),
    ("expected", "The support if the roots fell independently.  Against the book: the windows times each "
                 "root's share of them.  Against the testament: the book's windows times the set's rate "
                 "over the testament."),
    ("lift", "support / expected: how many times more often the set gathers than chance (against the "
             "testament: how many times more often the book holds it than the testament does)."),
    ("keyness", "Dunning's G2 of support against expected: how surprising the gathering is.  The sort order; "
                "at least 10.8."),
    ("span", "Chapters from the start of the set's first place to the end of its last."),
    ("in order", "The share of the set's windows in which its roots come in one same order within twelve "
                 "content words."),
    ("inclusio", "Marked when every place of the set lies in the first or last 15% of the book, with one at "
                 "each end: a frame found by counting."),
    ("folds", "How many smaller sets fold under this one: sets of its roots, one fewer, with the same support, "
              "which say nothing it does not."),
]
HEADINGS = [c for c, _ in COLUMNS]
LIMIT = 500                         # rows the grid shows; the line above it says how many matched

NORM_NAMES = {"book": "against the book itself", "testament": "against its testament"}
KIND_CHOICES = [("all kinds", None), ("constellations", "constellation"), ("frames", "frame"), ("phrases", "phrase")]
SIZE_CHOICES = [("all sizes", None), ("2", 2), ("3", 3), ("4", 4), ("5", 5)]

LIT = QColor(0xe3, 0x49, 0x48)       # the heat strips' hot colour: where the set gathers
UNLIT = QColor(0xf0, 0xef, 0xec)     # their ordinary colour


class SetItem(QTableWidgetItem):
    """A grid cell: numbers sort by value, text by text."""

    def __init__(self, text, number=None):
        super().__init__(text)
        self.number = number
        if number is not None:
            self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other):
        a, b = self.number, getattr(other, "number", None)
        if a is not None and b is not None:
            return a < b
        return self.text() < other.text()


class SetGrid(QTableWidget):
    """The grid of sets; in help mode, the note of the column under the pointer."""

    def help_at(self, pos):
        header = self.horizontalHeader()
        col = header.logicalIndexAt(self.viewport().mapFrom(self, pos).x())
        if 0 <= col < len(COLUMNS):
            return f"{COLUMNS[col][0]}: {COLUMNS[col][1]}"
        return ""


class SetStrip(QWidget):
    """
    One strip along the scope, a cell per verse, lit where the chosen set's
    places lie (the stored verse ranges); chapter marks along the top.
    """

    TOP, ROW_H = 16, 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.verses = []            # (book, chapter, verse) of the scope, in order
        self.lit = []               # one bool per verse
        self.places = []            # the stored ranges, for the tooltip
        self.title = ""
        self.setMinimumHeight(self.TOP + self.ROW_H + 6)

    def set_verses(self, verses):
        self.verses = verses
        self.lit = [False] * len(verses)
        self.update()

    def show_places(self, title, places):
        """Light the verses that lie inside any stored range."""
        self.title, self.places = title, places
        spans = {}
        for book, c1, v1, c2, v2 in places:
            spans.setdefault(book, []).append(((c1, v1), (c2, v2)))
        self.lit = [any(a <= (c, v) <= b for a, b in spans.get(book, [])) for book, c, v in self.verses]
        self.update()

    def cell(self, i):
        width = max(1.0, self.width() - 8) / max(1, len(self.verses))
        x = 4 + i * width
        return QRect(int(x), self.TOP, max(1, int(x + width) - int(x)), self.ROW_H)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#fcfcfb"))
        if not self.verses:
            p.setPen(QColor("#6b6a66"))
            p.drawText(self.rect().adjusted(8, 2, -8, -2), Qt.AlignmentFlag.AlignLeft,
                       "No strip: this dataset holds no King James text for the scope.")
            p.end()
            return
        font = p.font()
        font.setPointSize(7)
        p.setFont(font)
        # One book: a tick and a number where each chapter begins.  A
        # testament: a tick and a name where each book begins
        one_book = self.verses[0][0] == self.verses[-1][0]
        last, next_free = None, 0
        for i, (book, c, v) in enumerate(self.verses):
            r = self.cell(i)
            p.fillRect(r, LIT if self.lit[i] else UNLIT)
            mark = (book, c) if one_book else book
            if mark != last:
                p.setPen(QColor("#b9b7b0"))
                p.drawLine(r.left(), self.TOP - 4, r.left(), self.TOP - 1)
                text = str(c) if one_book else book
                if r.left() >= next_free:
                    p.setPen(QColor("#6b6a66"))
                    p.drawText(r.left() + 1, self.TOP - 5, text)
                    next_free = r.left() + p.fontMetrics().horizontalAdvance(text) + 6
                last = mark
        p.end()

    def mouseMoveEvent(self, event):
        if not self.verses:
            return
        width = max(1.0, self.width() - 8) / len(self.verses)
        i = int((event.position().x() - 4) / width)
        if 0 <= i < len(self.verses):
            book, c, v = self.verses[i]
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{book} {c}:{v}" + ("  (the set gathers here)" if self.lit[i] else ""), self)


class ConstellationTab(QWidget):
    """The Constellations tab: the sets of a scope from the stored rows, a strip, the places and their text."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.data = None
        self.run_id = None
        self.rows = []               # the rows in the grid, as stored
        self.total = 0
        self.chosen = None           # the chosen set's row
        box = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setProperty("help", "sets_note")
        box.addWidget(self.note)
        # The top row: scope, norm, kind, size
        row = QHBoxLayout()
        row.addWidget(QLabel("Book:"))
        self.scope_box = self._combo("sets_scope", 12)
        self.scope_box.currentIndexChanged.connect(self.scope_changed)
        row.addWidget(self.scope_box, 2)
        row.addWidget(QLabel("Norm:"))
        self.norm_box = self._combo("sets_norm", 14)
        self.norm_box.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.norm_box, 2)
        row.addWidget(QLabel("Kind:"))
        self.kind_box = self._combo("sets_kind", 10)
        for label, value in KIND_CHOICES:
            self.kind_box.addItem(label, value)
        self.kind_box.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.kind_box, 1)
        row.addWidget(QLabel("Size:"))
        self.size_box = self._combo("sets_size", 6)
        for label, value in SIZE_CHOICES:
            self.size_box.addItem(label, value)
        self.size_box.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.size_box)
        box.addLayout(row)
        # The second row: closed only, the root box, save and copy
        row = QHBoxLayout()
        self.closed_box = QCheckBox("Closed sets only")
        self.closed_box.setChecked(True)
        self.closed_box.setProperty("help", "sets_closed")
        self.closed_box.toggled.connect(self.refresh)
        row.addWidget(self.closed_box)
        row.addWidget(QLabel("Root:"))
        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("a word or a Strong's number: covenant, H1285")
        self.root_edit.setProperty("help", "sets_root")
        self.root_edit.returnPressed.connect(self.refresh)
        row.addWidget(self.root_edit, 2)
        self.root_button = QPushButton("Filter")
        self.root_button.setProperty("help", "sets_root")
        self.root_button.clicked.connect(self.refresh)
        row.addWidget(self.root_button)
        self.save_button = QPushButton("Save as text...")
        self.save_button.setProperty("help", "sets_save")
        self.save_button.clicked.connect(self.save_text)
        row.addWidget(self.save_button)
        self.copy_button = QPushButton("Copy set")
        self.copy_button.setProperty("help", "sets_copy")
        self.copy_button.clicked.connect(self.copy_set)
        row.addWidget(self.copy_button)
        box.addLayout(row)
        self.count_label = QLabel()
        self.count_label.setProperty("help", "sets_count")
        box.addWidget(self.count_label)
        # The grid, then the strip and the places with their text
        split = QSplitter(Qt.Orientation.Vertical)
        self.grid = SetGrid(0, len(HEADINGS))
        self.grid.setHorizontalHeaderLabels(HEADINGS)
        self.grid.setProperty("help", "sets_grid")
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grid.verticalHeader().setVisible(False)
        self.grid.verticalHeader().setDefaultSectionSize(22)
        header = self.grid.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Strongest first: the keyness column, descending, until a heading is clicked
        header.setSortIndicator(HEADINGS.index("keyness"), Qt.SortOrder.DescendingOrder)
        self.grid.setSortingEnabled(True)
        self.grid.itemSelectionChanged.connect(self.set_chosen)
        split.addWidget(self.grid)
        lower = QWidget()
        lower_box = QVBoxLayout(lower)
        lower_box.setContentsMargins(0, 0, 0, 0)
        self.strip_label = QLabel("Choose a set to see where it gathers.")
        self.strip_label.setProperty("help", "sets_strip")
        lower_box.addWidget(self.strip_label)
        self.strip = SetStrip()
        self.strip.setProperty("help", "sets_strip")
        lower_box.addWidget(self.strip)
        sides = QSplitter(Qt.Orientation.Horizontal)
        self.place_list = QListWidget()
        self.place_list.setProperty("help", "sets_places")
        self.place_list.currentItemChanged.connect(self.place_chosen)
        sides.addWidget(self.place_list)
        right = QWidget()
        right_box = QVBoxLayout(right)
        right_box.setContentsMargins(0, 0, 0, 0)
        self.tags_box = QCheckBox("with Strong's numbers")
        self.tags_box.setProperty("help", "sets_tags")
        self.tags_box.toggled.connect(lambda *_: self.place_chosen(self.place_list.currentItem()))
        right_box.addWidget(self.tags_box)
        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setProperty("help", "sets_text")
        right_box.addWidget(self.text_view, 1)
        sides.addWidget(right)
        sides.setSizes([360, 560])
        lower_box.addWidget(sides, 1)
        split.addWidget(lower)
        split.setSizes([420, 360])
        box.addWidget(split, 1)
        self.set_dataset(None)

    def _combo(self, help_key, chars):
        """A drop-down sized by a few characters, not by its longest entry."""
        combo = QComboBox()
        combo.setProperty("help", help_key)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(chars)
        return combo

    # --- filling ----------------------------------------------------------------
    def set_dataset(self, data, run_id=None):
        """Fill the tab from a newly opened dataset (or empty it)."""
        self.data = data
        self.rows, self.total, self.chosen = [], 0, None
        self.scope_box.blockSignals(True)
        self.scope_box.clear()
        self.scope_box.blockSignals(False)
        self.norm_box.clear()
        self.grid.setRowCount(0)
        self.place_list.clear()
        self.text_view.setPlainText("")
        self.strip.set_verses([])
        self.count_label.setText("")
        if data is None:
            self.note.setText("Open a dataset to see its constellations.")
            return
        if not data.has_sets():
            self.note.setText("This dataset holds no constellations: it was packed before Word Atlas 0.10.112.  "
                              "Open a dataset packed by 0.10.112 or later (word_atlas_..._.wadb made after the "
                              "canon run of that version, or after atlas_sets.py --all) to see them here.")
            return
        self.note.setText("Sets of two to five words that gather in one stretch of text far more often than "
                          "chance, as the main program found them.  Every figure is stored; choose a set to see "
                          "where it gathers and to read its places.")
        self.run_id = data.set_run(run_id)
        self.scope_box.blockSignals(True)
        for scope in data.set_scopes(self.run_id):
            self.scope_box.addItem(scope)
        self.scope_box.blockSignals(False)
        if self.scope_box.count():
            self.scope_box.setCurrentIndex(0)
            self.scope_changed(0)

    def show_book(self, book):
        """Follow the page chosen on the left (the window calls this when a book's page is chosen)."""
        i = self.scope_box.findText(book)
        if i >= 0 and i != self.scope_box.currentIndex():
            self.scope_box.setCurrentIndex(i)

    def scope_changed(self, index):
        """A new scope: its norms, its strip's verses, and its sets."""
        if self.data is None or index < 0:
            return
        scope = self.scope_box.currentText()
        self.norm_box.blockSignals(True)
        self.norm_box.clear()
        for norm in self.data.set_norms(self.run_id, scope):
            label = NORM_NAMES.get(norm, norm) if scope not in ("Old", "New") else "against itself"
            self.norm_box.addItem(label, norm)
        self.norm_box.blockSignals(False)
        self.strip.set_verses(self.data.scope_verses(scope))
        self.refresh()

    def filters(self):
        """The filter as the boxes stand: (scope, norm, kind, size, closed only, root)."""
        return (self.scope_box.currentText(), self.norm_box.currentData(), self.kind_box.currentData(),
                self.size_box.currentData(), self.closed_box.isChecked(), self.root_edit.text().strip())

    def filter_line(self):
        """The filter in words, for the count line and the head of a saved file."""
        scope, norm, kind, size, closed, root = self.filters()
        parts = [scope, NORM_NAMES.get(norm, norm or ""), kind and f"{kind}s" or "every kind",
                 f"size {size}" if size else "every size", "closed sets only" if closed else "every set"]
        if root:
            parts.append(f"holding '{root}'")
        return ", ".join(p for p in parts if p)

    def refresh(self, *_):
        """Fill the grid from the stored rows that match the boxes."""
        if self.data is None or not self.data.has_sets() or self.norm_box.currentData() is None:
            return
        scope, norm, kind, size, closed, root = self.filters()
        self.rows, self.total = self.data.sets(self.run_id, scope, norm, kind, size, closed, root or None, LIMIT)
        self.grid.setSortingEnabled(False)
        self.grid.clearSelection()
        self.grid.setRowCount(len(self.rows))
        for r, s in enumerate(self.rows):
            cells = [
                SetItem(s["words"]), SetItem(str(s["size"]), s["size"]), SetItem(s["kind"]),
                SetItem(str(s["support"]), s["support"]), SetItem(str(s["stretches"]), s["stretches"]),
                SetItem(f"{s['expected']:.1f}", s["expected"]), SetItem(f"{s['lift']:.1f}", s["lift"]),
                SetItem(f"{s['keyness']:.1f}", s["keyness"]), SetItem(str(s["span"]), s["span"]),
                SetItem(f"{s['in_order']:.0%}", s["in_order"]), SetItem("yes" if s["inclusio"] else "",
                                                                         1 if s["inclusio"] else 0),
                SetItem(str(s["folds"]) if s["folds"] else "", s["folds"]),
            ]
            for c, item in enumerate(cells):
                item.setData(Qt.ItemDataRole.UserRole, r)
                item.setToolTip(s["roots"])          # the Strong's numbers behind the row
                self.grid.setItem(r, c, item)
        self.grid.setSortingEnabled(True)          # sorts by the column the reader last chose (keyness at first)
        shown = len(self.rows)
        self.count_label.setText(f"{self.total:,} set{'s' if self.total != 1 else ''} match ({self.filter_line()})"
                                 + (f"; the {shown} strongest are shown" if self.total > shown else ""))
        self.chosen = None
        self.place_list.clear()
        self.text_view.setPlainText("")
        self.strip.show_places("", [])
        self.strip_label.setText("Choose a set to see where it gathers.")
        if self.rows:
            # Cleared first: a row already selected before the refill would
            # send no signal, and the places below would stay empty
            self.grid.clearSelection()
            self.grid.selectRow(0)

    # --- a chosen set ------------------------------------------------------------
    def row_of(self, grid_row):
        item = self.grid.item(grid_row, 0)
        return None if item is None else self.rows[item.data(Qt.ItemDataRole.UserRole)]

    def set_chosen(self):
        """A row chosen: its places as ranges, its strip, and the sets folded under it."""
        selected = self.grid.selectionModel().selectedRows() if self.grid.selectionModel() else []
        if not selected or self.data is None:
            return
        s = self.row_of(selected[0].row())
        if s is None:
            return
        self.chosen = s
        places = self.data.set_windows(s["set_id"])
        self.strip.show_places(s["words"], places)
        self.strip_label.setText(f"Where {s['words']} gather: {len(places)} place{'s' if len(places) != 1 else ''}"
                                 + ("  (an inclusio: at both ends of the book)" if s["inclusio"] else ""))
        self.place_list.clear()
        for place in places:
            book, c1, v1, c2, v2 = place
            chapters = f"chapter {c1}" if c1 == c2 else f"chapters {c1}-{c2}"
            item = QListWidgetItem(f"{span_text(place)}   ({chapters})")
            item.setData(Qt.ItemDataRole.UserRole, place)
            self.place_list.addItem(item)
        folded = self.data.set_folded(s["set_id"])
        if folded:
            head = QListWidgetItem(f"Folded under it ({len(folded)}): smaller sets with the same support")
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            self.place_list.addItem(head)
            for f in folded:
                item = QListWidgetItem(f"   {f['words']}   (support {f['support']}, keyness {f['keyness']:.1f})")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(f["roots"])
                self.place_list.addItem(item)
        if places:
            self.place_list.setCurrentRow(0)

    def place_chosen(self, item, *_):
        """A place chosen: its King James verses on the right, with the Strong's numbers when asked."""
        if item is None or self.data is None:
            return
        place = item.data(Qt.ItemDataRole.UserRole)
        if not place:
            return
        book, c1, v1, c2, v2 = place
        num = self.data.book_number(book)
        if num is None or not self.data.has_kjv():
            self.text_view.setPlainText(f"{span_text(place)}\n\nThis dataset holds no King James text.")
            return
        lines = [span_text(place), ""]
        for ch, v, text, tags in self.data.kjv_range(num, c1, v1, c2, v2, tags=self.tags_box.isChecked()):
            lines.append(f"{ch}:{v}  {text}")
            if tags:
                lines.append("        " + "  ".join(f"{w} {n}" for w, n, _m in tags if n))
        self.text_view.setPlainText("\n".join(lines))

    # --- save and copy ----------------------------------------------------------
    def set_line(self, s):
        """One set as a line of text, with every figure the grid shows."""
        return (f"{s['words']}  [{s['roots']}]  size {s['size']}, {s['kind']}, support {s['support']}, "
                f"places {s['stretches']}, expected {s['expected']:.1f}, lift {s['lift']:.1f}, "
                f"keyness {s['keyness']:.1f}, span {s['span']}, in order {s['in_order']:.0%}"
                + (", inclusio" if s["inclusio"] else "") + (f", folds {s['folds']}" if s["folds"] else ""))

    def grid_text(self):
        """The grid as text, in its present order, with the filter line at the head."""
        lines = [f"Constellations: {self.filter_line()}",
                 f"{self.total:,} sets match; {self.grid.rowCount()} shown", ""]
        for r in range(self.grid.rowCount()):
            s = self.row_of(r)
            if s is not None:
                lines.append(self.set_line(s))
        return "\n".join(lines) + "\n"

    def save_text(self):
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save the sets as text",
                                              f"constellations_{self.scope_box.currentText().replace(' ', '_')}.txt",
                                              "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.grid_text())

    def copy_set(self):
        if self.chosen is not None:
            QGuiApplication.clipboard().setText(self.set_line(self.chosen))


def span_text(place):
    """A place as a reference: Revelation 1:1-17, Revelation 20:12-21:11."""
    book, c1, v1, c2, v2 = place
    if (c1, v1) == (c2, v2):
        return f"{book} {c1}:{v1}"
    if c1 == c2:
        return f"{book} {c1}:{v1}-{v2}"
    return f"{book} {c1}:{v1}-{c2}:{v2}"
