#!/usr/bin/env python3
"""
atlas_usb.py  -  a USB drive that installs Word Atlas and the Reader

A drive made here carries both programs, their data, an installer for
Windows and for Linux, and (when the internet is at hand while the
drive is made) the PyQt6 the programs need, so the computer the drive
is plugged into needs Python and nothing else.  Making the drive again
later is an update: only the files that changed are copied, and files
the drive no longer needs are taken off it.

Everything goes into one folder on the drive, WordAtlas/, and nothing
else on the drive is touched: no formatting, no other folder read or
changed.

    WordAtlas/
        README.txt              what the drive is and how to install from it
        Install-Windows.bat     double-click on Windows
        install-linux.sh        bash install-linux.sh  on Linux
        install.py              the installer both of those start
        usb_manifest.json       what the drive holds, file by file
        programs/word_atlas_reader/     the Reader's program files
        programs/word_atlas/            Word Atlas's program files
        data/reader/                    the dataset (.wadb) the Reader opens
        data/word_atlas/                the built databases chosen for the drive
        wheels/                         PyQt6 for Windows and Linux
        builds/<system>/WordAtlasReader a built Reader (PyInstaller), when one exists

This file is the same in the Word Atlas folder and in the Reader's
folder, and works from either: it finds the other program in the
folder beside its own (word_atlas beside word_atlas_reader).  It is
standard library only; atlas_usb_dialog.py is the window over it.

    python3 atlas_usb.py drives
        the drives plugged in, with their free space

    python3 atlas_usb.py status DRIVE
        what a drive holds now, and what a build would change

    python3 atlas_usb.py build DRIVE [--no-reader] [--no-atlas] [--no-wheels]
                                     [--data atlas.db,lxx.db,...] [--dataset FILE.wadb]
                                     [--guest-key] [--keep-old] [--verify]
        make the drive, or bring it up to date; DRIVE is the drive's
        folder (/media/andrew/KINGSTON, E:\\) or any folder at all

Author: Andrew Hopkins (with Claude)
"""

import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

# The folder this file is in: the Word Atlas folder or the Reader's
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(HERE)


def source_of_build():
    """
    For a built copy (PyInstaller) run from the folder it was built in,
    word_atlas_reader/dist/WordAtlasReader, the source folder two
    levels up, where the program files a drive needs are; None for a
    copy run from its source, or a built copy that has been moved.
    """
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    dist = os.path.dirname(exe_dir)
    if os.path.basename(dist).lower() != "dist":
        return None
    return os.path.dirname(dist)

FORMAT = "Word Atlas USB drive"
FORMAT_VERSION = 1
DRIVE_FOLDER = "WordAtlas"            # the one folder made on the drive
MANIFEST_NAME = "usb_manifest.json"
INSTALLER_SOURCE = "usb_install.py"   # beside this file; copied to the drive as install.py

# Where this computer keeps the PyQt6 files it has fetched (so a second
# drive does not fetch them again) and the choices last made in the window
USB_HOME = os.path.join(os.path.expanduser("~"), ".word_atlas_usb")
WHEEL_CACHE = os.path.join(USB_HOME, "wheels")
SETTINGS_PATH = os.path.join(USB_HOME, "settings.json")

# The systems the drive carries PyQt6 for: (name on the drive, how a
# wheel file for it is recognised by its file name)
WHEEL_SYSTEMS = [
    ("linux", lambda name: "manylinux" in name and name.endswith("x86_64.whl")),
    ("windows", lambda name: name.endswith("win_amd64.whl")),
]
PYPI_URL = "https://pypi.org/pypi/{name}/json"

# Word Atlas's files that are built, private or too large to be program
# files.  The built databases go on the drive only when chosen (see
# ATLAS_DATA below); the rest never go.
ATLAS_NOT_PROGRAM = {"atlas.db", "atlas_source.db", "lxx.db", "bibles.db", "metadata.db", "translations.db", "translations_index.db",
                     "sefaria_links.db", "richness_cache.json", "test_bibles.db", "lxx_backup.db",
                     "metadata_test_backup.db", "strongs_export.tsv.gz", "strongs.csv"}
# Program files are the top-level files with these endings, and these names
PROGRAM_ENDINGS = (".py", ".md", ".txt", ".tsv", ".spec")
ATLAS_EXTRA_FILES = ("metadata_backup.sql", "cross_references.db", "LICENSE")
READER_EXTRA_FILES = ("LICENSE",)

# The built databases Word Atlas can take along.  Each: the key used on
# the command line and in the settings, the path under the Word Atlas
# folder, whether it is ticked the first time, and a line saying what
# it is.  Those left unticked at first are the ones whose sources ask
# for care before a copy is handed to someone else.
ATLAS_DATA = [
    ("atlas.db", "atlas.db", True,
     "the atlas itself: every page is read from it"),
    ("translations_index.db", "translations_index.db", True,
     "the other translations as witnesses (the translations and families columns)"),
    ("strongs.csv", "strongs.csv", True,
     "the Strong's dictionary (strongs3 project, MIT licence)"),
    ("atlas_source.db", "atlas_source.db", True,
     "Word Atlas's own Bible text, taken out of bibles.db by atlas_source.py: the King James with its "
     "Strong's numbers and the translations free of copyright.  With it an installed copy can rebuild "
     "its atlas and needs no bibles.db.  Not here yet?  Builds > Take Word Atlas's own text out of "
     "bibles.db makes it"),
    ("lxx.db", "lxx.db", False,
     "the Greek and Hebrew layer.  Holds Rahlfs' Septuagint (CC BY-NC-SA: pass it on with its credit, "
     "never for sale) and STEPBible's texts (CC BY)"),
    ("sefaria_links.db", "sefaria_links.db", False,
     "the rabbinic library's pairs (the cited column).  Confirm Sefaria's licence on the links before "
     "giving a copy away"),
    ("results.db", os.path.join("reports", "results.db"), False,
     "the results database behind the Results menu.  Large; the Reader's dataset already carries its pages"),
]
# bibles.db, Bible Search Lite's whole database, was on this list until
# 0.10.93.  Word Atlas no longer reads it once atlas_source.db is made
# (the parts it needs are in that file), and it holds translations
# still under copyright, so the drive does not offer to carry it.


