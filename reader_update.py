#!/usr/bin/env python3
"""
reader_update.py  -  newer Readers and newer datasets, from GitHub

A Reader installed from a USB drive can bring itself up to date over
the internet without another drive:

    the program    the newest Reader is the one on the main branch of
                   its repository (github.com/andyinva/word-atlas-reader):
                   its version is read from word_atlas_reader.py there,
                   and the program files come from the branch's zip.
                   They replace this copy's files, the old ones kept in
                   a backup folder, or go into another folder of the
                   reader's choosing.  The datasets, the settings and a
                   guest key are never touched.
    the datasets   a dataset is too large for git (some 150 MB), so the
                   newest one is the newest .wadb attached to a GitHub
                   release of the same repository.  It is downloaded into
                   the Reader's own datasets folder; the older ones there
                   can be removed at the same time.

Publishing, on the computer the datasets are made on: push the Reader's
code as usual (a new VERSION in word_atlas_reader.py is what tells
copies an update is there), and attach each new .wadb to a release:
GitHub, the repository, Releases, "Draft a new release", a tag such as
dataset-2026-10-20, attach the file, Publish; or with the gh tool,

    gh release create dataset-2026-10-20 reports/word_atlas_0.10.101_2026-10-20.wadb \\
        --repo andyinva/word-atlas-reader --title "Dataset 2026-10-20" --notes "Word Atlas 0.10.101"

The repository can be changed in the Reader's settings.json
("update_repo": "owner/name"), for a copy that follows another one.

Standard library only (urllib), so it works in a built copy too.  The
network calls go through fetch() and download(), which the tests
replace with stand-ins: the tests never reach the internet.
"""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

REPO = "andyinva/word-atlas-reader"
BRANCH = "main"
RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/word_atlas_reader.py"
ZIP_URL = "https://codeload.github.com/{repo}/zip/refs/heads/{branch}"
# Tried in turn when the first address is refused (some networks and
# firewalls block one GitHub address and not another)
ZIP_URL_2 = "https://github.com/{repo}/archive/refs/heads/{branch}.zip"
CONTENTS_URL = "https://api.github.com/repos/{repo}/contents/?ref={branch}"
FILE_URL = "https://raw.githubusercontent.com/{repo}/{branch}/{name}"
RELEASES_URL = "https://api.github.com/repos/{repo}/releases?per_page=30"
PAGE_URL = "https://github.com/{repo}"
TIMEOUT = 30
USER_AGENT = "WordAtlasReader-update"

# The files of a Reader that an update writes: top-level files with these
# endings, and LICENSE (the same rule the USB drive uses, atlas_usb.py)
PROGRAM_ENDINGS = (".py", ".md", ".txt", ".tsv", ".spec")
EXTRA_FILES = ("LICENSE",)
# Never written by an update, whatever the zip holds
NEVER = {"guest_key.dat", "settings.json"}


class UpdateError(Exception):
    """Anything that stops a check or a download, in one sentence."""


def repo_of(settings):
    return (settings or {}).get("update_repo") or REPO


# ---------------------------------------------------------------------------
# The network: two small functions the tests replace
# ---------------------------------------------------------------------------

