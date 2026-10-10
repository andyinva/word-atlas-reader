#!/usr/bin/env python3
"""
atlas_results.py

Questions across the whole canon, asked of reports/results.db, the
results database that `atlas_query.py dossier all --results` fills
(atlas_report.py).  Every answer is printed and also saved as a text
file under reports/, so a reader who works from the text files (the
reviewer) reads the answer the same way as a dossier.

    python3 atlas_results.py runs                     the runs in the database
    python3 atlas_results.py shares                   every New Testament book's share of Septuagint words (1f), ranked
    python3 atlas_results.py deltas                   every function-word Delta of a part from its rest (7d, 7.2d ...)
    python3 atlas_results.py seams                    the seams between the two taggings 4e found, counted across the canon
    python3 atlas_results.py declined                 every table that declined to measure, with its reason
    python3 atlas_results.py listed                   the echo tables (4, 4e, 6) against the cross references, book by book
    python3 atlas_results.py cited                    the same against the pairs the rabbinic library cites together (Sefaria)
    python3 atlas_results.py unlisted [N]             a random sample of N unlisted echo rows (default 100) to grade by hand; --seed S
    python3 atlas_results.py idiom                    the English echoes (4, 4f) by how many translations keep them: idiom or the originals' words
    python3 atlas_results.py section Isaiah 7d        one section of one page, as stored
    python3 atlas_results.py diff 1 2                 the cells that differ between two runs, page by page
    python3 atlas_results.py sql "SELECT ..."         any query, printed as a table

    --run N      read run N (default: the latest run)
    --out NAME   save under reports/results_NAME.txt (default: the question's name)

The tables: runs (version, build, started, note); pages (run_id, name,
title, kind, notes); sections (page_id, position, number, title, note,
kind, columns, n_rows); cells (section_id, row, col, column, value,
number); refs (section_id, row, reference); footers (section_id,
position, text).  A page's book is in its title's square brackets.

Author: Andrew Hopkins (with Claude)
"""

import os
import re
import sqlite3
import sys

from atlas_report import is_numeric_cell   # one alignment rule for pages and results
from atlas_listed import parse_footer         # the listed-links footer read back

PROGRAM_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(PROGRAM_DIR, "reports", "results.db")


def connect():
    if not os.path.exists(RESULTS_PATH):
        sys.exit(f"{RESULTS_PATH} not found: write it with  python3 atlas_query.py dossier all --results")
    db = sqlite3.connect(RESULTS_PATH)
    db.row_factory = sqlite3.Row
    return db


def latest_run(db):
    row = db.execute("SELECT MAX(run_id) FROM runs").fetchone()
    if row[0] is None:
        sys.exit("results.db holds no run yet")
    return row[0]


def book_of(title):
    """The subject in a page title's first square brackets: 'Isaiah' from 'Book page [Isaiah] (KJV)'."""
    m = re.search(r"\[([^\]]+)\]", title)
    return m.group(1) if m else title


def table(columns, rows):
    """Rows laid out as the pages lay them out: widths to fit, numbers right-aligned."""
    cells = [[str(v) if v is not None else "-" for v in row] for row in rows]
    widths = [len(c) for c in columns]
    for row in cells:
        for i, v in enumerate(row):
            widths[i] = max(widths[i], len(v))
    # Numbers and figure-like text ("501 / 3261", "15/66") right-aligned,
    # words left-aligned: the same rule the pages use (atlas_report)
    numeric = [all(is_numeric_cell(row[i]) for row in rows) for i in range(len(columns))]

    def fmt(values):
        return "  ".join(v.rjust(widths[i]) if numeric[i] else v.ljust(widths[i]) for i, v in enumerate(values)).rstrip()
    lines = [fmt(list(columns)), "-" * min(sum(widths) + 2 * len(widths), 110)]
    lines.extend(fmt(row) for row in cells)
    return "\n".join(lines)