class Cancelled(Exception):
    """Raised inside a build when the user presses Cancel."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def mb(n):
    """A byte count as megabytes, for the log."""
    return f"{n / 1e6:.1f} MB"


def read_version(path):
    """The VERSION = "..." line of a program file, or '' when there is none."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r'VERSION\s*=\s*"([^"]+)"', line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ""


def resource_path(name):
    """
    A file that travels with this module: beside it when the program
    runs from source, in PyInstaller's unpacked folder when it runs as
    a built copy.
    """
    path = os.path.join(HERE, name)
    if os.path.exists(path):
        return path
    return os.path.join(getattr(sys, "_MEIPASS", HERE), name)


def load_settings():
    """The choices last made in the USB window, empty the first time."""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    os.makedirs(USB_HOME, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


# ---------------------------------------------------------------------------
# The two programs: where they are and what files they are made of
# ---------------------------------------------------------------------------

def home_app():
    """Which program this copy of the file sits in: 'atlas' or 'reader'."""
    return "atlas" if os.path.exists(os.path.join(HERE, "word_atlas.py")) else "reader"


def find_atlas_dir():
    """The Word Atlas folder: this one, or word_atlas beside the Reader; None when it is not there."""
    candidates = [HERE, os.path.join(PARENT_DIR, "word_atlas")]
    built = source_of_build()
    if built:
        # A built Reader: Word Atlas beside the Reader's source folder
        candidates.append(os.path.join(os.path.dirname(built), "word_atlas"))
    for folder in candidates:
        if os.path.exists(os.path.join(folder, "word_atlas.py")) and os.path.exists(os.path.join(folder, "atlas_pages.py")):
            return folder
    return None


def find_reader_dir():
    """The Reader's folder: this one (when this is the Reader), or word_atlas_reader beside Word Atlas."""
    candidates = [os.path.join(PARENT_DIR, "word_atlas_reader")]
    if home_app() == "reader":
        candidates.insert(0, HERE)
    # A built copy has no program files beside it: its source folder,
    # two levels up from dist/WordAtlasReader, has them (0.10.102)
    built = source_of_build()
    if built:
        candidates.insert(0, built)
    for folder in candidates:
        if os.path.exists(os.path.join(folder, "word_atlas_reader.py")) and os.path.exists(os.path.join(folder, "reader_data.py")):
            return folder
    return None


def atlas_version(atlas_dir):
    return read_version(os.path.join(atlas_dir, "atlas_pages.py")) if atlas_dir else ""


def reader_version(reader_dir):
    return read_version(os.path.join(reader_dir, "word_atlas_reader.py")) if reader_dir else ""


def program_files(folder, extras=(), skip=()):
    """
    The program files of a folder: its top-level files with a program
    ending, plus the named extras, less the named skips.  Nothing in a
    subfolder is a program file (builds, reports, data, venv and .git
    all stay where they are).
    """
    out = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or name in skip or name.startswith("."):
            continue
        if name.endswith(PROGRAM_ENDINGS) or name in extras:
            out.append(name)
    return out


def reader_files(reader_dir, guest_key=False):
    """The Reader's program files; the guest key only when asked for."""
    files = program_files(reader_dir, READER_EXTRA_FILES)
    if guest_key and os.path.exists(os.path.join(reader_dir, "guest_key.dat")):
        files.append("guest_key.dat")
    return files


def atlas_files(atlas_dir):
    """Word Atlas's program files, with the metadata backup and the cross references."""
    return program_files(atlas_dir, ATLAS_EXTRA_FILES, skip=ATLAS_NOT_PROGRAM)


def find_strongs_csv(atlas_dir):
    """strongs.csv beside the program or in the strongs3 folder it came in."""
    for path in (os.path.join(atlas_dir, "strongs.csv"),
                 os.path.join(atlas_dir, "strongs3-master", "data_processed", "strongs.csv")):
        if os.path.exists(path):
            return path
    return None


def atlas_data_choices(atlas_dir):
    """
    The built databases that could go on the drive, as dicts: key, the
    file on this computer (None when it is not built here), where it
    goes under the Word Atlas folder, its size, whether it is ticked
    the first time, and its note.
    """
    out = []
    for key, rel, default, note in ATLAS_DATA:
        if key == "strongs.csv":
            path = find_strongs_csv(atlas_dir)
        else:
            path = os.path.join(atlas_dir, rel)
            path = path if os.path.exists(path) else None
        out.append({"key": key, "path": path, "rel": rel, "default": default, "note": note,
                    "size": os.path.getsize(path) if path else 0})
    return out


# ---------------------------------------------------------------------------
# Datasets: the .wadb files the Reader opens
# ---------------------------------------------------------------------------

def newest_dataset(atlas_dir=None, reader_dir=None):
    """
    The newest .wadb this computer has: under Word Atlas's reports/
    first (that is where atlas_pack.py writes them), else the Reader's
    own datasets folder (the copies it keeps of what it has opened),
    else, last of all, the small sample the Reader's tests use.  None
    when there is none.
    """
    for folder in ([os.path.join(atlas_dir, "reports")] if atlas_dir else []) + \
                  ([os.path.join(reader_dir, "datasets"), os.path.join(reader_dir, "sample")] if reader_dir else []):
        if os.path.isdir(folder):
            files = [os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".wadb")]
            if files:
                return max(files, key=os.path.getmtime)
    return None


def results_newer_than(dataset, atlas_dir):
    """True when Word Atlas's results.db was written after the dataset was packed (a fresh pack is due)."""
    results = os.path.join(atlas_dir, "reports", "results.db") if atlas_dir else ""
    if not results or not os.path.exists(results):
        return False
    return dataset is None or os.path.getmtime(results) > os.path.getmtime(dataset) + 1


def pack_dataset(results_path, out_dir, note="", log=print):
    """
    Pack a results.db into a .wadb named after its newest run, the way
    atlas_pack.py does (the same members, the same manifest), without
    needing the main program.  Returns the archive's path.
    """
    db = sqlite3.connect("file:" + results_path.replace("\\", "/") + "?mode=ro", uri=True)
    runs = [{"run_id": r[0], "version": r[1], "started": r[2], "note": r[3],
             "pages": db.execute("SELECT COUNT(*) FROM pages WHERE run_id = ?", (r[0],)).fetchone()[0]}
            for r in db.execute("SELECT run_id, version, started, note FROM runs ORDER BY run_id")]
    db.close()
    if not runs:
        raise ValueError(f"{results_path} holds no run yet")
    newest = runs[-1]
    manifest = {"format": "Word Atlas dataset", "program_version": newest["version"],
                "packed": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note, "runs": runs}
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"word_atlas_{newest['version']}_{newest['started'][:10]}.wadb")
    log(f"Packing {os.path.basename(results_path)} ({mb(os.path.getsize(results_path))}) ...")
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(results_path, "results.db")
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    log(f"  packed into {os.path.basename(out)} ({mb(os.path.getsize(out))})")
    return out


def dataset_summary(path):
    """One line about a .wadb: its runs and pages, from its manifest."""
    try:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        runs = manifest.get("runs", [])
        pages = sum(r.get("pages", 0) for r in runs)
        return f"{len(runs)} run(s), {pages} pages, packed {manifest.get('packed', '?')[:10]}"
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return "a bare results database" if path.endswith(".db") else "not a readable dataset"


# ---------------------------------------------------------------------------
# Drives: what is plugged in
# ---------------------------------------------------------------------------

class Drive:
    """One place a drive could be made: its folder, a name to show, and its room."""

    def __init__(self, path, label="", kind="USB"):
        self.path = path
        self.label = label
        self.kind = kind
        try:
            usage = shutil.disk_usage(path)
            self.total, self.free = usage.total, usage.free
        except OSError:
            self.total = self.free = 0

    def holds_drive(self):
        """True when this drive already carries a WordAtlas folder made here."""
        return os.path.exists(os.path.join(self.path, DRIVE_FOLDER, MANIFEST_NAME))

    def describe(self):
        name = f"{self.label}  " if self.label else ""
        room = f"{self.free / 1e9:.1f} GB free of {self.total / 1e9:.1f} GB" if self.total else "size unknown"
        mark = "  [holds Word Atlas]" if self.holds_drive() else ""
        return f"{name}{self.path}  ({self.kind}, {room}){mark}"


def _linux_drives():
    """Mounted partitions of USB and other removable disks, from lsblk; the media folders when lsblk is missing."""
    drives, seen = [], set()
    try:
        out = subprocess.run(["lsblk", "-J", "-o", "NAME,MOUNTPOINT,RM,HOTPLUG,TRAN,LABEL"],
                             capture_output=True, text=True, timeout=10).stdout
        tree = json.loads(out).get("blockdevices", [])
    except (OSError, ValueError, subprocess.SubprocessError):
        tree = []

    def truthy(value):
        return value in (True, 1, "1", "true")

    def walk(node, removable):
        removable = removable or node.get("tran") == "usb" or truthy(node.get("rm")) or truthy(node.get("hotplug"))
        mount = node.get("mountpoint")
        if removable and mount and mount not in ("/", "[SWAP]") and not mount.startswith(("/boot", "/snap")):
            if mount not in seen:
                seen.add(mount)
                drives.append(Drive(mount, node.get("label") or os.path.basename(mount), "USB"))
        for child in node.get("children", []) or []:
            walk(child, removable)

    for disk in tree:
        walk(disk, False)
    # The folders a desktop mounts removable drives under, for a system
    # without lsblk or a drive lsblk did not mark as removable
    user = os.environ.get("USER") or os.path.basename(os.path.expanduser("~"))
    for base in (f"/media/{user}", f"/run/media/{user}", "/media"):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if os.path.ismount(path) and path not in seen:
                seen.add(path)
                drives.append(Drive(path, name, "mounted"))
    return drives


def _windows_drives():
    """Removable drives first, then fixed drives other than the system's (an external SSD shows as fixed)."""
    import ctypes
    drives = []
    kernel = ctypes.windll.kernel32
    bits = kernel.GetLogicalDrives()
    system = (os.environ.get("SystemDrive") or "C:").upper()
    for i in range(26):
        if not bits & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        kind = kernel.GetDriveTypeW(root)          # 2 removable, 3 fixed
        if kind not in (2, 3) or (kind == 3 and root[:2].upper() == system):
            continue
        label = ctypes.create_unicode_buffer(261)
        kernel.GetVolumeInformationW(root, label, 261, None, None, None, None, 0)
        drives.append(Drive(root, label.value, "USB" if kind == 2 else "fixed disk"))
    drives.sort(key=lambda d: d.kind != "USB")
    return drives


def list_drives():
    """The drives a WordAtlas folder could be made on, most likely first."""
    try:
        if sys.platform.startswith("win"):
            return _windows_drives()
        if sys.platform == "darwin":
            return [Drive(os.path.join("/Volumes", n), n, "volume") for n in sorted(os.listdir("/Volumes"))
                    if os.path.ismount(os.path.join("/Volumes", n)) and not os.path.samefile(os.path.join("/Volumes", n), "/")]
        return _linux_drives()
    except Exception:           # noqa: BLE001  a drive list must never stop the window
        return []


def drive_root(drive_path):
    """The WordAtlas folder of a drive (the path itself when it already ends in WordAtlas)."""
    drive_path = os.path.abspath(os.path.expanduser(drive_path))
    if os.path.basename(drive_path.rstrip("\\/")) == DRIVE_FOLDER:
        return drive_path
    return os.path.join(drive_path, DRIVE_FOLDER)


# ---------------------------------------------------------------------------
# PyQt6 for the drive: found on PyPI, fetched once, kept in a cache
# ---------------------------------------------------------------------------

def _version_tuple(text):
    """'6.11.2' as (6, 11, 2); None for a pre-release or anything not plain numbers."""
    parts = text.split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) else None


