#!/usr/bin/env python3
"""
atlas_usb_dialog.py  -  the window over atlas_usb.py

One dialog, the same in Word Atlas (Workbench tab > Install > Build or
update a USB drive) and in the Reader (Tools tab): pick the drive, tick
what goes on it, press the button.  A drive that already carries a
WordAtlas folder is brought up to date: only what changed is copied.

The copying runs on its own thread, so the window stays answerable and
the build can be stopped; what it says goes into the log at the foot.

Run this file on its own to try the dialog:
    python3 atlas_usb_dialog.py

Author: Andrew Hopkins (with Claude)
"""

import os
import sys
import time

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

import atlas_usb


class BuildWorker(QObject):
    """Runs one build (or one check) of a drive away from the window's thread."""

    log = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)        # megabytes done, megabytes in all, the file in hand
    finished = pyqtSignal(bool, str)            # went well?, the closing line

    def __init__(self, drive, options, atlas_dir, reader_dir, pack_from=None, check_only=False):
        super().__init__()
        self.drive = drive
        self.options = dict(options)
        self.atlas_dir = atlas_dir
        self.reader_dir = reader_dir
        self.pack_from = pack_from        # a results.db to pack into a fresh dataset first, or None
        self.check_only = check_only
        self.stop = False
        self._last = 0.0

    def _progress(self, done, total, name):
        # A signal for every megabyte would swamp the window: four a second is plenty
        now = time.monotonic()
        if now - self._last >= 0.25 or done >= total:
            self._last = now
            self.progress.emit(int(done / 1e6), max(int(total / 1e6), 1), name)

    def run(self):
        try:
            if self.check_only:
                bad = atlas_usb.check_drive(self.drive, self.log.emit)
                self.finished.emit(not bad, "The drive is sound." if not bad else
                                   f"{len(bad)} file(s) are missing or damaged: press Update the drive to put them right.")
                return
            if self.pack_from:
                self.options["dataset"] = atlas_usb.pack_dataset(self.pack_from, os.path.dirname(self.pack_from),
                                                                 log=self.log.emit)
            atlas_usb.build(self.drive, self.options, self.atlas_dir, self.reader_dir, log=self.log.emit,
                            progress=self._progress, cancelled=lambda: self.stop)
            self.finished.emit(True, "The drive is ready.")
        except atlas_usb.Cancelled:
            self.finished.emit(False, "Stopped.  What was copied stays on the drive; press the button again to finish.")
        except Exception as e:          # noqa: BLE001  whatever went wrong is said in the window, not lost
            self.log.emit(f"The drive was not finished: {e}")
            self.finished.emit(False, f"The drive was not finished: {e}")