def section_rows(db, section_id):
    """A stored section back as (columns, rows), numbers as numbers where they were."""
    sec = db.execute("SELECT columns, n_rows FROM sections WHERE section_id = ?", (section_id,)).fetchone()
    columns = sec["columns"].split("\t")
    rows = [[None] * len(columns) for _ in range(sec["n_rows"])]
    for c in db.execute("SELECT row, col, value, number FROM cells WHERE section_id = ?", (section_id,)):
        if c["col"] >= len(columns):
            continue
        # A number comes back as the page printed it: whole when it was
        # printed whole, otherwise as the decimal written
        if c["number"] is None:
            value = c["value"]
        elif "." in c["value"]:
            value = float(c["number"])
        else:
            value = int(c["number"])
        rows[c["row"]][c["col"]] = value
    return columns, rows


# --- the questions ------------------------------------------------------------
def q_runs(db, run):
    rows = [(r["run_id"], r["version"], r["started"], r["note"],
             db.execute("SELECT COUNT(*) FROM pages WHERE run_id = ?", (r["run_id"],)).fetchone()[0])
            for r in db.execute("SELECT * FROM runs ORDER BY run_id")]
    return "The runs in results.db", table(["run", "version", "started", "note", "pages"], rows)


def q_shares(db, run):
    """The 1f footer of every New Testament book page: 'Share ... : Jude 17.0%, 7th of 27 ...'."""
    rows = []
    for r in db.execute(
            "SELECT p.title, f.text FROM footers f JOIN sections s USING (section_id) JOIN pages p USING (page_id) "
            "WHERE p.run_id = ? AND p.kind = 'Book' AND s.number = '1f' AND f.text LIKE 'Share of content words%'", (run,)):
        m = re.search(r"Septuagint: (.+?) ([\d.]+)%, (\d+)(?:st|nd|rd|th) of (\d+)", r["text"])
        if m:
            rows.append((m.group(1), float(m.group(2)), int(m.group(3))))
    # The same order the page's footer ranks by (share, then name), so
    # the rank column and the list agree at a tie
    rows.sort(key=lambda t: (-t[1], t[0]))
    return ("Share of content words leaning to the Septuagint (1f), every New Testament book, from its own page",
            table(["book", "share %", "rank"], rows))


YARDSTICK = re.compile(r"about ([\d,]+) tokens ([\d.]+), nine in ten under ([\d.]+)")


def size_yardsticks(db, section_id):
    """
    The size yardsticks printed under a 7d table, parsed from its
    footer: [(tokens, median, nine in ten)], the testament's own line
    (the first "Size yardsticks" footer, not the kind's).
    """
    for f in db.execute("SELECT text FROM footers WHERE section_id = ? ORDER BY position", (section_id,)):
        if f["text"].startswith("Size yardsticks"):
            return [(int(a.replace(",", "")), float(b), float(c)) for a, b, c in YARDSTICK.findall(f["text"])]
    return []


def nine_in_ten(yardsticks, tokens):
    """The nine-in-ten line for a part's size: the nearest size struck, on a log scale; the largest beyond it."""
    if not yardsticks or not tokens:
        return None
    import math
    best = min(yardsticks, key=lambda y: abs(math.log(y[0]) - math.log(max(tokens, 1))))
    return best[2]