def _satisfies(version, spec):
    """Does a version tuple meet a requirement such as '<6.12.0,>=6.11.0'?"""
    for clause in spec.split(","):
        m = re.match(r"\s*(<=|>=|==|<|>)\s*([\d.]+)", clause)
        if not m:
            continue
        op, want = m.group(1), _version_tuple(m.group(2))
        if want is None:
            continue
        n = max(len(version), len(want))
        a, b = version + (0,) * (n - len(version)), want + (0,) * (n - len(want))
        if not {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b}[op]:
            return False
    return True


def _pypi(name):
    """A project's listing on PyPI as a dict."""
    with urllib.request.urlopen(PYPI_URL.format(name=name), timeout=30) as r:
        return json.load(r)


def _wanted(files):
    """Of a release's files, the wheels for the systems the drive serves: [(system, file dict)]."""
    out = []
    for f in files:
        if f.get("yanked") or not f["filename"].endswith(".whl"):
            continue
        for system, matches in WHEEL_SYSTEMS:
            if matches(f["filename"]):
                out.append((system, f))
    return out


def _best_release(listing, spec):
    """The newest plain release meeting the requirement that has a wheel for every system served."""
    best = None
    for text, files in listing.get("releases", {}).items():
        version = _version_tuple(text)
        if version is None or not _satisfies(version, spec):
            continue
        wanted = _wanted(files)
        if {s for s, _ in wanted} != {s for s, _ in WHEEL_SYSTEMS}:
            continue
        if best is None or version > best[0]:
            best = (version, text, wanted)
    return best


