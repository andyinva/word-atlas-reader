#!/usr/bin/env python3
"""
reader_themes.py  -  the Themes tab of the Word Atlas Reader

A theme is a set of verses gathered by hand that belong together (the
first is land and inheritance), with a role for every verse:

    core        a verse the theme is about
    borderline  a verse that matches but stands apart from the theme
    excluded    a verse the search found that is not the theme, kept
                with its reason and never counted

The main program (Word Atlas 0.10.109 or later, atlas_themes.py) works
out everything about a theme when it loads it, and the dataset carries
the result: every verse with its role, reason and King James text, and
for every chapter of the canon the counts, the expected counts, the
lift per chapter and the colour to draw it in.  This tab only reads
those rows and draws them.  It never counts, divides or picks a colour:
a cell is painted with the colour stored for it, and a tooltip prints
the numbers stored for it.

    the strip      one cell per chapter in canonical order, one line per
                   book, as the Word Atlas window draws it: light grey
                   ordinary, red over, blue under, grey outside the
                   theme's home range; a short tick where a section of
                   the book begins.  A box switches between core verses
                   and core plus borderline.  Point at a cell for its
                   figures; click it to list that chapter's theme verses
    the verses     every verse of the theme with its role, its reason,
                   the reference as the list wrote it, and its text

A dataset packed before Word Atlas 0.10.109 holds no themes; the tab
then says so.

Author: Andrew Hopkins (with Claude)
"""

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                             QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QToolTip,
                             QVBoxLayout, QWidget)


def number_text(value, places=2):
    """A stored number as text, or a dash when the row stores none (outside the home range)."""
    return "-" if value is None else f"{value:.{places}f}"


class ThemeStripChart(QWidget):
    """
    The theme's strip: one line per book, one cell per chapter, each cell
    painted with its stored colour.  Signals the strip position clicked.
    """

    clicked = pyqtSignal(int)            # the chapter's position in canonical order

    CELL_W, CELL_H, GAP, TOP = 6, 11, 3, 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.lines = []              # [(book, [cell dict, ...])], as stored
        self.with_borderline = False
        self.selected = None         # the position clicked, outlined
        self.empty_text = "No theme to draw."
        self.label_w = 60
        self.setMinimumHeight(60)

    def set_cells(self, cells):
        """Take a theme's stored strip rows (one dict per chapter) and lay them out a line per book."""
        self.lines = []
        for cell in cells:
            if not self.lines or self.lines[-1][0] != cell["book"]:
                self.lines.append((cell["book"], []))
            self.lines[-1][1].append(cell)
        self.selected = None
        metrics = self.fontMetrics()
        self.label_w = max((metrics.horizontalAdvance(b) for b, _ in self.lines), default=48) + 12
        widest = max((len(c) for _, c in self.lines), default=1)
        if self.lines:
            self.setFixedSize(self.label_w + widest * self.CELL_W + 12,
                              self.TOP + len(self.lines) * (self.CELL_H + self.GAP) + 8)
        else:
            self.setFixedSize(400, 60)
        self.update()

    def set_with_borderline(self, on):
        """Paint the core colours, or the core plus borderline colours (both are stored)."""
        self.with_borderline = bool(on)
        self.update()

    def cell_at(self, point):
        """The stored cell under a point, or None."""
        line = (point.y() - self.TOP) // (self.CELL_H + self.GAP)
        if point.y() < self.TOP or point.x() < self.label_w or not 0 <= line < len(self.lines):
            return None
        col = (point.x() - self.label_w) // self.CELL_W
        cells = self.lines[line][1]
        return cells[col] if 0 <= col < len(cells) else None

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        if not self.lines:
            p.setPen(QColor("#6b6a66"))
            p.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignmentFlag.AlignLeft, self.empty_text)
            p.end()
            return
        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)
        key = "colour_all" if self.with_borderline else "colour_core"
        for i, (book, cells) in enumerate(self.lines):
            y = self.TOP + i * (self.CELL_H + self.GAP)
            p.setPen(QColor("#333333"))
            p.drawText(QRect(0, y - 2, self.label_w - 6, self.CELL_H + 4),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, book)
            for j, cell in enumerate(cells):
                x = self.label_w + j * self.CELL_W
                # The colour the main program stored for this cell, as it is
                p.fillRect(QRect(x, y, self.CELL_W - 1, self.CELL_H), QColor(cell[key]))
                if cell["section_start"]:
                    # A section of the book begins here: a short dark tick under the cell
                    p.fillRect(QRect(x, y + self.CELL_H, 2, self.GAP), QColor("#2b2b29"))
                if cell["position"] == self.selected:
                    p.setPen(QColor("#d04000"))
                    p.drawRect(QRect(x - 1, y - 1, self.CELL_W, self.CELL_H + 1))
        p.end()

    def tip(self, cell):
        """The stored figures of one chapter, written out for the tooltip."""
        text = f"{cell['book']} {cell['chapter']}"
        if cell["section"]:
            text += f" ({cell['section']})"
        text += f": {cell['core']} core, {cell['all_verses']} with borderline, of {cell['chapter_verses']} verses"
        if cell["in_home"]:
            text += (f"\nexpected {number_text(cell['expected_core'])} core, "
                     f"{number_text(cell['expected_all'])} with borderline"
                     f"\nlift {number_text(cell['lift_core'])} core, {number_text(cell['lift_all'])} with borderline")
        else:
            text += "\noutside the theme's home range: no lift"
        if cell["all_verses"]:
            text += "\nClick to list these verses below."
        return text

    def mouseMoveEvent(self, event):
        cell = self.cell_at(event.position().toPoint())
        if cell is None:
            QToolTip.hideText()
            return
        QToolTip.showText(event.globalPosition().toPoint(), self.tip(cell), self)

    def mousePressEvent(self, event):
        cell = self.cell_at(event.position().toPoint())
        if cell is not None:
            self.selected = cell["position"]
            self.update()
            self.clicked.emit(cell["position"])


