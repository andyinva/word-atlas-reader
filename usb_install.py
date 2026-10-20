#!/usr/bin/env python3
"""
The Word Atlas installer  (install.py on a Word Atlas drive)

Installs the Word Atlas Reader, Word Atlas, or both, with their data,
from the folder this file is in to this computer.  It is started by
Install-Windows.bat (Windows) or install-linux.sh (Linux), or directly:

    python3 install.py                     ask what to install and where
    python3 install.py --app reader        the Reader only   (atlas, both)
    python3 install.py --dest FOLDER       install into FOLDER, not ~/WordAtlas
    python3 install.py --yes               take the usual answer to every question
    python3 install.py --force             replace even files that are newer here
    python3 install.py --no-shortcuts      make no menu or Desktop entries
    python3 install.py --no-pyqt           leave PyQt6 alone: no check, nothing unpacked or fetched
    python3 install.py --list              say what the drive holds and stop
    python3 install.py --check             check an install and write its report, copying nothing
                                           (also: python3 usb_install.py --check in the installed
                                           word_atlas_reader folder, without the drive)

Every run ends with an install report (install_report.txt in the
install folder): every installed file checked against the drive's
checksum, the datasets read back, PyQt6 loaded and a window opened, the
starters and menu entries looked for, any error a program left when it
last failed to start, and for each problem what to do about it.  It is
the file to send when asking for help.

What it does, in order: copies the program files and the data (only
the files that differ from what is already installed, so running it
again from a newer drive is an update); makes sure PyQt6 can be found
(the computer's own, else the copy on the drive unpacked into the
install's libs folder, else fetched with pip); writes a starter file
for each program and an entry in the applications menu.

What it never does: replace metadata.db (your own catalogue), touch
reports, kept builds or settings, or delete anything.  A file that is
newer on this computer than on the drive is left alone and named,
unless --force is given.

This file is kept in the program folders as usb_install.py and copied
to a drive as install.py by atlas_usb.py.  Standard library only.

Author: Andrew Hopkins (with Claude)
"""

import ast
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import zipfile

MIN_PYTHON = (3, 10)          # what the programs and the PyQt6 on the drive need
ROOT = os.path.dirname(os.path.abspath(__file__))       # the WordAtlas folder on the drive
MANIFEST_NAME = "usb_manifest.json"
WINDOWS = os.name == "nt"

# The two programs: the key used on the command line, the name shown,
# the folder under programs/ on the drive and under the install folder,
# the script that starts it
APPS = {
    "reader": {"name": "Word Atlas Reader", "folder": "word_atlas_reader", "script": "word_atlas_reader.py",
               "about": "a viewer for the results of a Word Atlas run"},
    "atlas": {"name": "Word Atlas", "folder": "word_atlas", "script": "word_atlas.py",
              "about": "the program that builds the atlas and writes the results"},
}


def say(text=""):
    print(text, flush=True)


def ask(question, default="", yes=False):
    """Ask on the terminal; Enter (or --yes, or no terminal to ask on) takes the default."""
    if yes:
        return default
    try:
        answer = input(question).strip()
    except EOFError:
        return default
    return answer or default


def mb(n):
    return f"{n / 1e6:.1f} MB"


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# What the drive holds
# ---------------------------------------------------------------------------

def load_manifest():
    """The drive's manifest; the installer stops with a plain message when it is missing or unreadable."""
    path = os.path.join(ROOT, MANIFEST_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"This folder has no readable {MANIFEST_NAME} ({e}).\n"
                         "Make the drive again from Word Atlas or the Reader (Build or update a USB drive).")


def files_of(manifest, group):
    """The drive's files of one group, as (path on the drive with / between folders, entry)."""
    return sorted((rel, e) for rel, e in manifest.get("files", {}).items() if e.get("group") == group)


def describe(manifest):
    """The lines that say what can be installed from this drive."""
    lines = [f"This drive was written {manifest.get('written', '?')} from {manifest.get('written_by', '?')}."]
    if manifest.get("reader"):
        data = ", ".join(d["name"] for d in manifest.get("datasets", [])) or "no dataset"
        lines.append(f"  Word Atlas Reader {manifest['reader'].get('version', '?')}, with {data}")
    if manifest.get("atlas"):
        data = ", ".join(manifest.get("atlas_data", [])) or "no built databases"
        lines.append(f"  Word Atlas {manifest['atlas'].get('version', '?')}, with {data}")
    if manifest.get("wheels"):
        lines.append(f"  PyQt6 {manifest['wheels'].get('PyQt6', '?')} for Windows and Linux")
    return lines


# ---------------------------------------------------------------------------
# Copying: only what differs, and never over a file that is newer here
# ---------------------------------------------------------------------------