def q_deltas(db, run):
    """
    Every row of a function-word-by-section table: the part, its
    tokens, its Delta from its rest, the nine-in-ten yardstick for a
    part of its size, and the excess of the Delta over that line, which
    is what the list is sorted by: a small part stands far from its
    book by size alone, and the yardsticks were struck to discount it.
    One row per division and part (a cross-book division's table is on
    every page of the division); a two-part division, whose parts have
    the same Delta by construction, prints once as "A / B".
    """
    seen = {}
    order = []
    for s in db.execute(
            "SELECT s.section_id, s.number, s.title, p.title AS page FROM sections s JOIN pages p USING (page_id) "
            "WHERE p.run_id = ? AND s.title LIKE '%Function words by section%' ORDER BY p.page_id, s.position", (run,)):
        columns, data = section_rows(db, s["section_id"])
        try:
            i_text, i_tok, i_d, i_d2 = (columns.index("text"), columns.index("tokens"),
                                        columns.index("Delta"), columns.index("Delta (no pronouns)"))
        except ValueError:
            continue
        yardsticks = size_yardsticks(db, s["section_id"])
        division = s["title"]
        for row in data:
            if not isinstance(row[i_d], (int, float)):
                continue                      # a part that declined ("-")
            key = (division, row[i_text])
            if key in seen:
                continue
            line = nine_in_ten(yardsticks, row[i_tok])
            seen[key] = [book_of(division), s["number"], row[i_text], row[i_tok], row[i_d], row[i_d2], line,
                         round(row[i_d] - line, 2) if line is not None else None]
            order.append(key)
    # A two-part division: one row for the pair
    by_division = {}
    for key in order:
        by_division.setdefault(key[0], []).append(key)
    rows = []
    for division, keys in by_division.items():
        if len(keys) == 2 and seen[keys[0]][4] == seen[keys[1]][4]:
            a, b = seen[keys[0]], seen[keys[1]]
            rows.append([a[0], a[1], f"{a[2]} / {b[2]}", f"{a[3]} / {b[3]}", a[4], a[5],
                         a[6] if a[6] is not None and b[6] is not None and a[6] <= b[6] else b[6],
                         max(x for x in (a[7], b[7]) if x is not None) if (a[7] is not None or b[7] is not None) else None])
        else:
            rows.extend(seen[k] for k in keys)
    rows.sort(key=lambda t: -(t[7] if t[7] is not None else -9))
    return ("Every part's function-word Delta from its rest (7d and its repeats), with the nine-in-ten yardstick "
            "for a part of its size and the excess over it, largest excess first.  A part above its line stands "
            "further from its book than nine in ten runs of its size do; the yardsticks are two different books "
            "about 1.10 and the two halves of one book about 0.67",
            table(["division", "table", "part", "tokens", "Delta", "Delta (no pronouns)", "nine in ten (size)", "excess"], rows))


def q_seams(db, run):
    """The 'Seams between the two taggings' footers of 4e, parsed and counted across the canon."""
    counts = {}
    for r in db.execute(
            "SELECT p.title, f.text FROM footers f JOIN sections s USING (section_id) JOIN pages p USING (page_id) "
            "WHERE p.run_id = ? AND s.number = '4e' AND f.text LIKE 'Seams between the two taggings%'", (run,)):
        body = r["text"].split(": ", 1)[1].split(".  Each is either")[0]
        for item in body.split("; "):
            m = re.match(r"(.+?) \(([^|]+) \| ([^)]+)\) at (.+)", item.strip())
            if not m:
                continue
            word, k1, k2, ref = m.group(1), m.group(2).strip(), m.group(3).strip(), m.group(4).strip()
            # The pair of keys, whichever side each was on
            pair = tuple(sorted([k1, k2]))
            entry = counts.setdefault(pair, {"words": set(), "refs": [], "pages": set()})
            entry["words"].add(word)
            if ref not in entry["refs"]:          # the book page and the chapter page both list it
                entry["refs"].append(ref)
            entry["pages"].add(book_of(r["title"]))
    rows = []
    for (a, b), e in counts.items():
        rows.append((a, b, ", ".join(sorted(e["words"]))[:40], len(e["refs"]), len(e["pages"]),
                     ", ".join(e["refs"][:4]) + (" ..." if len(e["refs"]) > 4 else "")))
    rows.sort(key=lambda t: (-t[3], t[0]))
    return ("Seams between the two taggings (4e): the same word under two keys, counted across the canon.  "
            "Two legitimate numbers for one word want an equivalents row; one tagging's slip wants a lemma repair; "
            "the reading decides which",
            table(["key", "key", "word(s)", "places", "pages", "where"], rows))