class ThemeTab(QWidget):
    """The Themes tab: a theme's strip and its verses, read from the dataset."""

    VERSE_COLUMNS = ["reference", "role", "reason", "as written", "text"]

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.data = None
        self.theme = None            # the chosen theme's stored row
        self.cells = {}              # position -> stored strip row
        box = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setProperty("help", "theme_note")
        box.addWidget(self.note)
        # The theme to show, and core or core plus borderline
        row = QHBoxLayout()
        row.addWidget(QLabel("Theme:"))
        self.theme_box = QComboBox()
        self.theme_box.setProperty("help", "theme_box")
        self.theme_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.theme_box.setMinimumContentsLength(20)
        self.theme_box.currentIndexChanged.connect(self.theme_changed)
        row.addWidget(self.theme_box, 1)
        self.borderline_box = QCheckBox("count the borderline verses too")
        self.borderline_box.setProperty("help", "theme_borderline")
        self.borderline_box.toggled.connect(self.borderline_toggled)
        row.addWidget(self.borderline_box)
        box.addLayout(row)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setProperty("help", "theme_summary")
        box.addWidget(self.summary)
        # The strip above, the verses below
        split = QSplitter(Qt.Orientation.Vertical)
        self.chart = ThemeStripChart()
        self.chart.setProperty("help", "theme_strip")
        self.chart.clicked.connect(self.chapter_clicked)
        scroll = QScrollArea()
        scroll.setWidget(self.chart)
        scroll.setWidgetResizable(False)
        split.addWidget(scroll)
        lower = QWidget()
        lower_box = QVBoxLayout(lower)
        lower_box.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.verses_label = QLabel("Verses")
        head.addWidget(self.verses_label, 1)
        self.all_button = QPushButton("Every verse of the theme")
        self.all_button.setProperty("help", "theme_all")
        self.all_button.clicked.connect(self.show_all_verses)
        head.addWidget(self.all_button)
        lower_box.addLayout(head)
        self.grid = QTableWidget(0, len(self.VERSE_COLUMNS))
        self.grid.setHorizontalHeaderLabels(self.VERSE_COLUMNS)
        self.grid.setProperty("help", "theme_verses")
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setWordWrap(True)
        self.grid.verticalHeader().setVisible(False)
        header = self.grid.horizontalHeader()
        for c in range(len(self.VERSE_COLUMNS) - 1):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(self.VERSE_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        lower_box.addWidget(self.grid, 1)
        self.footer = QLabel()
        self.footer.setWordWrap(True)
        self.footer.setObjectName("note")
        lower_box.addWidget(self.footer)
        split.addWidget(lower)
        split.setSizes([520, 300])
        box.addWidget(split, 1)
        self.set_dataset(None)

    # --- filling --------------------------------------------------------------
    def set_dataset(self, data):
        """Fill the tab from a newly opened dataset (or empty it)."""
        self.data = data
        self.theme_box.blockSignals(True)
        self.theme_box.clear()
        self.theme_box.blockSignals(False)
        self.theme = None
        self.cells = {}
        self.chart.set_cells([])
        self.grid.setRowCount(0)
        self.summary.setText("")
        self.footer.setText("")
        if data is None:
            self.note.setText("Open a dataset to see its themes.")
            return
        themes = data.themes()
        if not themes:
            self.note.setText("This dataset holds no themes: it was packed before Word Atlas 0.10.109, or the "
                              "atlas it was packed from had none.  Pack it again after loading a theme "
                              "(themes/ in the main program).")
            self.chart.empty_text = "No themes in this dataset."
            self.chart.update()
            return
        self.note.setText("A theme is a set of verses gathered by hand.  The strip shows where the Bible holds "
                          "more of it than a chapter's length would give it by chance: red is over, light grey "
                          "ordinary, blue under, grey outside the theme's home range.  Every figure is the one "
                          "the main program stored; point at a cell for them, click it for its verses.")
        self.theme_box.blockSignals(True)
        for t in themes:
            self.theme_box.addItem(t["name"], t["theme_id"])
        self.theme_box.blockSignals(False)
        self.theme_box.setCurrentIndex(0)
        self.theme_changed(0)

    def theme_changed(self, index):
        """Show the chosen theme: its stored summary, strip and verses."""
        if self.data is None or index < 0:
            return
        tid = self.theme_box.itemData(index)
        self.theme = next((t for t in self.data.themes() if t["theme_id"] == tid), None)
        if self.theme is None:
            return
        t = self.theme
        cells = self.data.theme_strip(tid)
        self.cells = {c["position"]: c for c in cells}
        self.chart.set_cells(cells)
        self.chart.set_with_borderline(self.borderline_box.isChecked())
        self.summary.setText(
            f"{t['name']}: core {t['n_core']}, borderline {t['n_borderline']}, excluded {t['n_excluded']}; "
            f"{t['n_chapters']} chapters hold a theme verse.  Home range {t['home_label']}, cushion "
            f"{t['cushion']:g}: lift per chapter = (theme verses + cushion) / (expected + cushion).  "
            f"From {t['file']}, loaded into {t['build']}.")
        problems = self.data.theme_problems(tid)
        terms = self.data.theme_terms(tid)
        lines = []
        if problems:
            lines.append("Not placed in the atlas: " + "; ".join(f"{r} ({why})" for r, why in problems))
        if terms:
            lines.append("Companion terms: " + ", ".join(s or r for s, r, _n in terms))
        self.footer.setText("\n".join(lines))
        self.show_all_verses()

    def borderline_toggled(self, on):
        self.chart.set_with_borderline(on)

    # --- the verses -------------------------------------------------------------
    def fill_grid(self, verses, heading):
        """List stored verse rows in the table."""
        self.verses_label.setText(heading)
        self.grid.setRowCount(len(verses))
        for r, v in enumerate(verses):
            ref = f"{v['book']} {v['chapter']}:{v['verse']}"
            for c, value in enumerate([ref, v["role"], v["reason"], v["as_written"], v["text"]]):
                item = QTableWidgetItem(str(value or ""))
                if c == 4:
                    item.setToolTip(str(value or ""))
                self.grid.setItem(r, c, item)
        self.grid.resizeRowsToContents()

    def show_all_verses(self):
        """Every verse of the theme, core, borderline and excluded, in canonical order."""
        if self.theme is None:
            return
        verses = self.data.theme_verses(self.theme["theme_id"])
        self.fill_grid(verses, f"Every verse of {self.theme['name']} ({len(verses)})")

    def chapter_clicked(self, position):
        """A cell clicked: that chapter's theme verses, as stored."""
        cell = self.cells.get(position)
        if cell is None or self.theme is None:
            return
        verses = self.data.theme_verses(self.theme["theme_id"], cell["book"], cell["chapter"])
        name = f"{cell['book']} {cell['chapter']}"
        self.fill_grid(verses, f"{name}: {len(verses)} verse{'s' if len(verses) != 1 else ''} of the theme"
                       if verses else f"{name}: none of the theme")
