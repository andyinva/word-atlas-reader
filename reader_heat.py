#!/usr/bin/env python3
"""
reader_heat.py  -  the Heat tab of the Word Atlas Reader

The heat strips of a book, drawn from the rows a Word Atlas run stored
(the heat_strips, heat_windows and heat_spots tables of a dataset made
by Word Atlas 0.10.101 or later), with the King James text and the
named passages the same dataset carries.  Nothing is counted here: every
figure is the one the main program's atlas_heat.py wrote, so the Reader
shows what run_heat.py's reports and charts show.

    the strips     one row per strip along the book, a cell per window,
                   red for hot, grey for ordinary, blue for cool, as the
                   main program's SVG charts colour them.  Point at a
                   cell for its verses and score; click it to read the
                   window's verses below; point at a strip's name for
                   what it measures (and a word list's words)
    the spots      the chosen strip's hot and cool spots with the words
                   that lit them, at the report's line or at the 'near'
                   line (three quarters of it); double-click one to read
                   its verses
    the text       the King James verses of a window, a spot, a named
                   passage or a reference typed in, with the Strong's
                   numbers of their words when asked

A dataset made before 0.10.101 has no heat rows.  The tab then says so
and which file to open instead, and the text box still works when the
file carries the King James text and the passages.
"""

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
                             QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QToolTip,
                             QVBoxLayout, QWidget)

import re

# The colours of the main program's strip charts (atlas_heat.StripChart):
# blue through grey to red, clamped at z = 3
COOL = (0x2a, 0x78, 0xd6)
MID = (0xf0, 0xef, 0xec)
HOT = (0xe3, 0x49, 0x48)

# How a view (scale, norm) is named in the View box
VIEW_NAMES = {
    ("z", "bible"): "z, against every book of its language (the usual reading)",
    ("percentile", "book"): "percentile, against the book itself",
    ("g2", "bible"): "G2, against every book of its language",
    ("g2", "group"): "G2, against the other books of its own kind",
}
KIND_CHOICES = ["every strip", "measure", "feeling", "feeling family", "word list", "names", "context", "voice"]


def colour(z):
    """The cell colour for a score, as the main program's charts draw it."""
    t = max(-3.0, min(3.0, z)) / 3.0
    end = HOT if t > 0 else COOL
    t = abs(t)
    return QColor(*[round(m + (e - m) * t) for m, e in zip(MID, end)])


def view_name(view):
    scale, norm, size = view
    name = VIEW_NAMES.get((scale, norm), f"{scale}, against {norm}")
    return name + ("" if size == 10 else f", {size}-verse windows")


def verse_span(c1, v1, c2, v2):
    """'23:7-24:2', '23:7-16', '23:7', or for whole chapters (verse 1 to 999) '3' and '3-4'."""
    if v1 == 1 and v2 == WHOLE:
        return f"{c1}" if c1 == c2 else f"{c1}-{c2}"
    if c1 == c2:
        return f"{c1}:{v1}" if v1 == v2 else f"{c1}:{v1}-{v2}"
    return f"{c1}:{v1}-{c2}:{v2}"


# The last verse of a whole chapter asked for ('Ruth 3'); the text lookup stops at the chapter's end
WHOLE = 999


# ---------------------------------------------------------------------------
# The strip chart: painted, not built of widgets, so a book of 1,500
# windows and seventy strips draws at once
# ---------------------------------------------------------------------------