def first_sentence(text, limit=150):
    """
    The reason as a reader needs it: whole sentences (a full stop
    followed by a space ends one, so 'lxx.db' does not) until at least
    sixty characters are in hand ("Not measured." alone says nothing),
    within the limit.
    """
    out = ""
    for m in re.finditer(r".*?\.(?=\s|$)", text, re.S):
        out = text[:m.end()].strip()
        if len(out) >= 60:
            break
    out = out or text
    return out if len(out) <= limit else out[:limit].rstrip() + " ..."


def q_declined(db, run):
    """
    Every table that declined to measure (no rows and a note beginning
    'Not measured'), and every table that declined for a part of what
    it covers (a footer beginning 'Not measured'), with the reason.
    """
    rows = []
    for r in db.execute(
            "SELECT p.title AS page, s.number, s.note FROM sections s JOIN pages p USING (page_id) "
            "WHERE p.run_id = ? AND s.n_rows = 0 AND s.note LIKE 'Not measured%' ORDER BY p.page_id, s.position", (run,)):
        rows.append((book_of(r["page"]), r["number"], "whole table", first_sentence(r["note"])))
    for r in db.execute(
            "SELECT p.title AS page, s.number, f.text FROM footers f JOIN sections s USING (section_id) "
            "JOIN pages p USING (page_id) WHERE p.run_id = ? AND f.text LIKE 'Not measured%' "
            "ORDER BY p.page_id, s.position, f.position", (run,)):
        rows.append((book_of(r["page"]), r["number"], "in part", first_sentence(r["text"])))
    return ("Every table that declined to measure, whole or in part, with the first sentence of its reason",
            table(["page", "table", "declined", "reason"], rows))


def q_section(db, run, book, number):
    page = db.execute(
        "SELECT page_id, title FROM pages WHERE run_id = ? AND kind = 'Book' AND title LIKE ? ORDER BY page_id LIMIT 1",
        (run, f"Book page [{book}]%")).fetchone()
    if page is None:
        sys.exit(f"no book page for {book} in run {run}")
    sec = db.execute("SELECT section_id, title, note FROM sections WHERE page_id = ? AND number = ?",
                     (page["page_id"], number)).fetchone()
    if sec is None:
        sys.exit(f"{book} has no section {number} in run {run}")
    columns, rows = section_rows(db, sec["section_id"])
    footers = [f["text"] for f in db.execute("SELECT text FROM footers WHERE section_id = ? ORDER BY position", (sec["section_id"],))]
    return sec["title"], table(columns, rows) + ("\n\n" + "\n".join(footers) if footers else "")


def q_diff(db, run_a, run_b):
    """
    The cells that differ between two runs: pages matched by title,
    sections by number, rows by their first cell (the word, the part,
    the echo), cells by column.  Prints the changed numbers and counts
    the rows added or dropped.
    """
    def load(run):
        out = {}
        for p in db.execute("SELECT page_id, title FROM pages WHERE run_id = ?", (run,)):
            for s in db.execute("SELECT section_id, number, columns FROM sections WHERE page_id = ?", (p["page_id"],)):
                columns = s["columns"].split("\t")
                rows = {}
                for c in db.execute("SELECT row, col, value FROM cells WHERE section_id = ? ORDER BY row, col", (s["section_id"],)):
                    rows.setdefault(c["row"], {})[c["col"]] = c["value"]
                keyed = {}
                for r, cells in rows.items():
                    key = cells.get(0, "")
                    if key in keyed:
                        key = f"{key} #{r}"
                    keyed[key] = cells
                out[(p["title"], s["number"])] = (columns, keyed)
        return out
    a, b = load(run_a), load(run_b)
    changed, added, dropped, missing_sections = [], 0, 0, []
    for key in sorted(set(a) | set(b)):
        if key not in a or key not in b:
            missing_sections.append((key[0], key[1], "only in run " + (str(run_a) if key in a else str(run_b))))
            continue
        cols_a, rows_a = a[key]
        cols_b, rows_b = b[key]
        for rk in set(rows_a) | set(rows_b):
            if rk not in rows_a:
                added += 1
                continue
            if rk not in rows_b:
                dropped += 1
                continue
            for ci, name in enumerate(cols_a):
                va, vb = rows_a[rk].get(ci), rows_b[rk].get(ci)
                if va != vb:
                    changed.append((book_of(key[0]), key[1], rk[:40], name, va, vb))
    head = (f"Run {run_a} against run {run_b}: {len(changed)} cells changed, {added} rows only in run {run_b}, "
            f"{dropped} rows only in run {run_a}, {len(missing_sections)} sections in one run only")
    body = table(["page", "table", "row", "column", f"run {run_a}", f"run {run_b}"], changed[:500])
    if len(changed) > 500:
        body += f"\n... and {len(changed) - 500} more"
    if missing_sections:
        body += "\n\n" + table(["page", "table", "note"], missing_sections[:100])
    return head, body