class UsbDialog(QDialog):
    """Pick a drive, tick what goes on it, build it or bring it up to date."""

    def __init__(self, parent=None, dataset=None):
        """dataset: a .wadb to offer first (the one open in the Reader), else the newest found."""
        super().__init__(parent)
        self.setWindowTitle("Build or update a USB drive")
        self.resize(820, 720)
        self.settings = atlas_usb.load_settings()
        # The two programs: where this copy finds them, or where the user said they are
        self.atlas_dir = self._known_dir("atlas_dir", atlas_usb.find_atlas_dir(), "word_atlas.py")
        self.reader_dir = self._known_dir("reader_dir", atlas_usb.find_reader_dir(), "word_atlas_reader.py")
        self.dataset = dataset if dataset and dataset.endswith(".wadb") else \
            atlas_usb.newest_dataset(self.atlas_dir, self.reader_dir)
        self.thread = None
        self.worker = None
        self.data_boxes = {}
        self._build()
        self.refresh_drives()

    def _known_dir(self, key, found, marker):
        """A program folder: the one found beside this program, else one the user pointed to before."""
        if found:
            return found
        saved = self.settings.get(key, "")
        return saved if saved and os.path.exists(os.path.join(saved, marker)) else None

    # --- layout ---------------------------------------------------------------------------
    def _build(self):
        box = QVBoxLayout(self)
        intro = QLabel("A drive made here installs the Word Atlas Reader, Word Atlas, or both, with their data, on a "
                       "Windows or Linux computer.  Everything goes into one folder on the drive, WordAtlas; nothing "
                       "else on the drive is touched.  Press the button again another day and only what has changed "
                       "is copied.")
        intro.setWordWrap(True)
        box.addWidget(intro)

        # The drive
        row = QHBoxLayout()
        row.addWidget(QLabel("Drive:"))
        self.drive_box = QComboBox()
        # A long drive path must not push the two buttons off the row
        self.drive_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.drive_box.setMinimumContentsLength(30)
        self.drive_box.currentIndexChanged.connect(self.drive_changed)
        row.addWidget(self.drive_box, 1)
        refresh = QPushButton("Look again")
        refresh.setToolTip("Look for drives again, after plugging one in")
        refresh.clicked.connect(self.refresh_drives)
        row.addWidget(refresh)
        other = QPushButton("Other folder...")
        other.setToolTip("Make the WordAtlas folder in any folder: a drive not listed, a network share, a trial run")
        other.clicked.connect(self.choose_folder)
        row.addWidget(other)
        box.addLayout(row)
        self.drive_label = QLabel()
        self.drive_label.setWordWrap(True)
        box.addWidget(self.drive_label)

        # The choices sit in a pane that scrolls, so on a small screen
        # they keep their size and the pane gets a scroll bar instead
        # of the boxes being squeezed into one another
        outer = box
        choices = QWidget()
        box = QVBoxLayout(choices)
        box.setContentsMargins(0, 0, 6, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(choices)
        outer.addWidget(scroll, 3)

        # The Reader and its dataset
        group = QGroupBox("The Word Atlas Reader")
        g = QVBoxLayout(group)
        row = QHBoxLayout()
        self.reader_box = QCheckBox()
        self.reader_box.toggled.connect(self.update_plan)
        row.addWidget(self.reader_box, 1)
        self.reader_find = QPushButton("Find...")
        self.reader_find.clicked.connect(lambda: self.find_program("reader"))
        row.addWidget(self.reader_find)
        g.addLayout(row)
        row = QHBoxLayout()
        self.dataset_box = QCheckBox()
        self.dataset_box.toggled.connect(self.update_plan)
        row.addWidget(self.dataset_box, 1)
        choose = QPushButton("Choose...")
        choose.setToolTip("Put a different dataset (.wadb) on the drive")
        choose.clicked.connect(self.choose_dataset)
        row.addWidget(choose)
        g.addLayout(row)
        self.pack_box = QCheckBox("Pack a fresh dataset from results.db first (results.db is newer than the dataset)")
        self.pack_box.toggled.connect(self.update_plan)
        g.addWidget(self.pack_box)
        self.keep_box = QCheckBox("Keep the older datasets already on the drive")
        self.keep_box.setChecked(bool(self.settings.get("keep_old")))
        self.keep_box.toggled.connect(self.update_plan)
        g.addWidget(self.keep_box)
        self.guest_box = QCheckBox("Include the guest key (guest_key.dat), so the copy can ask Claude until its end date")
        self.guest_box.setChecked(bool(self.settings.get("guest_key")))
        g.addWidget(self.guest_box)
        box.addWidget(group)

        # Word Atlas and its databases
        group = QGroupBox("Word Atlas")
        g = QVBoxLayout(group)
        row = QHBoxLayout()
        self.atlas_box = QCheckBox()
        self.atlas_box.toggled.connect(self.atlas_toggled)
        row.addWidget(self.atlas_box, 1)
        self.atlas_find = QPushButton("Find...")
        self.atlas_find.clicked.connect(lambda: self.find_program("atlas"))
        row.addWidget(self.atlas_find)
        g.addLayout(row)
        self.data_label = QLabel("Its program files, the metadata backup and the cross references always go.  "
                                 "The built databases to take as well (rest the pointer on one to read what it is):")
        self.data_label.setWordWrap(True)
        g.addWidget(self.data_label)
        self.data_grid = QGridLayout()
        g.addLayout(self.data_grid)
        box.addWidget(group)

        # PyQt6
        self.wheels_box = QCheckBox("PyQt6 for Windows and Linux, so installing needs no internet "
                                    "(about 180 MB; fetched once, then kept on this computer)")
        self.wheels_box.setChecked(self.settings.get("wheels", True))
        self.wheels_box.toggled.connect(self.update_plan)
        box.addWidget(self.wheels_box)
        box.addStretch(1)
        box = outer                       # what follows is below the scrolling pane again

        self.plan_label = QLabel()
        self.plan_label.setWordWrap(True)
        box.addWidget(self.plan_label)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        box.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("What the build does is listed here.")
        self.log.setMinimumHeight(80)
        box.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.check_button = QPushButton("Check the drive")
        self.check_button.setToolTip("Read every file on the drive back and compare it with what was written")
        self.check_button.clicked.connect(lambda: self.start(check_only=True))
        row.addWidget(self.check_button)
        row.addStretch(1)
        self.build_button = QPushButton("Build the drive")
        self.build_button.setDefault(True)
        self.build_button.clicked.connect(lambda: self.start())
        row.addWidget(self.build_button)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close_or_stop)
        row.addWidget(self.close_button)
        box.addLayout(row)
        self.fill_programs()

    def fill_programs(self):
        """Say which programs were found and what could go with each; called again after Find."""
        # The Reader
        if self.reader_dir:
            self.reader_box.setText(f"Word Atlas Reader {atlas_usb.reader_version(self.reader_dir)}  "
                                    f"({self.reader_dir})")
            self.reader_box.setEnabled(True)
            self.reader_box.setChecked(self.settings.get("reader", True))
        else:
            self.reader_box.setText("The Reader was not found beside this program (Find... says where it is)")
            self.reader_box.setEnabled(False)
            self.reader_box.setChecked(False)
        self.reader_find.setVisible(self.reader_dir is None)
        has_key = bool(self.reader_dir) and os.path.exists(os.path.join(self.reader_dir, "guest_key.dat"))
        self.guest_box.setVisible(has_key)
        self.show_dataset()
        # Word Atlas
        if self.atlas_dir:
            self.atlas_box.setText(f"Word Atlas {atlas_usb.atlas_version(self.atlas_dir)}  ({self.atlas_dir})")
            self.atlas_box.setEnabled(True)
            self.atlas_box.setChecked(self.settings.get("atlas", True))
        else:
            self.atlas_box.setText("Word Atlas was not found beside this program (Find... says where it is)")
            self.atlas_box.setEnabled(False)
            self.atlas_box.setChecked(False)
        self.atlas_find.setVisible(self.atlas_dir is None)
        self.data_label.setVisible(self.atlas_dir is not None)
        # The databases, two to a row, each with its size and its note
        while self.data_grid.count():
            self.data_grid.takeAt(0).widget().deleteLater()
        self.data_boxes = {}
        if self.atlas_dir:
            saved = self.settings.get("atlas_data")
            # The databases that could be ticked when the ticks were last
            # saved.  One that was not there to tick then (atlas_source.db,
            # new in 0.10.92, or a file built since) was never chosen or
            # refused, so it starts as the list says, not unticked
            known = self.settings.get("atlas_data_known") or \
                [k for k, _rel, _default, _note in atlas_usb.ATLAS_DATA if k != "atlas_source.db"]
            for i, d in enumerate(atlas_usb.atlas_data_choices(self.atlas_dir)):
                size = atlas_usb.mb(d["size"]) if d["path"] else "not on this computer"
                check = QCheckBox(f"{d['key']}  ({size})")
                check.setToolTip(d["note"])
                check.setEnabled(d["path"] is not None)
                ticked = d["key"] in saved if saved is not None and d["key"] in known else d["default"]
                check.setChecked(d["path"] is not None and ticked)
                check.toggled.connect(self.update_plan)
                self.data_boxes[d["key"]] = check
                self.data_grid.addWidget(check, i // 2, i % 2)
        self.atlas_toggled(self.atlas_box.isChecked())

    def show_dataset(self):
        """Name the dataset that would go on the drive, and offer a fresh pack when results.db is newer."""
        if self.dataset and os.path.exists(self.dataset):
            self.dataset_box.setText(f"Dataset {os.path.basename(self.dataset)}  "
                                     f"({atlas_usb.mb(os.path.getsize(self.dataset))}; "
                                     f"{atlas_usb.dataset_summary(self.dataset)})")
            self.dataset_box.setEnabled(True)
            self.dataset_box.setChecked(True)
        else:
            self.dataset_box.setText("No dataset (.wadb) found: Choose... picks one, or pack one below")
            self.dataset_box.setEnabled(False)
            self.dataset_box.setChecked(False)
        due = atlas_usb.results_newer_than(self.dataset, self.atlas_dir)
        self.pack_box.setVisible(due)
        self.pack_box.setChecked(due)

    # --- the drive ------------------------------------------------------------------------
    def refresh_drives(self):
        """List the drives plugged in, the one used last time chosen when it is among them."""
        wanted = self.drive_box.currentData() or self.settings.get("drive", "")
        self.drive_box.blockSignals(True)
        self.drive_box.clear()
        for drive in atlas_usb.list_drives():
            self.drive_box.addItem(drive.describe(), drive.path)
        # A folder chosen by hand before stays on offer while it exists
        if wanted and self.drive_box.findData(wanted) < 0 and os.path.isdir(wanted):
            self.drive_box.addItem(atlas_usb.Drive(wanted, "", "folder").describe(), wanted)
        if self.drive_box.count() == 0:
            self.drive_box.addItem("No drive found: plug one in and press Look again, or choose Other folder...", "")
        index = self.drive_box.findData(wanted)
        self.drive_box.setCurrentIndex(index if index >= 0 else 0)
        self.drive_box.blockSignals(False)
        self.drive_changed()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Make the WordAtlas folder inside which folder?",
                                                  self.drive_box.currentData() or os.path.expanduser("~"))
        if folder:
            if self.drive_box.findData(folder) < 0:
                self.drive_box.addItem(atlas_usb.Drive(folder, "", "folder").describe(), folder)
            self.drive_box.setCurrentIndex(self.drive_box.findData(folder))

    def drive_changed(self, index=None):
        """Say what the chosen drive holds now, and name the button to match."""
        drive = self.drive_box.currentData()
        if not drive:
            self.drive_label.setText("")
            self.build_button.setText("Build the drive")
        else:
            self.drive_label.setText(atlas_usb.describe_drive(drive, brief=True))
            holds = bool(atlas_usb.read_manifest(atlas_usb.drive_root(drive)))
            self.build_button.setText("Update the drive" if holds else "Build the drive")
            self.check_button.setEnabled(holds)
        self.update_plan()

    # --- the choices ----------------------------------------------------------------------
    def atlas_toggled(self, on):
        for check in self.data_boxes.values():
            check.setVisible(on)
        self.data_label.setVisible(on and self.atlas_dir is not None)
        self.update_plan()

    def find_program(self, which):
        """Let the user say where the other program is, when it is not in the folder beside this one."""
        marker = "word_atlas.py" if which == "atlas" else "word_atlas_reader.py"
        name = "Word Atlas" if which == "atlas" else "the Word Atlas Reader"
        folder = QFileDialog.getExistingDirectory(self, f"Which folder holds {name} ({marker})?", atlas_usb.PARENT_DIR)
        if not folder:
            return
        if not os.path.exists(os.path.join(folder, marker)):
            QMessageBox.information(self, "Not found", f"{folder} holds no {marker}.")
            return
        if which == "atlas":
            self.atlas_dir = folder
        else:
            self.reader_dir = folder
        self.settings[which + "_dir"] = folder
        if not self.dataset:
            self.dataset = atlas_usb.newest_dataset(self.atlas_dir, self.reader_dir)
        self.fill_programs()

    def choose_dataset(self):
        start = os.path.dirname(self.dataset) if self.dataset else (self.atlas_dir or self.reader_dir or "")
        path, _ = QFileDialog.getOpenFileName(self, "Which dataset goes on the drive?", start,
                                              "Word Atlas datasets (*.wadb)")
        if path:
            self.dataset = path
            self.show_dataset()
            self.pack_box.setChecked(False)
            self.update_plan()

    def options(self):
        """The ticks as the options atlas_usb.build takes."""
        return {
            "reader": self.reader_box.isChecked(),
            "atlas": self.atlas_box.isChecked(),
            "dataset": self.dataset if self.dataset_box.isChecked() else None,
            "atlas_data": [key for key, check in self.data_boxes.items() if check.isChecked() and check.isEnabled()],
            "wheels": self.wheels_box.isChecked(),
            "guest_key": self.guest_box.isVisible() and self.guest_box.isChecked(),
            "keep_old": self.keep_box.isChecked(),
            "verify": False,
        }

    def update_plan(self, *_):
        """One line on what pressing the button would do, and whether the drive has room for it."""
        drive = self.drive_box.currentData()
        if not drive or self.thread is not None:
            if not drive:
                self.plan_label.setText("")
                self.build_button.setEnabled(False)
            return
        options = self.options()
        # The PyQt6 files already fetched stand in for those a build would fetch
        cached = []
        if options["wheels"] and os.path.isdir(atlas_usb.WHEEL_CACHE):
            for name in os.listdir(atlas_usb.WHEEL_CACHE):
                for system, matches in atlas_usb.WHEEL_SYSTEMS:
                    if matches(name):
                        cached.append((system, os.path.join(atlas_usb.WHEEL_CACHE, name)))
        try:
            items, groups = atlas_usb.gather(options, self.atlas_dir, self.reader_dir, cached)
            plan = atlas_usb.make_plan(atlas_usb.drive_root(drive), items, groups, options)
        except OSError as e:
            self.plan_label.setText(f"Could not read the files to copy: {e}")
            return
        need = plan.copy_bytes + (180e6 if options["wheels"] and not cached else 0)
        free = atlas_usb.Drive(drive).free
        text = "Pressing the button: " + plan.summary() + "."
        if options["wheels"] and not cached:
            text += "  PyQt6 is fetched from the internet first (about 180 MB)."
        if self.pack_box.isVisible() and self.pack_box.isChecked():
            text += "  A fresh dataset is packed first and goes in place of the one named above."
        if free and need > free:
            text += f"  THE DRIVE HAS ONLY {atlas_usb.mb(free)} FREE: untick some of the data, or use a larger drive."
        self.plan_label.setText(text)
        self.build_button.setEnabled(bool(options["reader"] or options["atlas"] or options["dataset"]))

    # --- building -------------------------------------------------------------------------
    def start(self, check_only=False):
        drive = self.drive_box.currentData()
        if not drive or self.thread is not None:
            return
        options = self.options()
        if not check_only:
            # Remember the ticks for next time
            self.settings.update({"drive": drive, "reader": options["reader"], "atlas": options["atlas"],
                                  "atlas_data": options["atlas_data"], "wheels": options["wheels"],
                                  "atlas_data_known": [k for k, c in self.data_boxes.items() if c.isEnabled()],
                                  "guest_key": options["guest_key"], "keep_old": options["keep_old"]})
            atlas_usb.save_settings(self.settings)
        pack_from = None
        if not check_only and self.pack_box.isVisible() and self.pack_box.isChecked() and self.atlas_dir:
            pack_from = os.path.join(self.atlas_dir, "reports", "results.db")
        self.log.appendPlainText("")
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)                 # busy until the first figure comes
        self.build_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.close_button.setText("Stop")
        self.thread = QThread(self)
        self.worker = BuildWorker(drive, options, self.atlas_dir, self.reader_dir, pack_from, check_only)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.progress.connect(self.show_progress)
        self.worker.finished.connect(self.finished)
        self.thread.start()

    def show_progress(self, done, total, name):
        self.bar.setRange(0, total)
        self.bar.setValue(min(done, total))
        self.bar.setFormat(f"{name}   %v of %m MB")

    def finished(self, ok, message):
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.worker = None
        self.bar.setVisible(False)
        self.close_button.setText("Close")
        self.log.appendPlainText(message)
        # A dataset packed during the build is the newest one now
        self.dataset = self.dataset if not self.pack_box.isChecked() else \
            (atlas_usb.newest_dataset(self.atlas_dir, self.reader_dir) or self.dataset)
        self.show_dataset()
        self.drive_changed()

    def close_or_stop(self):
        """Close; while a build runs the same button stops it instead."""
        if self.thread is not None:
            self.worker.stop = True
            self.log.appendPlainText("Stopping after the file in hand ...")
        else:
            self.close()

    def closeEvent(self, event):
        if self.thread is not None:
            # Never leave a copy running behind a closed window
            self.worker.stop = True
            self.thread.quit()
            self.thread.wait(15000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    dialog = UsbDialog()
    dialog.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