class StripChart(QWidget):
    """One row per strip, one cell per window.  Signals the strip and window clicked."""

    clicked = pyqtSignal(int, int)          # strip row, window position

    LABEL_W = 260
    ROW_H = 18
    GAP = 3
    TOP = 22                                # room for the chapter marks

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.strips = []        # [(name, kind, description, roots)]
        self.windows = []       # per strip: [(position, c1, v1, c2, v2, z)]
        self.book = ""
        self.selected = -1      # the strip row picked
        self.marked = None      # (first position, last position) of a spot to outline
        self.empty_text = "No strips to draw."
        self.setMinimumHeight(60)

    def set_data(self, book, strips, windows):
        self.book, self.strips, self.windows = book, strips, windows
        self.selected = 0 if strips else -1
        self.marked = None
        self.setMinimumHeight(self.TOP + len(strips) * (self.ROW_H + self.GAP) + 10)
        self.update()

    def n_windows(self):
        return max((len(w) for w in self.windows), default=0)

    def cell_width(self):
        return max(0.05, (self.width() - self.LABEL_W - 8) / (self.n_windows() or 1))

    def cell_rect(self, row, pos):
        # A cell's width is the plot's width over the windows, a fraction
        # of a pixel in a long book: neighbours then share a pixel, and
        # each is drawn at least one pixel wide
        width = self.cell_width()
        x = self.LABEL_W + pos * width
        y = self.TOP + row * (self.ROW_H + self.GAP)
        return QRect(int(x), y, max(1, int(x + width) - int(x)), self.ROW_H)

    def hit(self, point):
        """(row, window position) under a point, or (row, -1) on a label, or (-1, -1)."""
        row = (point.y() - self.TOP) // (self.ROW_H + self.GAP)
        if point.y() < self.TOP or row < 0 or row >= len(self.strips):
            return -1, -1
        if point.x() < self.LABEL_W:
            return row, -1
        pos = int((point.x() - self.LABEL_W) / self.cell_width())
        return (row, pos) if 0 <= pos < len(self.windows[row]) else (row, -1)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#fcfcfb"))
        if not self.strips:
            p.setPen(QColor("#6b6a66"))
            p.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignmentFlag.AlignLeft, self.empty_text)
            p.end()
            return
        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)
        # Chapter marks along the top, from the first strip's windows
        first = self.windows[0] if self.windows else []
        last_ch = None
        next_free = 0
        for pos, c1, v1, c2, v2, z in first:
            if c1 != last_ch:
                r = self.cell_rect(0, pos)
                p.setPen(QColor("#b9b7b0"))
                p.drawLine(r.left(), self.TOP - 6, r.left(), self.TOP - 1)
                # A chapter number where there is room for it after the last one written
                if r.left() >= next_free:
                    p.setPen(QColor("#6b6a66"))
                    p.drawText(r.left() + 2, self.TOP - 8, str(c1))
                    next_free = r.left() + p.fontMetrics().horizontalAdvance(str(c1)) + 8
                last_ch = c1
        for row, (name, kind, description, roots) in enumerate(self.strips):
            y = self.TOP + row * (self.ROW_H + self.GAP)
            label = QRect(4, y, self.LABEL_W - 10, self.ROW_H)
            if row == self.selected:
                p.fillRect(label, QColor("#e6e4dc"))
            p.setPen(QColor("#2b2b29"))
            p.drawText(label.adjusted(4, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, label.width() - 6))
            for pos, c1, v1, c2, v2, z in self.windows[row]:
                p.fillRect(self.cell_rect(row, pos), colour(z))
        if self.marked and 0 <= self.selected < len(self.strips):
            a = self.cell_rect(self.selected, self.marked[0])
            b = self.cell_rect(self.selected, self.marked[1])
            p.setPen(QColor("#2b2b29"))
            p.drawRect(QRect(a.left(), a.top() - 1, b.right() - a.left(), a.height() + 1))
        p.end()

    def mouseMoveEvent(self, event):
        row, pos = self.hit(event.position().toPoint())
        if row < 0:
            QToolTip.hideText()
            return
        name, kind, description, roots = self.strips[row]
        if pos < 0:
            text = f"{name} ({kind})\n{description}"
            if roots:
                words = roots.split("\n")
                text += "\n\n" + "\n".join(words[:30]) + (f"\n... and {len(words) - 30} more" if len(words) > 30 else "")
        else:
            _, c1, v1, c2, v2, z = self.windows[row][pos]
            text = f"{name}: {self.book} {verse_span(c1, v1, c2, v2)}, z {z:+.2f}\nClick to read these verses below."
        QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def mousePressEvent(self, event):
        row, pos = self.hit(event.position().toPoint())
        if row >= 0:
            self.selected = row
            self.marked = None
            self.update()
            self.clicked.emit(row, pos)


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------