def fetch(url, timeout=TIMEOUT):
    """The body of a URL as bytes; UpdateError with a plain reason when it cannot be had."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError(f"not found on GitHub ({url})") from None
        if e.code == 403:
            raise UpdateError("GitHub refused for now (too many checks in an hour); try again later") from None
        raise UpdateError(f"GitHub answered {e.code} for {url}") from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise UpdateError(f"could not reach GitHub ({reason}): is this computer online?") from None


def download(url, path, progress=None, cancelled=None):
    """
    Download a URL to a file, by way of path + '.part' so a stopped
    download never leaves a file that looks whole.  progress(done, total)
    is called as it goes; cancelled() returning True stops it.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"})
    part = path + ".part"
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply, open(part, "wb") as out:
            total = int(reply.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancelled and cancelled():
                    raise UpdateError("the download was stopped")
                block = reply.read(1 << 20)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if progress:
                    progress(done, total)
        os.replace(part, path)
    except (urllib.error.URLError, OSError) as e:
        if os.path.exists(part):
            os.remove(part)
        raise UpdateError(f"the download failed ({getattr(e, 'reason', e)})") from None
    except UpdateError:
        if os.path.exists(part):
            os.remove(part)
        raise


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

def version_in(text):
    """The VERSION = "x.y.z" a program file sets, or ''."""
    m = re.search(r'^VERSION\s*=\s*"([\d.]+)"', text, re.M)
    return m.group(1) if m else ""


def version_key(version):
    """'0.3.12' -> (0, 3, 12), for comparing."""
    return tuple(int(p) for p in re.findall(r"\d+", version or "0"))


def is_newer(latest, current):
    return version_key(latest) > version_key(current)


# ---------------------------------------------------------------------------
# The program
# ---------------------------------------------------------------------------

def latest_program(settings=None):
    """{'version', 'zip_url', 'page'} of the newest Reader on GitHub."""
    repo = repo_of(settings)
    text = fetch(RAW_URL.format(repo=repo, branch=BRANCH)).decode("utf-8", "replace")
    version = version_in(text)
    if not version:
        raise UpdateError(f"no version found in word_atlas_reader.py on {repo}")
    return {"version": version, "zip_url": ZIP_URL.format(repo=repo, branch=BRANCH),
            "page": PAGE_URL.format(repo=repo), "repo": repo}


def download_program(latest, zip_path, say=None):
    """
    Bring the newest Reader down as a zip at zip_path, trying three ways
    in turn, since a network may refuse one GitHub address and not
    another:
        1. the branch zip from codeload.github.com
        2. the same zip by way of github.com
        3. the program files one by one from raw.githubusercontent.com
           (the address the version check itself used), packed here
           into a zip of the same shape
    say(text) is told of each way that fails.  Returns the way that worked.
    """
    repo = latest.get("repo") or REPO
    reasons = []
    for url in (latest["zip_url"], ZIP_URL_2.format(repo=repo, branch=BRANCH)):
        try:
            download(url, zip_path)
            if zipfile.is_zipfile(zip_path):
                return url
            reasons.append(f"{url}: not a zip")
        except UpdateError as e:
            reasons.append(f"{url}: {e}")
        if say:
            say(f"    {reasons[-1]}; trying another way ...")
    try:
        names = program_names_on_github(repo)
        top = f"{repo.split('/')[-1]}-{BRANCH}"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name in names:
                z.writestr(f"{top}/{name}", fetch(FILE_URL.format(repo=repo, branch=BRANCH, name=name)))
        return "raw.githubusercontent.com, file by file"
    except UpdateError as e:
        reasons.append(f"file by file: {e}")
    raise UpdateError("the newer Reader could not be downloaded.  " + "  ".join(reasons))


def program_names_on_github(repo):
    """The names of the program files at the top of the repository, from GitHub's contents list."""
    try:
        listing = json.loads(fetch(CONTENTS_URL.format(repo=repo, branch=BRANCH)).decode("utf-8"))
    except ValueError:
        raise UpdateError("GitHub's list of files could not be read") from None
    names = [item["name"] for item in listing if isinstance(item, dict) and item.get("type") == "file"
             and item.get("name") not in NEVER and not item["name"].startswith(".")
             and (item["name"].endswith(PROGRAM_ENDINGS) or item["name"] in EXTRA_FILES)]
    if "word_atlas_reader.py" not in names or "reader_data.py" not in names:
        raise UpdateError("GitHub's list of files does not hold the Reader's program files")
    return sorted(names)


def program_members(zip_path):
    """{file name: member name} of the Reader's program files in a GitHub branch zip (one top folder)."""
    out = {}
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            parts = member.split("/")
            # word-atlas-reader-main/<file>: top-level files only
            if len(parts) != 2 or not parts[1]:
                continue
            name = parts[1]
            if name in NEVER or name.startswith("."):
                continue
            if name.endswith(PROGRAM_ENDINGS) or name in EXTRA_FILES:
                out[name] = member
    if "word_atlas_reader.py" not in out or "reader_data.py" not in out:
        raise UpdateError("the download does not hold the Reader's program files")
    return out


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def install_program(zip_path, target_dir, backup_root=None, current_version=""):
    """
    Write the program files of a downloaded zip into target_dir.  The
    files it replaces are first copied to a backup folder under
    backup_root (reader_<old version>_<date>), so an update can be
    undone by copying them back.  Returns (files written, backup folder
    or None).  Subfolders (datasets, sample, builds) are not touched.
    """
    members = program_members(zip_path)
    os.makedirs(target_dir, exist_ok=True)
    backup = None
    replaced = [n for n in members if os.path.exists(os.path.join(target_dir, n))]
    if backup_root and replaced:
        backup = os.path.join(backup_root, f"reader_{current_version or 'old'}_{time.strftime('%Y-%m-%d_%H%M%S')}")
        os.makedirs(backup, exist_ok=True)
        for name in replaced:
            shutil.copy2(os.path.join(target_dir, name), os.path.join(backup, name))
    written = []
    with zipfile.ZipFile(zip_path) as z:
        for name, member in sorted(members.items()):
            target = os.path.join(target_dir, name)
            part = target + ".part"
            with z.open(member) as src, open(part, "wb") as out:
                shutil.copyfileobj(src, out)
            os.replace(part, target)
            written.append(name)
    note_in_install(target_dir, written, version_in(open(os.path.join(target_dir, "word_atlas_reader.py"),
                                                         encoding="utf-8").read()))
    return written, backup


def note_in_install(target_dir, written, version):
    """
    When target_dir is an installed Reader (installed.json and
    installed_files.json in the folder above, written by the USB
    installer), record the files just written and the new version
    there, so the install report does not take an update for damage.
    """
    parent = os.path.dirname(os.path.abspath(target_dir))
    folder = os.path.basename(os.path.abspath(target_dir))
    files_path = os.path.join(parent, "installed_files.json")
    record_path = os.path.join(parent, "installed.json")
    if not os.path.exists(record_path):
        return
    try:
        with open(files_path, encoding="utf-8") as f:
            files = json.load(f)
    except (OSError, ValueError):
        files = {}
    reader = files.setdefault("reader", {})
    for name in written:
        path = os.path.join(target_dir, name)
        reader[f"{folder}/{name}"] = {"size": os.path.getsize(path), "sha256": file_sha256(path)}
    with open(files_path, "w", encoding="utf-8") as f:
        json.dump(files, f, indent=1)
    try:
        with open(record_path, encoding="utf-8") as f:
            record = json.load(f)
        if "reader" in record:
            record["reader"]["version"] = version
            record["reader"]["updated"] = time.strftime("%Y-%m-%d %H:%M") + " (from GitHub)"
            with open(record_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# The datasets
# ---------------------------------------------------------------------------

def latest_dataset(settings=None):
    """
    The newest .wadb attached to a release of the repository:
    {'name', 'size', 'url', 'published', 'release'}, or None when no
    release carries one.
    """
    repo = repo_of(settings)
    try:
        releases = json.loads(fetch(RELEASES_URL.format(repo=repo)).decode("utf-8"))
    except ValueError:
        raise UpdateError("GitHub's list of releases could not be read") from None
    found = []
    for release in releases if isinstance(releases, list) else []:
        if release.get("draft"):
            continue
        for asset in release.get("assets", []):
            if asset.get("name", "").lower().endswith(".wadb"):
                found.append({"name": asset["name"], "size": asset.get("size", 0),
                              "url": asset.get("browser_download_url", ""),
                              "published": asset.get("updated_at") or release.get("published_at") or "",
                              "release": release.get("name") or release.get("tag_name", "")})
    if not found:
        return None
    return max(found, key=lambda a: (a["published"], a["name"]))


def have_dataset(asset, folder):
    """True when the folder already holds this dataset (the same name and size)."""
    path = os.path.join(folder, asset["name"])
    return os.path.exists(path) and (not asset.get("size") or os.path.getsize(path) == asset["size"])


def fetch_dataset(asset, folder, progress=None, cancelled=None):
    """Download a release's .wadb into the folder; returns its path."""
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, asset["name"])
    download(asset["url"], target, progress, cancelled)
    if not zipfile.is_zipfile(target):
        os.remove(target)
        raise UpdateError(f"{asset['name']} came down damaged (not a .wadb); try again")
    return target


def older_datasets(folder, keep):
    """The other .wadb files in the folder: those the newly fetched one makes older."""
    return sorted(os.path.join(folder, n) for n in os.listdir(folder)
                  if n.lower().endswith(".wadb") and os.path.abspath(os.path.join(folder, n)) != os.path.abspath(keep))


def temp_zip_path():
    """A place to download a program zip to, removed by the caller."""
    handle, path = tempfile.mkstemp(suffix=".zip", prefix="word_atlas_reader_")
    os.close(handle)
    return path


def frozen():
    """True for a built copy (PyInstaller), whose program files are inside the build and cannot be replaced."""
    return bool(getattr(sys, "frozen", False))