def q_listed(db, run, web="Listed links"):
    """
    The outside check across a run: for every book page's tables 4, 4e
    and 6, how many of the well-voted cross references (OpenBible.info
    on the Treasury of Scripture Knowledge) from the book's verses the
    table holds, from the footers the pages wrote.  'held' is the count
    the table reached, 'listed' the count to reach; the share is the
    recall of the echo layer against readers' own linking.  With
    web='Cited pairs' the same is read from the cited-pairs footers
    (Sefaria's library, 0.10.81; q_cited below).
    """
    rows = []
    like = web + " (%"
    for r in db.execute(
            "SELECT p.title, s.number, f.text FROM footers f JOIN sections s USING (section_id) "
            "JOIN pages p USING (page_id) WHERE p.run_id = ? AND p.kind = 'Book' AND s.number IN ('4', '4e') "
            "AND f.text LIKE ? ORDER BY p.page_id, s.number", (run, like)):
        parsed = parse_footer(r["text"])
        if parsed:
            _, what, listed, held, strong, strong_held = parsed
            share = round(100 * held / listed) if listed else None
            rows.append((book_of(r["title"]), r["number"], what, listed, held, share, strong, strong_held))
    # Table 6 writes its own form: links between chapters, and how many lit
    for r in db.execute(
            "SELECT p.title, f.text FROM footers f JOIN sections s USING (section_id) JOIN pages p USING (page_id) "
            "WHERE p.run_id = ? AND p.kind = 'Book' AND s.number = '6' AND f.text LIKE ? "
            "ORDER BY p.page_id", (run, like)):
        m = re.search(r"between different chapters of .+?: (\d+); (\d+) fall on a pair the map lights", r["text"])
        if m:
            listed, lit = int(m.group(1)), int(m.group(2))
            rows.append((book_of(r["title"]), "6", "its own chapters", listed, lit,
                         round(100 * lit / listed) if listed else None, "-", "-"))
    rows.sort(key=lambda t: (t[1], -(t[5] or -1), t[0]))
    total_listed = sum(t[3] for t in rows if t[1] == "4")
    total_held = sum(t[4] for t in rows if t[1] == "4")
    if web == "Cited pairs":
        head = (f"The echo tables against the pairs the rabbinic library cites together (derived from Sefaria's "
                f"links; pairs cited in 2 or more passages): how many of the cited pairs from each book's verses "
                f"the table holds.  The rabbis read two verses together above all for a word they share, so this "
                f"web tests the method on its own ground, where the cross references test it on theme.  "
                f"Table 4 over the run: {total_held} of {total_listed} held")
        columns = ["book", "table", "pairs to", "cited", "held", "held %", "10+ passages", "held"]
    else:
        head = (f"The echo tables against the cross references (OpenBible.info on the Treasury of Scripture "
                f"Knowledge, links with 10 or more votes): how many of the listed links from each book's verses the "
                f"table holds.  Table 4 over the run: {total_held} of {total_listed} held")
        columns = ["book", "table", "links to", "listed", "held", "held %", "100+ votes", "held"]
    head += (f" ({round(100 * total_held / total_listed)}%)" if total_listed else "") + "."
    return head, table(columns, rows)


def q_cited(db, run):
    """The echo tables against the cited pairs (Sefaria), book by book: q_listed on the other web's footers."""
    return q_listed(db, run, web="Cited pairs")