def choose_wheels(log=print):
    """
    Decide which wheel files the drive should carry: the newest PyQt6
    with wheels for every system served, the Qt and sip it asks for.
    Returns [(system, file name, url, sha256, size)], and the versions
    as a dict.  Needs the internet; raises OSError without it.
    """
    pyqt = _pypi("PyQt6")
    release = _best_release(pyqt, ">=6.4")
    if release is None:
        raise OSError("PyPI lists no PyQt6 release with wheels for both Windows and Linux")
    version, version_text, pyqt_files = release
    # What this PyQt6 asks of its two companions, from its own metadata
    # when the release is the newest one; else by the usual rule (the
    # same minor version of Qt, any sip of the 13 series)
    requires = pyqt["info"].get("requires_dist") or [] if pyqt["info"].get("version") == version_text else []
    qt_spec = f">={version[0]}.{version[1]}.0,<{version[0]}.{version[1] + 1}.0"
    sip_spec = ">=13.8,<14"
    for req in requires:
        m = re.match(r"\s*(PyQt6[-_]Qt6|PyQt6[-_]sip)\s*\(?([^;)]*)", req, re.IGNORECASE)
        if m and m.group(2).strip():
            if m.group(1).lower().endswith("qt6"):
                qt_spec = m.group(2).strip()
            else:
                sip_spec = m.group(2).strip()
    qt = _best_release(_pypi("PyQt6-Qt6"), qt_spec)
    sip = _best_release(_pypi("PyQt6-sip"), sip_spec)
    if qt is None or sip is None:
        raise OSError("PyPI lists no PyQt6-Qt6 or PyQt6-sip to go with PyQt6 " + version_text)
    chosen = []
    for _, _, wanted in (release, qt, sip):
        for system, f in wanted:
            chosen.append((system, f["filename"], f["url"], f.get("digests", {}).get("sha256", ""), f.get("size", 0)))
    versions = {"PyQt6": version_text, "PyQt6-Qt6": qt[1], "PyQt6-sip": sip[1]}
    log(f"PyQt6 {version_text}, Qt {qt[1]}, sip {sip[1]}: {len(chosen)} files, "
        f"{mb(sum(c[4] for c in chosen))}")
    return chosen, versions


def fetch_wheels(log=print, progress=None, cancelled=None):
    """
    Bring the wheel cache up to date and return ([(system, path)],
    versions).  Files already in the cache with the right checksum are
    not fetched again.  Without the internet the cache is used as it
    stands, and ([], {}) comes back when it is empty.
    """
    os.makedirs(WHEEL_CACHE, exist_ok=True)
    listing_path = os.path.join(WHEEL_CACHE, "chosen.json")
    try:
        chosen, versions = choose_wheels(log)
        with open(listing_path, "w", encoding="utf-8") as f:
            json.dump({"chosen": chosen, "versions": versions}, f)
    except (OSError, ValueError, urllib.error.URLError) as e:
        # No internet, or PyPI not answering: go on with what was fetched before
        try:
            with open(listing_path, encoding="utf-8") as f:
                saved = json.load(f)
            chosen, versions = [tuple(c) for c in saved["chosen"]], saved["versions"]
            log(f"PyPI could not be reached ({e}); using the PyQt6 files fetched earlier")
        except (OSError, ValueError, KeyError):
            log(f"PyPI could not be reached ({e}) and no PyQt6 files were fetched earlier: "
                "the drive will be made without them, and the installer will fetch PyQt6 itself")
            return [], {}
    out = []
    total = sum(c[4] for c in chosen)
    done = 0
    for system, name, url, sha, size in chosen:
        if cancelled and cancelled():
            raise Cancelled()
        path = os.path.join(WHEEL_CACHE, name)
        if not (os.path.exists(path) and (not sha or file_sha256(path) == sha)):
            log(f"  fetching {name} ({mb(size)})")
            part = path + ".part"
            digest = hashlib.sha256()
            try:
                with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
                    while True:
                        if cancelled and cancelled():
                            raise Cancelled()
                        block = r.read(1 << 20)
                        if not block:
                            break
                        f.write(block)
                        digest.update(block)
                        if progress:
                            progress(done + f.tell(), total, "fetching " + name)
            except (OSError, urllib.error.URLError) as e:
                if os.path.exists(part):
                    os.remove(part)
                log(f"  could not fetch {name} ({e}); the drive will be made without PyQt6")
                return [], {}
            except Cancelled:
                os.remove(part)
                raise
            if sha and digest.hexdigest() != sha:
                os.remove(part)
                log(f"  {name} arrived damaged (checksum differs); the drive will be made without PyQt6")
                return [], {}
            os.replace(part, path)
        done += size
        out.append((system, path))
    # Wheels of an older PyQt6 are of no further use in the cache
    keep = {os.path.basename(p) for _, p in out} | {"chosen.json"}
    for name in os.listdir(WHEEL_CACHE):
        if name not in keep:
            try:
                os.remove(os.path.join(WHEEL_CACHE, name))
            except OSError:
                pass
    return out, versions


# ---------------------------------------------------------------------------
# The plan: every file the drive should hold, and where each comes from
# ---------------------------------------------------------------------------

