#!/usr/bin/env python3
"""
atlas_pack.py  -  pack the results database for the Word Atlas Reader

    python3 atlas_pack.py [--out FILE] [--note TEXT]

Zips reports/results.db together with a small manifest (the program
version, the runs the file holds, when it was packed) into one .wadb
file, by default reports/word_atlas_<run version>_<run date>.wadb,
named after the newest run the database holds.  The Reader opens
that file directly; a reader who has it needs neither the Bible build
nor the main program.  The database compresses to about a third of its
size, since nearly all of it is text.

Write the database first:  python3 atlas_query.py dossier all --results
"""

import json
import os
import sqlite3
import sys
import time
import zipfile

from atlas_pages import VERSION

PROGRAM_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(PROGRAM_DIR, "reports", "results.db")


def pack(results_path=RESULTS_PATH, out_path=None, note=""):
    """Write the archive and return its path."""
    if not os.path.exists(results_path):
        sys.exit(f"{results_path} not found: write it with  python3 atlas_query.py dossier all --results")
    db = sqlite3.connect("file:" + results_path.replace("\\", "/") + "?mode=ro", uri=True)
    runs = [{"run_id": r[0], "version": r[1], "started": r[2], "note": r[3],
             "pages": db.execute("SELECT COUNT(*) FROM pages WHERE run_id = ?", (r[0],)).fetchone()[0]}
            for r in db.execute("SELECT run_id, version, started, note FROM runs ORDER BY run_id")]
    db.close()
    if not runs:
        sys.exit("results.db holds no run yet")
    manifest = {
        "format": "Word Atlas dataset",
        "program_version": VERSION,
        "packed": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": note,
        "runs": runs,
    }
    if out_path is None:
        # Named after the newest run inside, its version and its date,
        # not after the program doing the packing: the name then says
        # what the pages are, and packing again later does not change it
        newest = runs[-1]
        out_path = os.path.join(PROGRAM_DIR, "reports",
                                f"word_atlas_{newest['version']}_{newest['started'][:10]}.wadb")
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(results_path, "results.db")
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    before = os.path.getsize(results_path)
    after = os.path.getsize(out_path)
    print(f"Packed {len(runs)} run(s), {sum(r['pages'] for r in runs)} pages: "
          f"{before / 1e6:.1f} MB into {after / 1e6:.1f} MB at {out_path}")
    return out_path


def main(argv):
    out, note = None, ""
    args = argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--out" and i + 1 < len(args):
            out = args[i + 1]; i += 2; continue
        if args[i] == "--note" and i + 1 < len(args):
            note = args[i + 1]; i += 2; continue
        if args[i] in ("-h", "--help"):
            print(__doc__); return
        i += 1
    pack(out_path=out, note=note)


if __name__ == "__main__":
    main(sys.argv)