def q_unlisted(db, run, n=100, seed=1):
    """
    A random sample of the echo rows (tables 4 and 4e) that no cross
    reference lists, for grading by hand: real connection, shared idiom,
    or coincidence.  A hundred grades give the false-positive rate of the
    echo layer and the shape of its idiom, which is what tells which rule
    to tighten.  The sample is drawn with a fixed seed so it can be
    drawn again; --seed changes it.  A 'verdict' column is left blank.
    """
    import random
    rows = []
    for s in db.execute(
            "SELECT s.section_id, s.number, s.columns, p.title FROM sections s JOIN pages p USING (page_id) "
            "WHERE p.run_id = ? AND p.kind = 'Book' AND s.number IN ('4', '4e')", (run,)):
        columns = s["columns"].split("\t")
        if "listed" not in columns:
            continue
        li = columns.index("listed")
        cells = {}
        for c in db.execute("SELECT row, col, value FROM cells WHERE section_id = ?", (s["section_id"],)):
            cells.setdefault(c["row"], {})[c["col"]] = c["value"]
        for r, by_col in cells.items():
            if by_col.get(li, "") != "":
                continue
            if s["number"] == "4":
                echo, grade, here, there = by_col.get(0, ""), by_col.get(1, ""), by_col.get(2, ""), by_col.get(3, "")
            else:
                echo, grade, here, there = by_col.get(1, ""), by_col.get(4, ""), by_col.get(5, ""), by_col.get(6, "")
            rows.append((book_of(s["title"]), s["number"], echo[:50], grade, here[:40], there[:50], ""))
    random.Random(seed).shuffle(rows)
    sample = sorted(rows[:n], key=lambda t: (t[0], t[1]))
    head = (f"{len(rows)} unlisted echo rows in run {run} (tables 4 and 4e of the book pages, no cross reference "
            f"between the verses); a sample of {len(sample)}, seed {seed}.  Grade each in the verdict column: "
            f"real (a connection a reader would allow), idiom (the language's stock), coincidence (numbers, names), "
            f"or unsure.")
    return head, table(["book", "table", "echo", "grade", "here", "elsewhere", "verdict"], sample)


def q_idiom(db, run):
    """
    The echoes found by English wording across the run (table 4's 'by
    English' rows and every 4f row), by how the other English
    translations stand to them: the 'translations' and 'families' cells
    the pages wrote ('kept/asked').  An echo no other family keeps is
    the likeliest to be the King James translators' idiom; one every
    family keeps is the originals' own words.  The first list is the
    idiom candidates, rarest first as the pages rank them; the second
    the best attested; then a count by book.
    """
    rows = []
    for r in db.execute(
            "SELECT p.title, s.section_id, s.number, s.columns FROM sections s JOIN pages p USING (page_id) "
            "WHERE p.run_id = ? AND p.kind = 'Book' AND s.number IN ('4', '4f') ORDER BY p.page_id, s.number", (run,)):
        columns = r["columns"].split("\t")
        if "translations" not in columns or "families" not in columns:
            continue
        _, data = section_rows(db, r["section_id"])
        col = {c: i for i, c in enumerate(columns)}
        for row in data:
            if r["number"] == "4" and row[col.get("grade", 0)] != "by English":
                continue
            t_cell, f_cell = str(row[col["translations"]] or ""), str(row[col["families"]] or "")
            m1, m2 = re.match(r"(\d+)/(\d+)", t_cell), re.match(r"(\d+)/(\d+)", f_cell)
            if not m1 or not m2:
                continue
            kept, asked = int(m1.group(1)), int(m1.group(2))
            f_kept, f_asked = int(m2.group(1)), int(m2.group(2))
            where = ", ".join(str(row[col[c]]) for c in ("here", "elsewhere", "Septuagint", "New Testament") if c in col)
            rows.append((book_of(r["title"]), r["number"], row[0], where, kept, asked, f_kept, f_asked))
    if not rows:
        return ("No page of this run carries the translations columns: build translations_index.db "
                "(python3 atlas_translations.py build) and run the dossier again."), ""
    idiom = [t for t in rows if t[7] and t[6] <= 1]
    attested = sorted((t for t in rows if t[7] and t[6] == t[7] and t[7] >= 2), key=lambda t: (-t[4], t[0]))
    by_book = {}
    for t in rows:
        b = by_book.setdefault(t[0], [0, 0, 0])
        b[0] += 1
        b[1] += t[6] <= 1
        b[2] += t[7] >= 2 and t[6] == t[7]
    columns = ["book", "table", "echo", "verses", "kept", "asked", "families", "of"]
    head = (f"The {len(rows)} echoes found by English wording (table 4's 'by English' rows, every 4f row) "
            f"against the other English translations: {len(idiom)} are kept by no other family of translation "
            f"than the King James's (the likeliest translators' idiom), {len(attested)} by every family asked "
            f"(the originals' own words).  Counts, not scores; a translation keeps an echo when the same run "
            f"stands in both verses and in at most six of its verses.")
    body = ("Kept by the King James family alone, or by none:\n" + table(columns, idiom)
            + "\n\nKept by every family asked:\n" + table(columns, attested)
            + "\n\nBy book:\n" + table(["book", "English echoes", "idiom candidates", "every family"],
                                        [(b, *v) for b, v in sorted(by_book.items())]))
    return head, body