def file_sha256(path):
    """The SHA-256 of a file, read a megabyte at a time."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# Checksums of source files already worked out in this run, keyed by the
# file, its size and its date: the window asks for a plan at every tick
# of a box, and a large database should be read once, not each time
_sha_cache = {}


def source_sha256(item):
    key = (item.src, item.size, item.mtime)
    if key not in _sha_cache:
        _sha_cache[key] = file_sha256(item.src)
    return _sha_cache[key]


class Item:
    """One file bound for the drive: where it is now, where it goes (always with / between folders), its group."""

    def __init__(self, src, rel, group):
        self.src = src
        self.rel = rel.replace("\\", "/")
        self.group = group
        self.size = os.path.getsize(src)
        self.mtime = str(os.stat(src).st_mtime_ns)


def default_options(atlas_dir=None, reader_dir=None):
    """The choices a first build starts from: both programs when found, the newest dataset, PyQt6, the usual data."""
    return {
        "reader": reader_dir is not None,
        "atlas": atlas_dir is not None,
        "dataset": newest_dataset(atlas_dir, reader_dir),      # a .wadb path, or None
        "atlas_data": [d["key"] for d in atlas_data_choices(atlas_dir) if d["default"] and d["path"]] if atlas_dir else [],
        "wheels": True,
        "guest_key": False,       # the Reader's guest_key.dat goes along only when asked
        "keep_old": False,        # keep datasets already on the drive that are not this one
        "sync": True,             # end by flushing every disk, so the drive can be pulled (the tests turn it off)
        "verify": False,          # compare every file by checksum, not by size and date
    }


def gather(options, atlas_dir=None, reader_dir=None, wheels=()):
    """
    The files a build with these options puts on the drive, as Items,
    and the groups the build is answerable for (a group's files that
    are on the drive and no longer wanted are taken off it; groups the
    build leaves out are not touched).
    """
    items, groups = [], set()
    if options.get("reader") and reader_dir:
        groups.add("reader")
        for name in reader_files(reader_dir, options.get("guest_key")):
            items.append(Item(os.path.join(reader_dir, name), "programs/word_atlas_reader/" + name, "reader"))
        # A built Reader (PyInstaller's dist folder), carried for the
        # system it was built on so a computer without Python can run it
        built = os.path.join(reader_dir, "dist", "WordAtlasReader")
        if os.path.isdir(built):
            system = "windows" if sys.platform.startswith("win") else "linux"
            groups.add("build_" + system)
            for root, dirs, files in os.walk(built):
                # The datasets a built copy kept of what it opened are
                # not part of the build: the drive carries the dataset
                # once, under data/reader (0.10.102)
                if root == built:
                    dirs[:] = [d for d in dirs if d != "datasets"]
                for name in files:
                    path = os.path.join(root, name)
                    rel = os.path.relpath(path, built)
                    items.append(Item(path, f"builds/{system}/WordAtlasReader/{rel}", "build_" + system))
    if options.get("dataset"):
        groups.add("dataset")
        path = options["dataset"]
        items.append(Item(path, "data/reader/" + os.path.basename(path), "dataset"))
    if options.get("atlas") and atlas_dir:
        groups.update(("atlas", "atlas_data"))
        for name in atlas_files(atlas_dir):
            items.append(Item(os.path.join(atlas_dir, name), "programs/word_atlas/" + name, "atlas"))
        wanted = set(options.get("atlas_data") or [])
        for d in atlas_data_choices(atlas_dir):
            if d["key"] in wanted and d["path"]:
                items.append(Item(d["path"], "data/word_atlas/" + d["rel"], "atlas_data"))
    if options.get("wheels") and wheels:
        groups.add("wheels")
        for system, path in wheels:
            items.append(Item(path, f"wheels/{system}/{os.path.basename(path)}", "wheels"))
    return items, groups


class Plan:
    """What a build would do: files to copy, files already right, files to take off, and the totals."""

    def __init__(self):
        self.copy, self.same, self.remove = [], [], []

    @property
    def copy_bytes(self):
        return sum(i.size for i in self.copy)

    def summary(self):
        parts = [f"{len(self.copy)} file(s) to copy ({mb(self.copy_bytes)})",
                 f"{len(self.same)} already up to date"]
        if self.remove:
            parts.append(f"{len(self.remove)} no longer needed to take off")
        return ", ".join(parts)


def read_manifest(root):
    """The drive's manifest as a dict, empty when the drive has none (or one that cannot be read)."""
    try:
        with open(os.path.join(root, MANIFEST_NAME), encoding="utf-8") as f:
            manifest = json.load(f)
        return manifest if manifest.get("format") == FORMAT else {}
    except (OSError, ValueError):
        return {}


def make_plan(root, items, groups, options, manifest=None):
    """
    Compare the files wanted with what the drive's manifest says it
    holds.  A file is taken as unchanged when the manifest records the
    same size and source date for it and the copy on the drive is that
    size.  The same size under a different date (a file touched, or
    checked out again by git, with nothing in it changed) is settled
    by the file's checksum against the one the manifest recorded.  With
    the verify option every file on the drive is read and compared by
    checksum instead, which takes as long as reading the whole drive.
    """
    manifest = read_manifest(root) if manifest is None else manifest
    held = manifest.get("files", {})
    plan = Plan()
    wanted = set()
    for item in items:
        wanted.add(item.rel)
        entry = held.get(item.rel)
        target = os.path.join(root, *item.rel.split("/"))
        same = False
        if entry and os.path.exists(target) and os.path.getsize(target) == item.size == entry.get("size"):
            if options.get("verify"):
                same = file_sha256(target) == source_sha256(item)
            elif entry.get("mtime") == item.mtime:
                same = True
            else:
                same = bool(entry.get("sha256")) and source_sha256(item) == entry["sha256"]
        (plan.same if same else plan.copy).append(item)
    for rel, entry in held.items():
        if rel in wanted or entry.get("group") not in groups:
            continue
        if entry.get("group") == "dataset" and options.get("keep_old"):
            continue
        plan.remove.append(rel)
    return plan


# ---------------------------------------------------------------------------
# The installer's files, written fresh on every build
# ---------------------------------------------------------------------------

