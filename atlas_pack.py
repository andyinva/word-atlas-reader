#!/usr/bin/env python3
"""
atlas_pack.py  -  pack the results database for the Word Atlas Reader

    python3 atlas_pack.py [--out FILE] [--note TEXT] [--results FILE]
    python3 atlas_pack.py --results OLD.db --allow-old-schema --out FILE

Zips a copy of reports/results.db together with a small manifest (the
program version, the runs the file holds, its tables, when it was
packed) into one .wadb file, by default
reports/word_atlas_<run version>_<run date>.wadb, named after the newest
run the database holds.  The Reader opens that file directly; a reader
who has it needs neither the Bible build nor the main program.  The
database compresses to about a third of its size, since nearly all of
it is text.

WHAT THE PACK HOLDS (0.10.101)
    Everything the Reader shows, so nothing else from the atlas needs to
    be on the stick:
        the pages      runs, pages, sections, cells, refs, footers
                       (written by  python3 atlas_query.py dossier all --results)
        the heat rows  heat_strips, heat_windows, heat_spots
                       (written by every atlas_heat.py run;
                        python3 run_heat.py --all fills them for every book)
        schema_notes   what every table and column holds, in plain words
    and, added to the packed copy only (results.db itself is not changed):
        passages, passage_ranges
                       the named passages of metadata.db and their ranges
        kjv_books, kjv_verses, kjv_tags
                       the King James text with its Strong's tags, from
                       atlas_source.db (atlas_source.py)
    No chart (SVG) and no other file goes into the pack.

A results file without the schema_notes table was written before
0.10.101 and lacks the heat tables, so the pack refuses it: write the
pages again with the line above.  --allow-old-schema packs such a file
anyway, as it is plus the passages and the King James text, only to give
the Reader an old file to be tested against; its manifest says so.
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
import zipfile

from atlas_pages import VERSION
import atlas_report

PROGRAM_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(PROGRAM_DIR, "reports", "results.db")
METADATA_PATH = os.path.join(PROGRAM_DIR, "metadata.db")
SOURCE_PATH = os.path.join(PROGRAM_DIR, "atlas_source.db")

# The tables the pack adds to its copy, and where they come from
PACK_TABLES = ["passages", "passage_ranges", "kjv_books", "kjv_verses", "kjv_tags"]


class PackRefused(SystemExit):
    """The pack declined; the message says why.  A SystemExit, so the command line just stops."""


def read_only(path):
    """A read-only connection to a SQLite file, Windows paths included."""
    return sqlite3.connect("file:" + path.replace("\\", "/") + "?mode=ro", uri=True)


def has_table(db, name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone())


def add_reader_tables(db, metadata_path=METADATA_PATH, source_path=SOURCE_PATH):
    """
    Copy the named passages (metadata.db) and the King James text with
    its tags (atlas_source.db) into the packed copy, replacing any copy
    an earlier pack left there.  Returns {table: rows}.
    """
    for path, what in ((metadata_path, "the named passages"), (source_path, "the King James text")):
        if not os.path.exists(path):
            raise PackRefused(f"{path} not found: the pack carries {what} from it.")
    for table in PACK_TABLES:
        db.execute(f"DROP TABLE IF EXISTS {table}")
    db.executescript(atlas_report.PACK_SCHEMA)
    meta = read_only(metadata_path)
    try:
        db.executemany("INSERT INTO passages VALUES (?, ?, ?, ?)", meta.execute(
            "SELECT passage_id, name, description, source_note FROM passages ORDER BY passage_id"))
        db.executemany("INSERT INTO passage_ranges VALUES (?, ?, ?, ?, ?, ?)", meta.execute(
            "SELECT passage_id, book_num, chapter_start, verse_start, chapter_end, verse_end "
            "FROM passage_ranges ORDER BY passage_id, book_num, chapter_start, verse_start"))
    finally:
        meta.close()
    src = read_only(source_path)
    try:
        # The King James translation's id, as atlas_source.py stores it
        kjv = src.execute("SELECT id FROM translations WHERE abbreviation = 'KJV'").fetchone()
        if kjv is None:
            raise PackRefused(f"{source_path} has no KJV translation.")
        # Books by their order (1 Genesis ... 66 Revelation), the number
        # the passages and the rest of the program use
        order = dict(src.execute("SELECT id, order_index FROM books"))
        db.executemany("INSERT INTO kjv_books VALUES (?, ?, ?, ?)", src.execute(
            "SELECT order_index, name, abbreviation, testament FROM books ORDER BY order_index"))
        db.executemany("INSERT INTO kjv_verses VALUES (?, ?, ?, ?, ?)",
                       ((vid, order[book_id], ch, v, text) for vid, book_id, ch, v, text in src.execute(
                           "SELECT v.id, v.book_id, v.chapter, v.verse_number, t.text FROM verses v "
                           "JOIN verse_texts t ON t.verse_id = v.id AND t.translation_id = ? ORDER BY v.id",
                           (kjv[0],))))
        db.executemany("INSERT INTO kjv_tags VALUES (?, ?, ?, ?, ?)", src.execute(
            "SELECT verse_id, word_position, strongs_number, morphology, word_text FROM verse_strongs "
            "ORDER BY verse_id, word_position"))
    finally:
        src.close()
    db.commit()
    return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in PACK_TABLES}


def pack(results_path=RESULTS_PATH, out_path=None, note="", allow_old_schema=False,
         metadata_path=METADATA_PATH, source_path=SOURCE_PATH):
    """Write the archive and return its path."""
    if not os.path.exists(results_path):
        raise PackRefused(f"{results_path} not found: write it with  python3 atlas_query.py dossier all --results")
    db = read_only(results_path)
    try:
        if not has_table(db, "runs"):
            raise PackRefused(f"{results_path} is not a Word Atlas results file (no runs table).")
        new_schema = has_table(db, "schema_notes")
        if not new_schema and not allow_old_schema:
            raise PackRefused(
                f"{results_path} has no schema_notes table: it was written before 0.10.101 and lacks the "
                f"heat tables the Reader draws from.  Write it again with  python3 atlas_query.py dossier all "
                f"--results  and  python3 run_heat.py --all  (or pass --allow-old-schema to pack it as it is, "
                f"for testing the Reader against an old file).")
        runs = [{"run_id": r[0], "version": r[1], "started": r[2], "note": r[3],
                 "pages": db.execute("SELECT COUNT(*) FROM pages WHERE run_id = ?", (r[0],)).fetchone()[0]}
                for r in db.execute("SELECT run_id, version, started, note FROM runs ORDER BY run_id")]
    finally:
        db.close()
    if not runs:
        raise PackRefused("results.db holds no run yet")
    if out_path is None:
        # Named after the newest run inside, its version and its date,
        # not after the program doing the packing: the name then says
        # what the pages are, and packing again later does not change it
        newest = runs[-1]
        out_path = os.path.join(PROGRAM_DIR, "reports",
                                f"word_atlas_{newest['version']}_{newest['started'][:10]}.wadb")
    # A copy of the results file, with the Reader's tables added to the
    # copy only, so the file the dossier and the heat runs write stays
    # as they wrote it
    with tempfile.TemporaryDirectory() as tmp:
        copy_path = os.path.join(tmp, "results.db")
        src = read_only(results_path)
        copy = sqlite3.connect(copy_path)
        src.backup(copy)
        src.close()
        added = add_reader_tables(copy, metadata_path, source_path)
        tables = {name: copy.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                  for (name,) in copy.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")}
        copy.close()
        manifest = {
            "format": "Word Atlas dataset",
            "program_version": VERSION,
            "packed": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": note,
            "schema": "0.10.101" if new_schema else "before 0.10.101 (packed with --allow-old-schema, for testing)",
            "runs": runs,
            "tables": tables,
        }
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            # The database and the manifest, and nothing else: no chart
            # or other file of the atlas goes into the pack
            z.write(copy_path, "results.db")
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
        before = os.path.getsize(copy_path)
    after = os.path.getsize(out_path)
    heat = tables.get("heat_windows", 0)
    print(f"Packed {len(runs)} run(s), {sum(r['pages'] for r in runs)} pages, {heat:,} heat windows, "
          f"{added['passages']} passages, {added['kjv_verses']:,} King James verses: "
          f"{before / 1e6:.1f} MB into {after / 1e6:.1f} MB at {out_path}")
    return out_path


def main(argv):
    out, note, results, allow_old = None, "", RESULTS_PATH, False
    args = argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--out" and i + 1 < len(args):
            out = args[i + 1]; i += 2; continue
        if args[i] == "--note" and i + 1 < len(args):
            note = args[i + 1]; i += 2; continue
        if args[i] == "--results" and i + 1 < len(args):
            results = args[i + 1]; i += 2; continue
        if args[i] == "--allow-old-schema":
            allow_old = True; i += 1; continue
        if args[i] in ("-h", "--help"):
            print(__doc__); return
        i += 1
    pack(results_path=results, out_path=out, note=note, allow_old_schema=allow_old)


if __name__ == "__main__":
    main(sys.argv)