class Copier:
    """Copies files from the drive, counting what it did and remembering what it left alone."""

    def __init__(self, force=False):
        self.force = force
        self.copied = 0
        self.copied_bytes = 0
        self.same = 0
        self.kept_newer = []          # files newer on this computer, left alone
        self.failed = []              # files that could not be written (the program was running, a full disk)

    def copy(self, rel, entry, target):
        """Bring one file of the drive to target, unless the one there is the same or newer."""
        source = os.path.join(ROOT, *rel.split("/"))
        if not os.path.exists(source):
            say(f"  missing on the drive: {rel}")
            return
        drive_ns = int(entry.get("mtime", "0"))        # the source file's date, in nanoseconds
        drive_time = drive_ns / 1e9
        if os.path.exists(target):
            if os.path.getsize(target) == entry.get("size") and file_sha256(target) == entry.get("sha256"):
                self.same += 1
                return
            # Installed files carry the date of the file they were copied
            # from, so one dated later has been changed on this computer
            if not self.force and os.path.getmtime(target) > drive_time + 2:
                self.kept_newer.append(target)
                return
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if entry.get("size", 0) > 20e6:
            say(f"  copying {os.path.basename(target)} ({mb(entry['size'])}) ...")
        part = target + ".part"
        try:
            shutil.copyfile(source, part)
            os.replace(part, target)
            if drive_ns:
                os.utime(target, ns=(drive_ns, drive_ns))
        except OSError as e:
            # Windows will not replace a file a running program has open
            self.failed.append(f"{target}: {e}")
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
            return
        self.copied += 1
        self.copied_bytes += entry.get("size", 0)


def install_reader(manifest, dest, copier):
    """
    The Reader's program files into dest/word_atlas_reader, and its
    datasets into the datasets folder inside that: the Reader's own
    folder for the datasets it keeps, where it looks when it starts.
    """
    app_dir = os.path.join(dest, APPS["reader"]["folder"])
    prefix = "programs/word_atlas_reader/"
    for rel, entry in files_of(manifest, "reader"):
        copier.copy(rel, entry, os.path.join(app_dir, *rel[len(prefix):].split("/")))
    newest = None
    datasets_dir = os.path.join(app_dir, "datasets")
    for rel, entry in files_of(manifest, "dataset"):
        target = os.path.join(datasets_dir, rel.split("/")[-1])
        copier.copy(rel, entry, target)
        newest = target
    if newest:
        point_reader_at(newest, datasets_dir)
    return app_dir, newest