WINDOWS_BAT = r"""@echo off
rem Word Atlas installer for Windows.  Double-click this file.
rem It finds Python and hands over to install.py in this folder.
rem (Written with goto, not blocks, so a path with brackets in it is safe.)
setlocal
cd /d "%~dp0"
title Word Atlas installer

rem The py launcher first (python.org's installer adds it), then python
rem itself.  Each is tried by running it: on a Windows without Python
rem the name "python" is only a pointer to the Store and fails here.
set PY=
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set PY=py -3
if defined PY goto run
python -c "import sys" >nul 2>nul
if not errorlevel 1 set PY=python
if defined PY goto run
goto nopython

:run
%PY% "%~dp0install.py" %*
echo.
pause
exit /b

:nopython
echo Python was not found on this computer.
echo.
if not exist "%~dp0builds\windows\WordAtlasReader\WordAtlasReader.exe" goto howto
echo This drive carries a built copy of the Word Atlas Reader that needs no Python.
set ANSWER=
set /p ANSWER="Install that copy of the Reader now? [Y/n] "
if /i "%ANSWER%"=="n" goto howto
goto built

:howto
echo To install Word Atlas or the Reader from this drive, first install Python:
echo     1. Go to https://www.python.org/downloads/ and download Python 3.
echo     2. Run it and tick "Add python.exe to PATH" on its first screen.
echo     3. Double-click Install-Windows.bat again.
echo.
pause
exit /b

:built
set DEST=%USERPROFILE%\WordAtlas
echo Copying the Reader to %DEST%\WordAtlasReader ...
robocopy "%~dp0builds\windows\WordAtlasReader" "%DEST%\WordAtlasReader" /E /NFL /NDL /NJH /NJS >nul
rem The dataset goes into the Reader's own datasets folder, where it looks first
if not exist "%DEST%\WordAtlasReader\datasets" mkdir "%DEST%\WordAtlasReader\datasets"
copy /y "%~dp0data\reader\*.wadb" "%DEST%\WordAtlasReader\datasets\" >nul
set DATASET=
for /f "delims=" %%F in ('dir /b /o-d "%DEST%\WordAtlasReader\datasets\*.wadb" 2^>nul') do if not defined DATASET set DATASET=%DEST%\WordAtlasReader\datasets\%%F
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Word Atlas Reader.lnk'); $s.TargetPath='%DEST%\WordAtlasReader\WordAtlasReader.exe'; $s.Arguments='\"%DATASET%\"'; $s.WorkingDirectory='%DEST%\WordAtlasReader'; $s.Save()" >nul 2>nul
echo.
echo Done.  "Word Atlas Reader" is on the Desktop; the program is in %DEST%\WordAtlasReader.
echo.
pause
"""

LINUX_SH = """#!/bin/sh
# Word Atlas installer for Linux.  In a terminal opened in this folder:
#     bash install-linux.sh
# It finds Python 3 and hands over to install.py in this folder.
HERE="$(cd "$(dirname "$0")" && pwd)"
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$HERE/install.py" "$@"
fi
echo "Python 3 was not found.  Install it first (on Ubuntu: sudo apt install python3),"
echo "then run:  bash install-linux.sh"
exit 1
"""