def q_sql(db, run, sql):
    cur = db.execute(sql)
    columns = [d[0] for d in cur.description]
    rows = [tuple(r) for r in cur.fetchall()]
    return f"{len(rows)} rows", table(columns, rows)


# --- main -------------------------------------------------------------------------
def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return
    args = argv[1:]
    run = None
    out_name = None
    seed = 1
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--run" and i + 1 < len(args):
            run = int(args[i + 1]); i += 2; continue
        if args[i] == "--out" and i + 1 < len(args):
            out_name = args[i + 1]; i += 2; continue
        if args[i] == "--seed" and i + 1 < len(args):
            seed = int(args[i + 1]); i += 2; continue
        rest.append(args[i]); i += 1
    command = rest[0].lower()
    db = connect()
    if run is None:
        run = latest_run(db)
    if command == "runs":
        head, body = q_runs(db, run)
    elif command == "shares":
        head, body = q_shares(db, run)
    elif command == "deltas":
        head, body = q_deltas(db, run)
    elif command == "seams":
        head, body = q_seams(db, run)
    elif command == "declined":
        head, body = q_declined(db, run)
    elif command == "listed":
        head, body = q_listed(db, run)
    elif command == "cited":
        head, body = q_cited(db, run)
    elif command == "unlisted":
        n = int(rest[1]) if len(rest) > 1 else 100
        head, body = q_unlisted(db, run, n, seed)
    elif command == "idiom":
        head, body = q_idiom(db, run)
    elif command == "section" and len(rest) >= 3:
        head, body = q_section(db, run, " ".join(rest[1:-1]), rest[-1])
    elif command == "diff" and len(rest) == 3:
        head, body = q_diff(db, int(rest[1]), int(rest[2]))
    elif command == "sql" and len(rest) >= 2:
        head, body = q_sql(db, run, " ".join(rest[1:]))
    else:
        print(__doc__)
        return
    version = db.execute("SELECT version, started FROM runs WHERE run_id = ?", (run,)).fetchone()
    text = (f"WORD ATLAS  -  Results: {command} (run {run}, Word Atlas {version['version']}, {version['started']})\n"
            + "#" * 60 + "\n" + head + "\n\n" + body + "\n")
    try:
        print(text)
    except BrokenPipeError:
        pass
    name = out_name or (command if command != "sql" else "sql")
    os.makedirs(os.path.join(PROGRAM_DIR, "reports"), exist_ok=True)
    path = os.path.join(PROGRAM_DIR, "reports", f"results_{name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"(saved to {path})")


if __name__ == "__main__":
    main(sys.argv)