class HeatTab(QWidget):
    """The Heat tab: the strips of a book, its spots, and the King James text."""

    SPOT_COLUMNS = ["", "verses", "peak", "at", "words that lit it"]

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.data = None
        self.book = None
        self.view = None
        self.strips = []
        self.windows = []
        box = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setProperty("help", "heat_note")
        box.addWidget(self.note)
        row = QHBoxLayout()
        row.addWidget(QLabel("Book:"))
        self.book_box = QComboBox()
        self.book_box.setProperty("help", "heat_book")
        self.book_box.currentIndexChanged.connect(self.book_changed)
        row.addWidget(self.book_box, 1)
        row.addWidget(QLabel("Measured:"))
        self.view_box = QComboBox()
        self.view_box.setProperty("help", "heat_view")
        self.view_box.currentIndexChanged.connect(self.view_changed)
        row.addWidget(self.view_box, 2)
        row.addWidget(QLabel("Show:"))
        self.kind_box = QComboBox()
        self.kind_box.addItems(KIND_CHOICES)
        self.kind_box.setProperty("help", "heat_kind")
        self.kind_box.currentIndexChanged.connect(self.view_changed)
        row.addWidget(self.kind_box)
        box.addLayout(row)

        split = QSplitter(Qt.Orientation.Vertical)
        box.addWidget(split, 1)
        self.chart = StripChart()
        self.chart.setProperty("help", "heat_chart")
        self.chart.clicked.connect(self.chart_clicked)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.chart)
        split.addWidget(scroll)

        lower = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(lower)
        spots = QWidget()
        spots_box = QVBoxLayout(spots)
        spots_box.setContentsMargins(0, 0, 0, 0)
        line_row = QHBoxLayout()
        self.spots_label = QLabel("Spots")
        line_row.addWidget(self.spots_label, 1)
        self.line_box = QComboBox()
        self.line_box.addItem("at the report's line", "spot")
        self.line_box.addItem("at the near line (three quarters of it)", "near")
        self.line_box.setProperty("help", "heat_line")
        self.line_box.currentIndexChanged.connect(self.fill_spots)
        line_row.addWidget(self.line_box)
        spots_box.addLayout(line_row)
        self.spot_grid = QTableWidget()
        self.spot_grid.setColumnCount(len(self.SPOT_COLUMNS))
        self.spot_grid.setHorizontalHeaderLabels(self.SPOT_COLUMNS)
        self.spot_grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.spot_grid.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.spot_grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.spot_grid.horizontalHeader().setStretchLastSection(True)
        self.spot_grid.verticalHeader().setDefaultSectionSize(22)
        self.spot_grid.setProperty("help", "heat_spots")
        self.spot_grid.cellClicked.connect(self.spot_chosen)
        self.spot_grid.cellDoubleClicked.connect(self.spot_chosen)
        spots_box.addWidget(self.spot_grid, 1)
        lower.addWidget(spots)

        text = QWidget()
        text_box = QVBoxLayout(text)
        text_box.setContentsMargins(0, 0, 0, 0)
        find = QHBoxLayout()
        find.addWidget(QLabel("Passage:"))
        self.passage_box = QComboBox()
        self.passage_box.setProperty("help", "heat_passage")
        self.passage_box.activated.connect(self.passage_chosen)
        find.addWidget(self.passage_box, 1)
        text_box.addLayout(find)
        verse_row = QHBoxLayout()
        verse_row.addWidget(QLabel("Verses:"))
        self.verse_edit = QLineEdit()
        self.verse_edit.setPlaceholderText("Genesis 23:7-16, Ruth 3, John 1:1")
        self.verse_edit.setProperty("help", "heat_verses")
        self.verse_edit.returnPressed.connect(self.verses_asked)
        verse_row.addWidget(self.verse_edit, 1)
        show = QPushButton("Show")
        show.clicked.connect(self.verses_asked)
        verse_row.addWidget(show)
        self.tags_check = QCheckBox("Strong's numbers")
        self.tags_check.setProperty("help", "heat_tags")
        self.tags_check.toggled.connect(self.refresh_text)
        verse_row.addWidget(self.tags_check)
        text_box.addLayout(verse_row)
        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setProperty("help", "heat_text")
        text_box.addWidget(self.text_view, 1)
        lower.addWidget(text)
        lower.setSizes([520, 520])
        split.setSizes([480, 320])
        self.last_text = None           # what the text box shows, to redraw with or without tags
        self.set_dataset(None)

    # --- the dataset ----------------------------------------------------------
    def set_dataset(self, data):
        """Fill the tab from a newly opened dataset (or empty it)."""
        self.data = data
        self.book_box.blockSignals(True)
        self.book_box.clear()
        self.passage_box.clear()
        self.text_view.setPlainText("")
        self.last_text = None
        self.spots = []
        self.spots_label.setText("Spots")
        self.spot_grid.setRowCount(0)
        self.chart.empty_text = "No strips to draw."
        if data is None:
            self.note.setText("Open a dataset to see its heat strips.")
            self.book_box.blockSignals(False)
            self.chart.set_data("", [], [])
            self.spot_grid.setRowCount(0)
            return
        for book in data.heat_books():
            self.book_box.addItem(book)
        self.book_box.blockSignals(False)
        if data.has_passages():
            self.passage_box.addItem("(a named passage)", None)
            for pid, name, description in data.passages():
                self.passage_box.addItem(name, pid)
                self.passage_box.setItemData(self.passage_box.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
        else:
            self.passage_box.addItem("(this dataset holds no named passages)", None)
        has_text = data.has_kjv()
        self.verse_edit.setEnabled(has_text)
        if not has_text:
            self.text_view.setPlainText("This dataset holds no King James text: it was packed before Word Atlas "
                                        "0.10.101.  The verses of a window or a spot are named in the tooltips.")
        if not data.has_heat():
            self.note.setText("This dataset has no heat strips: it was made before Word Atlas 0.10.101, which "
                              "began writing them into the results file.  Open a dataset packed by 0.10.101 or "
                              "later (word_atlas_0.10.101_... .wadb) to see them here.")
            self.chart.empty_text = "No heat strips in this dataset (made before Word Atlas 0.10.101)."
            self.chart.set_data("", [], [])
            self.spot_grid.setRowCount(0)
            self.view_box.clear()
            return
        self.note.setText("The heat strips of a book as the main program measured them: red where a strip runs "
                          "hot, blue where it runs cool, grey where it is ordinary.  Point at a cell for its "
                          "verses and score, at a strip's name for what it measures; click a cell to read its "
                          "verses below.")
        if self.book_box.count():
            self.book_box.setCurrentIndex(0)
            self.book_changed(0)

    def show_book(self, book):
        """Show one book, by name (the window calls this when a book's page is chosen)."""
        i = self.book_box.findText(book)
        if i >= 0 and i != self.book_box.currentIndex():
            self.book_box.setCurrentIndex(i)

    def book_changed(self, index):
        if self.data is None or index < 0:
            return
        self.book = self.book_box.itemText(index)
        self.view_box.blockSignals(True)
        self.view_box.clear()
        for view in self.data.heat_views(self.book):
            self.view_box.addItem(view_name(view), view)
        self.view_box.blockSignals(False)
        self.view_changed()

    def view_changed(self, *_):
        if self.data is None or self.book is None or self.view_box.currentIndex() < 0:
            return
        self.view = self.view_box.currentData()
        wanted = self.kind_box.currentText()
        strips = self.data.heat_strips(self.book, self.view)
        if wanted != "every strip":
            strips = [s for s in strips if s[1] == wanted]
        self.strips = strips
        self.windows = [self.data.heat_windows(self.book, self.view, s[0]) for s in strips]
        self.chart.set_data(self.book, strips, self.windows)
        self.fill_spots()

    # --- the spots -------------------------------------------------------------
    def current_strip(self):
        row = self.chart.selected
        return self.strips[row] if 0 <= row < len(self.strips) else None

    def fill_spots(self, *_):
        self.spot_grid.setRowCount(0)
        strip = self.current_strip()
        if strip is None or self.data is None:
            self.spots_label.setText("Spots")
            return
        line = self.line_box.currentData()
        spots = self.data.heat_spots(self.book, self.view, strip[0], line)
        self.spots = spots
        hot = sum(1 for s in spots if s["hot"])
        self.spots_label.setText(f"{strip[0]}: {hot} hot, {len(spots) - hot} cool")
        self.spot_grid.setRowCount(len(spots))
        for r, s in enumerate(spots):
            cells = ["hot" if s["hot"] else "cool", verse_span(s["start_chapter"], s["start_verse"],
                                                               s["end_chapter"], s["end_verse"]),
                     s["peak_shown"], s["peak_at"], s["words"]]
            for c, value in enumerate(cells):
                item = QTableWidgetItem(str(value))
                if c == 0:
                    item.setForeground(colour(3.0 if s["hot"] else -3.0))
                self.spot_grid.setItem(r, c, item)

    def chart_clicked(self, row, pos):
        self.fill_spots()
        if pos >= 0:
            _, c1, v1, c2, v2, z = self.windows[row][pos]
            self.show_verses([(self.book, c1, v1, c2, v2)],
                             f"{self.strips[row][0]}, z {z:+.2f}: {self.book} {verse_span(c1, v1, c2, v2)}")

    def spot_chosen(self, row, col):
        if not 0 <= row < len(getattr(self, "spots", [])):
            return
        s = self.spots[row]
        # Outline the spot on the chosen strip
        windows = self.windows[self.chart.selected]
        inside = [w[0] for w in windows if (w[1], w[2]) >= (s["start_chapter"], s["start_verse"])
                  and (w[3], w[4]) <= (s["end_chapter"], s["end_verse"])]
        self.chart.marked = (min(inside), max(inside)) if inside else None
        self.chart.update()
        self.show_verses([(self.book, s["start_chapter"], s["start_verse"], s["end_chapter"], s["end_verse"])],
                         f"{s['strip']}, {'hot' if s['hot'] else 'cool'} spot {s['span']}, peak {s['peak_shown']} "
                         f"at {s['peak_at']}" + (f": {s['words']}" if s["words"] else ""))

    # --- the text --------------------------------------------------------------
    def passage_chosen(self, index):
        pid = self.passage_box.itemData(index)
        if pid is None or self.data is None:
            return
        ranges = self.data.passage_ranges(pid)
        self.show_verses(ranges, f"{self.passage_box.itemText(index)}: {len(ranges)} ranges")

    def verses_asked(self):
        """Read a reference typed in: 'Genesis 23:7-16', 'Ruth 3', 'John 1:1', several split by ';'."""
        if self.data is None:
            return
        ranges, bad = [], []
        for piece in re.split(r"[;\n]", self.verse_edit.text()):
            r = parse_reference(piece, self.data)
            if r:
                ranges.append(r)
            elif piece.strip():
                bad.append(piece.strip())
        if bad and not ranges:
            self.text_view.setPlainText(f"Not a reference this dataset can read: {'; '.join(bad)}.  "
                                        "Write a book, a chapter and verses: Genesis 23:7-16, Ruth 3, John 1:1.")
            return
        heading = "; ".join(f"{b} {verse_span(c1, v1, c2, v2)}" for b, c1, v1, c2, v2 in ranges)
        if bad:
            heading += f"  (not read: {'; '.join(bad)})"
        self.show_verses(ranges, heading)

    def show_verses(self, ranges, heading):
        self.last_text = (ranges, heading)
        self.refresh_text()

    def refresh_text(self, *_):
        if self.last_text is None or self.data is None:
            return
        ranges, heading = self.last_text
        if not self.data.has_kjv():
            self.text_view.setPlainText(heading + "\n\nThis dataset holds no King James text (packed before "
                                        "Word Atlas 0.10.101).")
            return
        tags = self.tags_check.isChecked()
        out = [heading, ""]
        for book, c1, v1, c2, v2 in ranges:
            num = self.data.book_number(book)
            if num is None:
                out.append(f"{book}: not a book of this dataset")
                continue
            out.append(f"{book} {verse_span(c1, v1, c2, v2)}")
            for ch, v, text, words in self.data.kjv_range(num, c1, v1, c2, v2, tags=tags):
                out.append(f"  {ch}:{v}  {text}")
                if tags and words:
                    out.append("        " + "  ".join(f"{w or '-'} {n}" for w, n, m in words))
            out.append("")
        self.text_view.setPlainText("\n".join(out).rstrip() + "\n")


def parse_reference(text, data):
    """
    (book, c1, v1, c2, v2) from 'Genesis 23:7-16', 'Genesis 23:7-24:2',
    'Ruth 3', 'Ruth 3-4' or 'John 1:1'; None when it cannot be read.
    A whole chapter runs to verse 999, which the text lookup clips.
    """
    m = re.match(r"^\s*((?:[1-3]\s*)?[A-Za-z][A-Za-z ]*?)\s*(\d+)(?::(\d+))?(?:\s*-\s*(\d+)(?::(\d+))?)?\s*$", text)
    if not m:
        return None
    book_text, c1, v1, x, y = m.groups()
    num = data.book_number(book_text)
    if num is None:
        return None
    book = data.book_names().get(num, book_text)
    c1 = int(c1)
    if v1 is None:
        # 'Ruth 3' or 'Ruth 3-4': whole chapters
        return book, c1, 1, int(x) if x else c1, WHOLE
    v1 = int(v1)
    if x is None:
        return book, c1, v1, c1, v1
    if y is None:
        return book, c1, v1, c1, int(x)          # 'Genesis 23:7-16'
    return book, c1, v1, int(x), int(y)          # 'Genesis 23:7-24:2'