def readme_text(manifest):
    """The README.txt at the top of the drive's folder: what is here and how to install it."""
    lines = ["WORD ATLAS on a drive", "=" * 21, "",
             f"Written {manifest['written']} from {manifest['written_by']}.", "",
             "What this folder holds"]
    reader, atlas = manifest.get("reader"), manifest.get("atlas")
    if reader:
        lines.append(f"  Word Atlas Reader {reader['version']}: a viewer for the results of a Word Atlas run.")
        for d in manifest.get("datasets", []):
            lines.append(f"      dataset {d['name']} ({d['about']})")
    if atlas:
        lines.append(f"  Word Atlas {atlas['version']}: the program that builds the atlas and writes the results.")
        if manifest.get("atlas_data"):
            lines.append("      with " + ", ".join(manifest["atlas_data"]))
    if manifest.get("wheels"):
        lines.append("  PyQt6 " + manifest["wheels"].get("PyQt6", "") + " for Windows and Linux, so installing needs no internet.")
    if manifest.get("builds"):
        lines.append("  A built Reader that needs no Python, for: " + ", ".join(manifest["builds"]) + ".")
    lines += ["",
              "Installing on Windows",
              "  Double-click Install-Windows.bat and answer its questions.",
              "  It needs Python 3.10 or later (python.org; tick \"Add python.exe to PATH\").",
              "",
              "Installing on Linux",
              "  Open a terminal in this folder and type:   bash install-linux.sh",
              "  If the window then fails to open with a message about the \"xcb\" plugin, type",
              "      sudo apt install libxcb-cursor0",
              "  and start the program again.",
              "",
              "Either way the installer asks which program to install (the Reader, Word Atlas,",
              "or both) and where, copies it with its data, sees to PyQt6, and leaves an entry",
              "in the Start menu (Windows: also on the Desktop) to start it by.  Running the",
              "installer again from a newer drive brings an earlier install up to date; your",
              "own files (metadata.db, reports, kept builds, settings) are never replaced.",
              "",
              "Bringing this drive up to date",
              "  In Word Atlas: the Workbench tab, Install menu, \"Build or update a USB drive\".",
              "  In the Reader: the Tools tab, \"Build or update a USB drive\".",
              "",
              "Credits in the data",
              "  The King James text and its Strong's tagging are public domain.  The cross",
              "  references are the OpenBible.info set (CC BY), built on the Treasury of",
              "  Scripture Knowledge.  lxx.db, when present, holds Rahlfs' Septuagint",
              "  (CC BY-NC-SA: pass it on with this credit and never for sale) and STEPBible's",
              "  TAGNT and TAHOT (Tyndale House Cambridge, CC BY 4.0).  The rabbinic links,",
              "  when present, are derived from Sefaria's library (sefaria.org).",
              "",
              "The programs are released under the MIT licence.  Andrew Hopkins, with Claude.",
              ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The build: copy what changed, take off what is no longer wanted, write the manifest
# ---------------------------------------------------------------------------

def _copy_file(src, target, progress, done, total, cancelled):
    """
    Copy one file to the drive through a .part name, so a drive pulled
    out mid-copy never holds half a file under its real name.  Returns
    the file's checksum, worked out as it is read.
    """
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + ".part"
    digest = hashlib.sha256()
    name = os.path.basename(target)
    try:
        with open(src, "rb") as fin, open(part, "wb") as fout:
            while True:
                if cancelled and cancelled():
                    raise Cancelled()
                block = fin.read(1 << 20)
                if not block:
                    break
                fout.write(block)
                digest.update(block)
                done += len(block)
                if progress:
                    progress(done, total, name)
            fout.flush()
            os.fsync(fout.fileno())       # on the drive, not in the computer's memory
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise
    os.replace(part, target)
    return digest.hexdigest()


def _write_text(root, name, text, newline="\n"):
    with open(os.path.join(root, name), "w", encoding="utf-8", newline=newline) as f:
        f.write(text)


def build(drive_path, options, atlas_dir=None, reader_dir=None, log=print, progress=None, cancelled=None):
    """
    Make the drive, or bring it up to date.  drive_path is the drive's
    folder (or any folder); options as default_options() gives them.
    Returns the manifest written.  A build stopped part way leaves the
    drive usable as it was plus the files already copied: the manifest
    is written last and lists only what is really there.
    """
    root = drive_root(drive_path)
    if not os.path.isdir(os.path.dirname(root)):
        raise OSError(f"{os.path.dirname(root)} is not there: is the drive plugged in?")
    installer = resource_path(INSTALLER_SOURCE)
    if not os.path.exists(installer):
        raise OSError(f"{INSTALLER_SOURCE} is missing beside atlas_usb.py: the drive cannot be made without it")
    old = read_manifest(root)
    log(f"{'Updating' if old else 'Making'} {root}")

    # Word Atlas's catalogue travels as its text backup: make sure the
    # backup says what metadata.db says now
    if options.get("atlas") and atlas_dir:
        refresh_metadata_backup(atlas_dir, log)

    wheels, wheel_versions = [], {}
    if options.get("wheels"):
        log("PyQt6 for the drive:")
        wheels, wheel_versions = fetch_wheels(log, progress, cancelled)

    items, groups = gather(options, atlas_dir, reader_dir, wheels)
    plan = make_plan(root, items, groups, options, old)
    log(plan.summary())
    free = shutil.disk_usage(os.path.dirname(root)).free
    # Room is needed for the new copies before the old ones are replaced
    if plan.copy_bytes > free:
        raise OSError(f"The drive has {mb(free)} free and the build needs {mb(plan.copy_bytes)}: "
                      "untick some of the data, or use a larger drive")

    os.makedirs(root, exist_ok=True)
    files = {rel: entry for rel, entry in old.get("files", {}).items()}
    done, total = 0, plan.copy_bytes
    started = time.time()
    try:
        for item in plan.copy:
            target = os.path.join(root, *item.rel.split("/"))
            if item.size > 20e6:
                log(f"  copying {item.rel} ({mb(item.size)})")
            sha = _copy_file(item.src, target, progress, done, total, cancelled)
            done += item.size
            files[item.rel] = {"size": item.size, "mtime": item.mtime, "sha256": sha, "group": item.group}
        for item in plan.same:
            files[item.rel]["group"] = item.group
            files[item.rel]["mtime"] = item.mtime      # a touched file is matched by its date next time
        for rel in plan.remove:
            target = os.path.join(root, *rel.split("/"))
            if os.path.exists(target):
                os.remove(target)
            files.pop(rel, None)
            # A folder left empty by the removal goes too (never the root)
            folder = os.path.dirname(target)
            while folder != root and os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
                folder = os.path.dirname(folder)
        stopped = False
    except Cancelled:
        stopped = True
        log("Stopped.  The files already copied stay on the drive; build again to finish.")

    # The manifest says what the drive holds now, whichever way the build ended
    manifest = _manifest(old, files, options, atlas_dir, reader_dir, wheel_versions, groups, stopped)
    shutil.copyfile(installer, os.path.join(root, "install.py"))
    _write_text(root, "Install-Windows.bat", WINDOWS_BAT, newline="\r\n")
    _write_text(root, "install-linux.sh", LINUX_SH)
    try:
        os.chmod(os.path.join(root, "install-linux.sh"), 0o755)    # no effect on a FAT drive, harmless
    except OSError:
        pass
    _write_text(root, "README.txt", readme_text(manifest), newline="\r\n")
    _write_text(root, MANIFEST_NAME, json.dumps(manifest, indent=1))
    if hasattr(os, "sync") and options.get("sync", True):
        os.sync()                         # everything out of memory and onto the drive
    if stopped:
        raise Cancelled()
    took = time.time() - started
    log(f"Done in {took:.0f}s: {len(plan.copy)} copied ({mb(plan.copy_bytes)}), {len(plan.same)} unchanged"
        + (f", {len(plan.remove)} taken off" if plan.remove else "") + ".")
    log("Eject the drive from the file manager before pulling it out.")
    return manifest


def _manifest(old, files, options, atlas_dir, reader_dir, wheel_versions, groups, stopped):
    """The manifest for the drive as it now stands; what a build left out is carried over from the old one."""
    manifest = {
        "format": FORMAT, "format_version": FORMAT_VERSION,
        "written": time.strftime("%Y-%m-%d %H:%M"),
        "written_by": f"{'Word Atlas' if home_app() == 'atlas' else 'Word Atlas Reader'} on "
                      f"{platform.node() or 'this computer'} ({platform.system()})",
        "complete": not stopped,
        "reader": old.get("reader"), "atlas": old.get("atlas"),
        "wheels": old.get("wheels", {}),
    }
    if "reader" in groups:
        manifest["reader"] = {"version": reader_version(reader_dir)}
    if "atlas" in groups:
        manifest["atlas"] = {"version": atlas_version(atlas_dir)}
    if "wheels" in groups and wheel_versions:
        manifest["wheels"] = wheel_versions
    # These three are read back from the file list, so they are right
    # whatever was copied, kept or taken off
    datasets = sorted(rel for rel, e in files.items() if e.get("group") == "dataset")
    known = {d["name"]: d for d in old.get("datasets", [])}
    manifest["datasets"] = []
    for rel in datasets:
        name = rel.split("/")[-1]
        about = known.get(name, {}).get("about")
        if options.get("dataset") and os.path.basename(options["dataset"]) == name:
            about = dataset_summary(options["dataset"])
        manifest["datasets"].append({"name": name, "about": about or ""})
    manifest["atlas_data"] = sorted(rel[len("data/word_atlas/"):] for rel, e in files.items()
                                    if e.get("group") == "atlas_data")
    manifest["builds"] = sorted({e["group"][len("build_"):] for e in files.values()
                                 if e.get("group", "").startswith("build_")})
    if not any(e.get("group") == "wheels" for e in files.values()):
        manifest["wheels"] = {}
    manifest["files"] = files
    return manifest


def refresh_metadata_backup(atlas_dir, log=print):
    """Write metadata_backup.sql afresh when metadata.db has changed since the last backup (Word Atlas's own tool)."""
    if not os.path.exists(os.path.join(atlas_dir, "metadata.db")):
        return
    try:
        out = subprocess.run([sys.executable, "atlas_backup.py", "status"], cwd=atlas_dir, capture_output=True,
                             text=True, timeout=120)
        if "up to date" in out.stdout.lower() and "not up to date" not in out.stdout.lower():
            return
        done = subprocess.run([sys.executable, "atlas_backup.py", "backup"], cwd=atlas_dir, capture_output=True,
                              text=True, timeout=300)
        if done.returncode == 0:
            log("metadata_backup.sql brought up to date with metadata.db")
    except (OSError, subprocess.SubprocessError):
        pass          # a built copy has no Python to run the tool with; the backup goes as it stands


# ---------------------------------------------------------------------------
# Saying what a drive holds
# ---------------------------------------------------------------------------

def describe_drive(drive_path, brief=False):
    """
    A few lines on what a drive holds, from its manifest; one line
    when it holds nothing yet.  brief: the same in one short paragraph,
    for the window.
    """
    root = drive_root(drive_path)
    manifest = read_manifest(root)
    if not manifest:
        return "This drive holds no Word Atlas files yet." if brief else f"{root}: no Word Atlas files yet."
    if brief:
        parts = []
        if manifest.get("reader"):
            parts.append(f"the Reader {manifest['reader'].get('version', '?')}")
        parts += [d["name"] for d in manifest.get("datasets", [])]
        if manifest.get("atlas"):
            data = ", ".join(manifest.get("atlas_data", []))
            parts.append(f"Word Atlas {manifest['atlas'].get('version', '?')}" + (f" with {data}" if data else ""))
        if manifest.get("wheels"):
            parts.append(f"PyQt6 {manifest['wheels'].get('PyQt6', '?')}")
        if manifest.get("builds"):
            parts.append("a built Reader for " + ", ".join(manifest["builds"]))
        total = sum(e.get("size", 0) for e in manifest.get("files", {}).values())
        return (f"On the drive now (written {manifest.get('written', '?')}): " + "; ".join(parts)
                + f".  {len(manifest.get('files', {}))} files, {mb(total)}."
                + ("" if manifest.get("complete", True) else "  The last build was stopped part way."))
    lines = [f"{root}: written {manifest.get('written', '?')} from {manifest.get('written_by', '?')}"
             + ("" if manifest.get("complete", True) else "  (the last build was stopped part way)")]
    if manifest.get("reader"):
        lines.append(f"  Word Atlas Reader {manifest['reader'].get('version', '?')}")
    for d in manifest.get("datasets", []):
        lines.append(f"  dataset {d['name']}" + (f" ({d['about']})" if d.get("about") else ""))
    if manifest.get("atlas"):
        data = ", ".join(manifest.get("atlas_data", [])) or "no built databases"
        lines.append(f"  Word Atlas {manifest['atlas'].get('version', '?')} with {data}")
    if manifest.get("wheels"):
        lines.append(f"  PyQt6 {manifest['wheels'].get('PyQt6', '?')} for Windows and Linux")
    if manifest.get("builds"):
        lines.append("  a built Reader for " + ", ".join(manifest["builds"]))
    total = sum(e.get("size", 0) for e in manifest.get("files", {}).values())
    lines.append(f"  {len(manifest.get('files', {}))} files, {mb(total)}")
    return "\n".join(lines)


def check_drive(drive_path, log=print):
    """
    Read every file the manifest lists and compare its checksum: is
    the drive sound?  Returns the bad files.  A bad file is struck
    from the manifest, so the next build copies it afresh without
    being asked to verify everything.
    """
    root = drive_root(drive_path)
    manifest = read_manifest(root)
    files = manifest.get("files", {})
    bad = []
    for rel, entry in sorted(files.items()):
        target = os.path.join(root, *rel.split("/"))
        if not os.path.exists(target):
            bad.append((rel, "missing"))
        elif file_sha256(target) != entry.get("sha256"):
            bad.append((rel, "damaged"))
    log(f"{len(files)} files read, " + (f"{len(bad)} bad: " + "; ".join(f"{r} ({why})" for r, why in bad[:10])
                                        if bad else "all sound"))
    if bad:
        for rel, _ in bad:
            files.pop(rel, None)
        manifest["complete"] = False
        _write_text(root, MANIFEST_NAME, json.dumps(manifest, indent=1))
        log("They are marked to be copied again: build the drive once more to put them right.")
    return [f"{rel} ({why})" for rel, why in bad]


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv):
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = args[0]
    flags = {a for a in args if a.startswith("--")}
    values = {a: args[i + 1] for i, a in enumerate(args) if a.startswith("--") and i + 1 < len(args)
              and not args[i + 1].startswith("--")}
    plain = [a for i, a in enumerate(args[1:], 1) if not a.startswith("--") and args[i - 1] not in values]
    atlas_dir, reader_dir = find_atlas_dir(), find_reader_dir()
    if cmd == "drives":
        drives = list_drives()
        for d in drives:
            print(d.describe())
        if not drives:
            print("No removable drive found.  Plug one in, or give any folder to  python3 atlas_usb.py build FOLDER")
        return 0
    if cmd in ("status", "build", "check") and not plain:
        print(f"Which drive?  python3 atlas_usb.py {cmd} DRIVE   (python3 atlas_usb.py drives  lists them)")
        return 1
    if cmd == "check":
        return 1 if check_drive(plain[0]) else 0
    options = default_options(atlas_dir, reader_dir)
    if "--no-reader" in flags:
        options["reader"] = False
        options["dataset"] = None
    if "--no-atlas" in flags:
        options["atlas"] = False
    if "--no-wheels" in flags:
        options["wheels"] = False
    if "--data" in values:
        options["atlas_data"] = [k.strip() for k in values["--data"].split(",") if k.strip()]
    if "--dataset" in values:
        options["dataset"] = os.path.abspath(os.path.expanduser(values["--dataset"]))
    options["guest_key"] = "--guest-key" in flags
    options["keep_old"] = "--keep-old" in flags
    options["verify"] = "--verify" in flags
    if cmd == "status":
        print(describe_drive(plain[0]))
        # What a build would change, without fetching anything
        cached = []
        if options["wheels"] and os.path.isdir(WHEEL_CACHE):
            for name in os.listdir(WHEEL_CACHE):
                for system, matches in WHEEL_SYSTEMS:
                    if matches(name):
                        cached.append((system, os.path.join(WHEEL_CACHE, name)))
        items, groups = gather(options, atlas_dir, reader_dir, cached)
        print("A build now: " + make_plan(drive_root(plain[0]), items, groups, options).summary())
        return 0
    if cmd == "build":
        print(f"Word Atlas: {atlas_dir or 'not found'}" + (f" ({atlas_version(atlas_dir)})" if atlas_dir else ""))
        print(f"Reader:     {reader_dir or 'not found'}" + (f" ({reader_version(reader_dir)})" if reader_dir else ""))
        try:
            build(plain[0], options, atlas_dir, reader_dir)
        except OSError as e:
            print(f"The drive was not made: {e}")
            return 1
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