def point_reader_at(dataset, datasets_dir):
    """
    Make the Reader open the dataset just installed on its next start,
    by setting the last file in its settings.  A last file the reader
    chose elsewhere is left as it is: only no choice yet, a file that
    has gone, or an earlier installed dataset gives way.
    """
    home = os.path.join(os.path.expanduser("~"), ".word_atlas_reader")
    path = os.path.join(home, "settings.json")
    try:
        with open(path, encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError):
        settings = {}
    last = settings.get("last_file", "")
    ours = os.path.abspath(os.path.dirname(last)) == os.path.abspath(datasets_dir) if last else False
    if not last or not os.path.exists(last) or ours:
        settings["last_file"] = dataset
        os.makedirs(home, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    elif os.path.abspath(last) != os.path.abspath(dataset):
        say(f"  The Reader will still open {last} first; the new dataset is {dataset} (File > Open).")


def install_atlas(manifest, dest, copier):
    """Word Atlas's program files and chosen databases into dest/word_atlas; metadata.db from its backup when new."""
    app_dir = os.path.join(dest, APPS["atlas"]["folder"])
    # Where a catalogue is already installed, its text backup is the
    # backup of that catalogue (Word Atlas rewrites it as it closes) and
    # is not the drive's to replace, any more than metadata.db is
    own_catalogue = os.path.exists(os.path.join(app_dir, "metadata.db"))
    for group, prefix in (("atlas", "programs/word_atlas/"), ("atlas_data", "data/word_atlas/")):
        for rel, entry in files_of(manifest, group):
            if own_catalogue and rel == "programs/word_atlas/metadata_backup.sql":
                continue
            copier.copy(rel, entry, os.path.join(app_dir, *rel[len(prefix):].split("/")))
    # The catalogue: built from its text backup the first time only.
    # A metadata.db already here is the user's own and is never replaced.
    if not os.path.exists(os.path.join(app_dir, "metadata.db")) and \
            os.path.exists(os.path.join(app_dir, "metadata_backup.sql")):
        done = subprocess.run([sys.executable, "atlas_backup.py", "restore", "--yes"], cwd=app_dir,
                              capture_output=True, text=True)
        say("  metadata.db made from metadata_backup.sql" if done.returncode == 0 else
            "  metadata.db could not be made from its backup; in Word Atlas use Workbench > Backup > Restore\n    "
            + (done.stderr.strip().splitlines() or [""])[-1])
    if not os.path.exists(os.path.join(app_dir, "atlas.db")):
        say("  Note: this drive carries no atlas.db.  Word Atlas will open on its Workbench tab, where\n"
            "  Builds > Build atlas.db makes one (it needs atlas_source.db, which the drive can carry,\n"
            "  or bibles.db beside the program).")
    return app_dir


# ---------------------------------------------------------------------------
# PyQt6: the computer's own, the drive's, or pip's
# ---------------------------------------------------------------------------

def pyqt_works(libs=None, show=False):
    """Can this Python import PyQt6 (with the libs folder on its path)?  show: also open the display."""
    env = dict(os.environ)
    if libs:
        env["PYTHONPATH"] = libs + os.pathsep + env.get("PYTHONPATH", "")
    code = "import PyQt6.QtWidgets"
    if show:
        code = "from PyQt6.QtWidgets import QApplication; a = QApplication([]); print('display ok')"
    try:
        done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return done.returncode == 0, (done.stderr.strip().splitlines() or [""])[-1]


def drive_wheels():
    """
    The three wheel files on the drive that fit this computer and this
    Python (PyQt6, its Qt, its sip), or [] with the reason when the
    drive has none that fit.
    """
    system = "windows" if WINDOWS else "linux"
    folder = os.path.join(ROOT, "wheels", system)
    if platform.machine().lower() not in ("x86_64", "amd64"):
        return [], f"the drive's PyQt6 is for 64-bit Intel and AMD computers, not {platform.machine()}"
    if not os.path.isdir(folder):
        return [], "the drive carries no PyQt6 for this system"
    names = sorted(os.listdir(folder))
    tag = f"cp{sys.version_info[0]}{sys.version_info[1]}"
    pyqt = [n for n in names if n.lower().startswith("pyqt6-")]
    qt = [n for n in names if n.lower().startswith("pyqt6_qt6-")]
    sip = [n for n in names if n.lower().startswith("pyqt6_sip-") and f"-{tag}-" in n]
    if not (pyqt and qt):
        return [], "the drive carries no PyQt6 for this system"
    if not sip:
        return [], f"the drive's PyQt6 has no part for Python {sys.version_info[0]}.{sys.version_info[1]}"
    # PyQt6's own wheel names the oldest Python it serves (cp310-abi3: 3.10 and later)
    m = re.search(r"-cp(\d)(\d+)-abi3", pyqt[-1])
    if m and sys.version_info[:2] < (int(m.group(1)), int(m.group(2))):
        return [], f"the drive's PyQt6 needs Python {m.group(1)}.{m.group(2)} or later"
    # On Linux the wheel names the oldest C library it runs on (manylinux_2_34: glibc 2.34)
    if not WINDOWS:
        have = platform.libc_ver()[1]
        for name in (pyqt[-1], qt[-1]):
            m = re.search(r"manylinux_(\d+)_(\d+)", name)
            if m and have:
                try:
                    if tuple(int(p) for p in have.split(".")[:2]) < (int(m.group(1)), int(m.group(2))):
                        return [], f"the drive's PyQt6 needs a newer Linux than this one (glibc {m.group(1)}.{m.group(2)})"
                except ValueError:
                    pass
    return [os.path.join(folder, n) for n in (pyqt[-1], qt[-1], sip[-1])], ""


def unpack_wheels(wheels, libs):
    """
    Unpack wheel files into the libs folder.  A wheel is a zip of the
    package's folders, so unpacking it into a folder on Python's path
    is all installing it amounts to for these three.  An earlier PyQt6
    in the folder is cleared first so two versions never mix.
    """
    if os.path.isdir(libs):
        for name in os.listdir(libs):
            if name.lower().startswith("pyqt6"):
                shutil.rmtree(os.path.join(libs, name), ignore_errors=True)
    os.makedirs(libs, exist_ok=True)
    for wheel in wheels:
        say(f"  unpacking {os.path.basename(wheel)} ...")
        with zipfile.ZipFile(wheel) as z:
            for info in z.infolist():
                # Kept inside the folder whatever the archive says
                rel = os.path.normpath(info.filename)
                if rel.startswith("..") or os.path.isabs(rel):
                    continue
                z.extract(info, libs)


def ensure_pyqt(dest, yes=False):
    """
    See that PyQt6 can be found.  Returns the libs folder the starter
    files must put on Python's path ('' when the computer's own PyQt6
    is used), or None when PyQt6 could not be had.
    """
    libs = os.path.join(dest, "libs")
    ok, _ = pyqt_works()
    if ok:
        say("PyQt6: already on this computer.")
        STATE.update(pyqt="already on this computer", pyqt_libs="")
        return ""
    if os.path.isdir(libs) and pyqt_works(libs)[0] and not drive_newer_than(libs):
        say("PyQt6: the copy installed earlier is in place.")
        STATE.update(pyqt="the copy installed earlier is in place", pyqt_libs=libs)
        return libs
    wheels, why = drive_wheels()
    if wheels:
        say("PyQt6: installing the copy on the drive (no internet needed).")
        unpack_wheels(wheels, libs)
        ok, error = pyqt_works(libs)
        if ok:
            with open(os.path.join(libs, "pyqt6_from.txt"), "w", encoding="utf-8") as f:
                f.write(os.path.basename(wheels[0]))
            STATE.update(pyqt=f"unpacked from the drive ({os.path.basename(wheels[0])})", pyqt_libs=libs)
            return libs
        say(f"  the drive's PyQt6 did not load here: {error}")
    else:
        say(f"PyQt6: {why}.")
    answer = ask("Fetch PyQt6 from the internet with pip instead? [Y/n] ", "y", yes)
    if answer.lower().startswith("y"):
        os.makedirs(libs, exist_ok=True)
        done = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--target", libs, "PyQt6"])
        if done.returncode == 0 and pyqt_works(libs)[0]:
            STATE.update(pyqt="fetched from the internet with pip", pyqt_libs=libs)
            return libs
        say("  pip could not install PyQt6.")
    say("PyQt6 is still missing.  The programs are installed but will not start until it is there:\n"
        "    Windows:  py -m pip install PyQt6\n"
        "    Ubuntu:   sudo apt install python3-pyqt6      (or  pip3 install PyQt6)")
    STATE.update(pyqt="NOT FOUND: neither this computer's, the drive's nor pip's could be had")
    return None


def drive_newer_than(libs):
    """True when the drive's PyQt6 wheel differs from the one the libs folder was unpacked from."""
    wheels, _ = drive_wheels()
    try:
        with open(os.path.join(libs, "pyqt6_from.txt"), encoding="utf-8") as f:
            return bool(wheels) and f.read().strip() != os.path.basename(wheels[0])
    except OSError:
        return False


def check_display(libs):
    """On Linux with a screen, open Qt once; say what to install when its window plugin will not load."""
    if WINDOWS or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return
    ok, error = pyqt_works(libs or None, show=True)
    STATE["display"] = "opens" if ok else "DOES NOT OPEN: " + error[:150]
    if not ok:
        say("Note: Qt could not open a window on this screen (" + error[:120] + ").\n"
            "  On Ubuntu this is nearly always one missing system file; install it with\n"
            "      sudo apt install libxcb-cursor0\n"
            "  and start the program again.")


# ---------------------------------------------------------------------------
# Starting the programs: a starter file each, and menu entries
# ---------------------------------------------------------------------------

STARTER = '''# Starts {name}.  Written by the Word Atlas installer on {date}.
# Double-click it (Windows), or:  python3 "{file}"
import os
import runpy
import sys

LIBS = {libs!r}          # the PyQt6 the installer unpacked; '' when the computer has its own
APP_DIR = {app_dir!r}
SCRIPT = {script!r}

try:
    if LIBS:
        # On this program's path, and on the path of every tool it starts
        sys.path.insert(0, LIBS)
        os.environ["PYTHONPATH"] = LIBS + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.chdir(APP_DIR)
    sys.path.insert(0, APP_DIR)
    sys.argv = [os.path.join(APP_DIR, SCRIPT)] + sys.argv[1:]
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit:
    raise
except BaseException:
    # Started without a terminal there is nowhere for an error to be
    # seen, so it is written beside this file and, on Windows, shown
    import traceback
    text = traceback.format_exc()
    log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start_error.txt")
    with open(log, "w", encoding="utf-8") as f:
        f.write(text)
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text[-900:] + "\\n\\n(also written to " + log + ")",
                                         {name!r} + " could not start", 0x10)
    raise
'''


def write_starter(dest, key, libs):
    """Write dest/start_<program>.pyw and return its path."""
    app = APPS[key]
    path = os.path.join(dest, f"start_{app['folder']}.pyw")
    with open(path, "w", encoding="utf-8") as f:
        f.write(STARTER.format(name=app["name"], date=time.strftime("%Y-%m-%d"), file=path, libs=libs or "",
                               app_dir=os.path.join(dest, app["folder"]), script=app["script"]))
    return path


def windowless_python():
    """pythonw.exe beside python.exe on Windows (no black window behind the program); else this Python."""
    if WINDOWS:
        candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(candidate):
            return candidate
    return sys.executable


def make_shortcuts(starters):
    """Menu entries for the installed programs: .desktop files on Linux, Start menu and Desktop shortcuts on Windows."""
    made = []
    if WINDOWS:
        python = windowless_python()

        def q(text):
            """A text inside single quotes in PowerShell: a single quote in it is doubled."""
            return text.replace("'", "''")

        # A .lnk is made through Windows' own scripting object.  The
        # commands go in a script file, not on a command line, so no
        # path with a space or a quote in it can be misread on the way
        lines = ["$shell = New-Object -ComObject WScript.Shell"]
        for key, starter in starters.items():
            name = APPS[key]["name"]
            for place in ("Desktop", "Programs"):
                lines += [f"$s = $shell.CreateShortcut([Environment]::GetFolderPath('{place}') + '\\{q(name)}.lnk')",
                          f"$s.TargetPath = '{q(python)}'",
                          f"$s.Arguments = '\"{q(starter)}\"'",
                          f"$s.WorkingDirectory = '{q(os.path.dirname(starter))}'",
                          f"$s.Description = '{q(APPS[key]['about'])}'",
                          "$s.Save()"]
        script = os.path.join(os.path.dirname(next(iter(starters.values()))), "make_shortcuts.ps1")
        try:
            with open(script, "w", encoding="utf-8-sig") as f:      # with the mark PowerShell reads UTF-8 by
                f.write("\n".join(lines) + "\n")
            done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                                  capture_output=True, timeout=120)
            if done.returncode == 0:
                made = [f"{APPS[key]['name']} (the Desktop and the Start menu)" for key in starters]
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            if os.path.exists(script):
                os.remove(script)
    else:
        folder = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
        try:
            os.makedirs(folder, exist_ok=True)
            for key, starter in starters.items():
                app = APPS[key]
                path = os.path.join(folder, app["folder"].replace("_", "-") + ".desktop")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("[Desktop Entry]\nType=Application\n"
                            f"Name={app['name']}\nComment={app['about']}\n"
                            f"Exec=\"{sys.executable}\" \"{starter}\"\n"
                            f"Path={os.path.dirname(starter)}\nTerminal=false\nCategories=Education;\n")
                os.chmod(path, 0o755)
                made.append(f"{app['name']} (the applications menu)")
        except OSError:
            pass
    return made


def start_command(starter):
    """The command line that starts a program, for the closing message."""
    return f'"{windowless_python()}" "{starter}"'


# ---------------------------------------------------------------------------
# The install report: what was installed, and whether it all works
# ---------------------------------------------------------------------------
# What the PyQt6 step found, for the report (filled by ensure_pyqt and
# check_display as they run)
STATE = {"pyqt": "", "pyqt_libs": None, "display": ""}

REPORT_NAME = "install_report.txt"
FILES_NAME = "installed_files.json"


def record_files(dest, manifest, keys):
    """
    Keep, beside the install, the list of every file it installed with
    its size and checksum (from the drive's manifest), so the install can
    be checked later without the drive: installed_files.json.
    """
    path = os.path.join(dest, FILES_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            held = json.load(f)
    except (OSError, ValueError):
        held = {}
    for key in keys:
        app_dir = APPS[key]["folder"]
        files = {}
        groups = (("reader", "programs/word_atlas_reader/"), ("dataset", None)) if key == "reader" else \
            (("atlas", "programs/word_atlas/"), ("atlas_data", "data/word_atlas/"))
        for group, prefix in groups:
            for rel, entry in files_of(manifest, group):
                if prefix is None:          # a dataset goes into the Reader's datasets folder
                    target = f"{app_dir}/datasets/{rel.split('/')[-1]}"
                else:
                    target = f"{app_dir}/{rel[len(prefix):]}"
                files[target] = {"size": entry.get("size"), "sha256": entry.get("sha256", "")}
        held[key] = files
    with open(path, "w", encoding="utf-8") as f:
        json.dump(held, f, indent=1)


class InstallCheck:
    """
    Looks over an install and writes what it finds: every file there and
    unchanged, the datasets readable, PyQt6 loading, a window opening,
    the starters and menu entries in place, and any error a program
    left when it last failed to start.  Each problem comes with what to
    do about it.  The text goes to the screen and to install_report.txt
    in the install folder: the file to send when asking for help.
    """

    def __init__(self, dest):
        self.dest = dest
        self.lines = []
        self.problems = []          # (what is wrong, what to do)

    def say(self, text=""):
        self.lines.append(text)

    def problem(self, what, fix):
        self.problems.append((what, fix))

    def run(self, copier=None, made=None, drive_manifest=None):
        dest = self.dest
        self.say("WORD ATLAS INSTALL REPORT")
        self.say("=" * 25)
        self.say(f"Written     {time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.say(f"Folder      {dest}")
        if drive_manifest:
            self.say(f"From drive  written {drive_manifest.get('written', '?')} by {drive_manifest.get('written_by', '?')}"
                     f" ({ROOT})")
        self.say("")
        self.computer()
        try:
            with open(os.path.join(dest, "installed.json"), encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, ValueError):
            record = {}
        try:
            with open(os.path.join(dest, FILES_NAME), encoding="utf-8") as f:
                files = json.load(f)
        except (OSError, ValueError):
            files = {}
        if not record:
            self.say("No installed.json in this folder: nothing has been installed here, or the folder is "
                     "not the install folder.")
            self.problem("No install found in " + dest,
                         "Give the folder the programs were installed into: install.py --check --dest FOLDER")
        for key in ("reader", "atlas"):
            if key in record:
                self.program(key, record[key], files.get(key, {}))
        if copier is not None:
            self.copy_step(copier)
        self.pyqt()
        self.starters(made)
        self.say("")
        if self.problems:
            self.say(f"PROBLEMS FOUND: {len(self.problems)}")
            for i, (what, fix) in enumerate(self.problems, 1):
                self.say(f"  {i}. {what}")
                self.say(f"     What to do: {fix}")
        else:
            self.say("NO PROBLEMS FOUND: every file is in place and unchanged, and PyQt6 loads.")
        self.say("")
        self.say(f"This report is kept as {os.path.join(dest, REPORT_NAME)}.  When asking for help, send that "
                 "file.  To check the install again later:  python3 install.py --check  on the drive, or "
                 "python3 usb_install.py --check  in the installed word_atlas_reader folder.")
        text = "\n".join(self.lines) + "\n"
        try:
            with open(os.path.join(dest, REPORT_NAME), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            text += f"\n(The report could not be saved in the install folder: {e})\n"
        return text

    # --- the parts -----------------------------------------------------------------------
    def computer(self):
        self.say("This computer")
        self.say(f"  System      {platform.platform()} ({platform.machine()})")
        self.say(f"  Python      {platform.python_version()} at {sys.executable}")
        try:
            free = shutil.disk_usage(self.dest).free
            self.say(f"  Free space  {free / 1e9:.1f} GB in the install folder's disk")
            if free < 500e6:
                self.problem(f"Only {free / 1e6:.0f} MB free on the install folder's disk",
                             "Free some space, or install into a folder on another disk (--dest).")
        except OSError:
            pass
        if sys.version_info[:2] < MIN_PYTHON:
            self.problem(f"Python {platform.python_version()} is older than {MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
                         "Install a newer Python from python.org and run the installer again.")
        self.say("")

    def program(self, key, record, files):
        app = APPS[key]
        app_dir = os.path.join(self.dest, app["folder"])
        self.say(f"{app['name']} {record.get('version', '?')}  (installed {record.get('installed', '?')})")
        self.say(f"  Folder      {app_dir}")
        if not os.path.isdir(app_dir):
            self.problem(f"{app['name']}'s folder is not there: {app_dir}",
                         "Run the installer again from the drive.")
            self.say("")
            return
        if not os.path.exists(os.path.join(app_dir, app["script"])):
            self.problem(f"{app['name']}'s program file {app['script']} is missing",
                         "Run the installer again from the drive.")
        if not files:
            self.say("  Files       no list of installed files (installed before the report came in): "
                     "only the program file was looked for")
        else:
            missing, changed, ok = [], [], 0
            for rel, want in sorted(files.items()):
                path = os.path.join(self.dest, *rel.split("/"))
                if not os.path.exists(path):
                    missing.append(rel)
                elif os.path.getsize(path) != want.get("size") or \
                        (want.get("sha256") and file_sha256(path) != want["sha256"]):
                    changed.append(rel)
                else:
                    ok += 1
            self.say(f"  Files       {len(files)} installed: {ok} in place and unchanged, {len(missing)} missing, "
                     f"{len(changed)} different from the drive's")
            for rel in missing[:10]:
                self.say(f"      missing:   {rel}")
            for rel in changed[:10]:
                self.say(f"      different: {rel}")
            if missing:
                self.problem(f"{len(missing)} of {app['name']}'s files are missing (first: {missing[0]})",
                             "Run the installer again from the drive; it copies only what is missing or wrong.")
            if changed:
                self.problem(f"{len(changed)} of {app['name']}'s files differ from the drive's (first: {changed[0]})",
                             "If you did not change them yourself, run the installer again with --force to "
                             "put back the drive's copies.")
        if key == "reader":
            self.datasets(app_dir)
        error_log = os.path.join(self.dest, "start_error.txt")
        if os.path.exists(error_log):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(error_log)))
            try:
                with open(error_log, encoding="utf-8", errors="replace") as f:
                    tail = f.read().strip().splitlines()[-3:]
            except OSError:
                tail = []
            self.say(f"  Last start error ({when}, start_error.txt):")
            for line in tail:
                self.say("      " + line)
            self.problem(f"A program failed to start on {when}: {tail[-1] if tail else 'see start_error.txt'}",
                         "Read the lines above; a missing PyQt6 or a missing system library are the usual "
                         "causes (see the PyQt6 part of this report).  Delete start_error.txt once it starts.")
        self.say("")

    def datasets(self, app_dir):
        folder = os.path.join(app_dir, "datasets")
        found = sorted(n for n in os.listdir(folder) if n.endswith(".wadb")) if os.path.isdir(folder) else []
        if not found:
            self.say("  Datasets    none in the datasets folder")
            self.problem("The Reader has no dataset to open",
                         "Install from a drive that carries one, or open a .wadb with File > Open.")
            return
        for name in found:
            path = os.path.join(folder, name)
            try:
                with zipfile.ZipFile(path) as z:
                    names = z.namelist()
                    manifest = json.loads(z.read("manifest.json")) if "manifest.json" in names else {}
                    bad = z.testzip()
                if "results.db" not in names:
                    raise ValueError("no results.db inside")
                if bad:
                    raise ValueError(f"damaged member {bad}")
                tables = manifest.get("tables", {})
                heat = "with heat strips" if tables.get("heat_windows") else "no heat strips (made before 0.10.101)"
                runs = manifest.get("runs", [])
                pages = sum(r.get("pages", 0) for r in runs)
                self.say(f"  Dataset     {name}: {os.path.getsize(path) / 1e6:.1f} MB, reads back whole, "
                         f"{pages} pages, {heat}")
            except (OSError, ValueError, zipfile.BadZipFile) as e:
                self.say(f"  Dataset     {name}: CANNOT BE READ ({e})")
                self.problem(f"The dataset {name} cannot be read ({e})",
                             "Run the installer again from the drive (with --force if the file is the same size).")
        settings = os.path.join(os.path.expanduser("~"), ".word_atlas_reader", "settings.json")
        try:
            with open(settings, encoding="utf-8") as f:
                last = json.load(f).get("last_file", "")
        except (OSError, ValueError):
            last = ""
        if last:
            state = "there" if os.path.exists(last) else "NOT THERE"
            self.say(f"  Opens first {last} ({state})")
            if not os.path.exists(last):
                self.problem("The Reader's last dataset is no longer there: " + last,
                             "Open a dataset with File > Open; the Reader remembers it.")

    def copy_step(self, copier):
        self.say("This run of the installer")
        self.say(f"  Copied      {copier.copied} file(s) ({mb(copier.copied_bytes)}); {copier.same} already up to date")
        if copier.kept_newer:
            self.say(f"  Left alone  {len(copier.kept_newer)} file(s) newer on this computer than on the drive")
            for path in copier.kept_newer[:6]:
                self.say("      " + path)
        if copier.failed:
            for line in copier.failed[:6]:
                self.say("      could not write: " + line)
            self.problem(f"{len(copier.failed)} file(s) could not be written",
                         "Close Word Atlas and the Reader if they are open (Windows will not replace a file in "
                         "use), and run the installer again.")
        self.say("")

    def libs_of_starters(self):
        """The PyQt6 folder the starter files put on the path ('' for the computer's own), read from them."""
        for app in APPS.values():
            path = os.path.join(self.dest, f"start_{app['folder']}.pyw")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    m = re.search(r"^LIBS = (.+?)\s+#", f.read(), re.M)
                if m:
                    try:
                        return ast.literal_eval(m.group(1))       # a quoted path written by write_starter
                    except Exception:
                        return ""
        return ""

    def pyqt(self):
        self.say("PyQt6 (what the programs' windows are made with)")
        if STATE["pyqt"]:
            self.say(f"  This run    {STATE['pyqt']}")
        libs = STATE["pyqt_libs"] if STATE["pyqt_libs"] is not None else self.libs_of_starters()
        ok, error = pyqt_works(libs or None)
        where = f"the copy in {libs}" if libs else "this computer's own"
        self.say(f"  Loads       {'yes' if ok else 'NO'}, {where}" + ("" if ok else f": {error[:150]}"))
        if not ok:
            self.problem("PyQt6 does not load (" + error[:120] + ")",
                         "Run the installer again (it unpacks the drive's PyQt6), or install it yourself: "
                         "Windows  py -m pip install PyQt6;  Ubuntu  sudo apt install python3-pyqt6.")
        elif not WINDOWS and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            shown, error = pyqt_works(libs or None, show=True)
            self.say(f"  A window    {'opens' if shown else 'DOES NOT OPEN: ' + error[:150]}")
            if not shown:
                self.problem("Qt cannot open a window on this screen (" + error[:100] + ")",
                             "On Ubuntu install the missing system file:  sudo apt install libxcb-cursor0")
        elif STATE["display"]:
            self.say(f"  A window    {STATE['display']}")
        self.say("")

    def starters(self, made):
        self.say("Starting the programs")
        try:
            with open(os.path.join(self.dest, "installed.json"), encoding="utf-8") as f:
                keys = [k for k in json.load(f) if k in APPS]
        except (OSError, ValueError):
            keys = []
        for key in keys:
            app = APPS[key]
            starter = os.path.join(self.dest, f"start_{app['folder']}.pyw")
            if os.path.exists(starter):
                self.say(f"  {app['name']}: {start_command(starter)}")
            else:
                self.say(f"  {app['name']}: NO STARTER FILE ({starter})")
                self.problem(f"{app['name']} has no starter file", "Run the installer again from the drive.")
            for place in self.shortcut_paths(key):
                self.say(f"      {'menu entry' if place.endswith('.desktop') else 'shortcut'}: {place} "
                         f"({'there' if os.path.exists(place) else 'not there'})")
        if made is not None and not made:
            self.say("  No menu entries or shortcuts were made this time (--no-shortcuts, or the system refused).")

    @staticmethod
    def shortcut_paths(key):
        """Where the menu entry or shortcuts for a program are made."""
        app = APPS[key]
        if WINDOWS:
            home = os.path.expanduser("~")
            appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
            return [os.path.join(home, "Desktop", app["name"] + ".lnk"),
                    os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", app["name"] + ".lnk")]
        return [os.path.join(os.path.expanduser("~"), ".local", "share", "applications",
                             app["folder"].replace("_", "-") + ".desktop")]


def check_install(dest, copier=None, made=None, drive_manifest=None):
    """Check the install in dest, print the report and save it; returns the number of problems."""
    check = InstallCheck(dest)
    say(check.run(copier, made, drive_manifest))
    return len(check.problems)


def default_install_dir():
    """
    The install folder to check when none is given: the folder above this
    file when this is the installed copy (usb_install.py inside
    word_atlas_reader or word_atlas), else ~/WordAtlas.
    """
    parent = os.path.dirname(ROOT)
    if os.path.exists(os.path.join(parent, "installed.json")):
        return parent
    return os.path.join(os.path.expanduser("~"), "WordAtlas")


# ---------------------------------------------------------------------------
# The installer
# ---------------------------------------------------------------------------

def main(argv):
    args = argv[1:]
    flags = {a for a in args if a.startswith("--")}
    values = {a: args[i + 1] for i, a in enumerate(args) if a.startswith("--") and i + 1 < len(args)
              and not args[i + 1].startswith("--")}
    if "--help" in flags or "-h" in args:
        say(__doc__)
        return 0
    yes = "--yes" in flags
    say("Word Atlas installer")
    say("====================")
    if sys.version_info[:2] < MIN_PYTHON:
        say(f"This computer's Python is {platform.python_version()}; Word Atlas needs "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} or later.\nInstall a newer Python (python.org) and run the installer again.")
        return 1
    if "--check" in flags:
        # Check an install and write its report; nothing is copied, and
        # the drive is not needed (the install keeps its own file list)
        dest = os.path.abspath(os.path.expanduser(values.get("--dest") or default_install_dir()))
        say(f"Checking the install in {dest}")
        say()
        return 1 if check_install(dest) else 0
    manifest = load_manifest()
    for line in describe(manifest):
        say(line)
    if not manifest.get("complete", True):
        say("Note: the last build of this drive was stopped part way; some files may be missing.")
    if "--list" in flags:
        return 0
    offered = [k for k in ("reader", "atlas") if manifest.get(k)]
    if not offered:
        say("The drive holds neither program.  Make it again from Word Atlas or the Reader.")
        return 1

    # Which program
    chosen = values.get("--app", "")
    if chosen not in ("reader", "atlas", "both"):
        if len(offered) == 1:
            chosen = offered[0]
        else:
            say()
            say("Install which?")
            say("  1. Word Atlas Reader   " + APPS["reader"]["about"])
            say("  2. Word Atlas          " + APPS["atlas"]["about"])
            say("  3. Both")
            answer = ask("Type 1, 2 or 3 and press Enter [1]: ", "1", yes)
            chosen = {"1": "reader", "2": "atlas", "3": "both"}.get(answer, "")
            if not chosen:
                say("Nothing installed.")
                return 0
    keys = [k for k in (("reader", "atlas") if chosen == "both" else (chosen,)) if k in offered]
    if not keys:
        say(f"The drive does not hold that program ({chosen}).")
        return 1

    # Where
    dest = values.get("--dest") or os.path.join(os.path.expanduser("~"), "WordAtlas")
    if "--dest" not in values:
        say()
        answer = ask(f"Install into {dest} ?  Press Enter for yes, or type another folder: ", "", yes)
        if answer:
            dest = answer
    dest = os.path.abspath(os.path.expanduser(dest))
    # A folder under git is somebody's working copy of the program, not an install
    for key in keys:
        if os.path.isdir(os.path.join(dest, APPS[key]["folder"], ".git")) and "--force" not in flags:
            say(f"\n{os.path.join(dest, APPS[key]['folder'])} is a working copy under git, not an install.\n"
                "The installer leaves it alone; choose another folder, or give --force to copy over it.")
            return 1
    os.makedirs(dest, exist_ok=True)

    # The files
    say()
    copier = Copier(force="--force" in flags)
    installed = {}
    for key in keys:
        say(f"{APPS[key]['name']} {manifest[key].get('version', '')} into {os.path.join(dest, APPS[key]['folder'])}")
        if key == "reader":
            installed[key] = install_reader(manifest, dest, copier)[0]
        else:
            installed[key] = install_atlas(manifest, dest, copier)
    say(f"  {copier.copied} file(s) copied ({mb(copier.copied_bytes)}), {copier.same} already up to date.")
    if copier.kept_newer:
        say(f"  {len(copier.kept_newer)} file(s) are newer on this computer than on the drive and were left alone:")
        for path in copier.kept_newer[:12]:
            say("      " + path)
        say("  (run the installer with --force to replace them with the drive's)")
    if copier.failed:
        say(f"  {len(copier.failed)} file(s) COULD NOT BE WRITTEN.  Close Word Atlas and the Reader if they are "
            "open, and run the installer again:")
        for line in copier.failed[:12]:
            say("      " + line)

    # PyQt6, the starter files, the menu entries
    say()
    if "--no-pyqt" in flags:
        # Asked to leave PyQt6 alone (the tests ask, so that a test never
        # reaches for the internet): the starters use the computer's own
        say("PyQt6: left as it is (--no-pyqt).")
        libs = ""
    else:
        libs = ensure_pyqt(dest, yes)
    starters = {key: write_starter(dest, key, libs or "") for key in keys}
    if libs is not None and "--no-pyqt" not in flags:
        check_display(libs)
    made = [] if "--no-shortcuts" in flags else make_shortcuts(starters)

    # A record of what was installed, for the next update and for anyone asking
    record_path = os.path.join(dest, "installed.json")
    try:
        with open(record_path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        record = {}
    for key in keys:
        record[key] = {"version": manifest[key].get("version", ""), "installed": time.strftime("%Y-%m-%d %H:%M"),
                       "from_drive_written": manifest.get("written", "")}
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    # The list of installed files, then the install report (0.10.102)
    record_files(dest, manifest, keys)
    say()
    problems = check_install(dest, copier, None if "--no-shortcuts" in flags else made, manifest)

    say()
    say(("Done." if libs is not None else "Done, except for PyQt6 (see above).") if not copier.failed else
        "Finished, but some files could not be written (see above).")
    for key in keys:
        say(f"  {APPS[key]['name']}:  {start_command(starters[key])}")
    if made:
        say("  Also in: " + "; ".join(made) + ".")
    if libs is not None and "--no-launch" not in flags and not yes:
        first = APPS[keys[0]]["name"]
        if ask(f"\nStart {first} now? [Y/n] ", "y").lower().startswith("y"):
            subprocess.Popen([windowless_python(), starters[keys[0]]], cwd=dest)
    if problems and not copier.failed and libs is not None:
        say("  The install report above found problems: see PROBLEMS FOUND.")
    return 1 if copier.failed else (0 if libs is not None else 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
