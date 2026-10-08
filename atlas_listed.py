#!/usr/bin/env python3
"""
atlas_listed.py  -  the cross references, an outside check on the echoes

The echo tables (4, 4e, 6) find shared wording on their own, with no
list of known connections to tell them what they ought to find.  This
module gives them one: the cross references in Bible Search Lite's
bibles.db, the OpenBible.info set, which was built on the Treasury of
Scripture Knowledge (1830s) and then voted on by readers for years,
some 345,000 links each with its votes.  Used under its Creative
Commons Attribution licence; the credit line is CREDIT below and goes
into every table that draws on it.

What the pages do with it:

  - a 'listed' column on tables 4 and 4e: the votes for a link between
    a verse on each side of the echo, blank when no link is listed, so
    a known connection and a new find are told apart;
  - a footer under 4, 4e and 6 saying how many of the well-voted links
    from the text's verses the table holds, and naming the strongest
    it does not, which is where the method's blind spots show.

The set is read from the first file that has a cross_references table:
bibles.db where the atlas finds it, or cross_references.db beside the
program (an export of the table alone).  Without either the pages say
so in a footer and go on without the column.

A cross reference is a list of facts about which verse readers have
linked to which; it says nothing about why.  A link can be a quotation,
an allusion, a shared name or a shared theme, and most are the last
two, so 'listed' means 'readers have connected these verses', no more.
"""

import os
import re
import sqlite3

CREDIT = "Cross references from OpenBible.info (built on the Treasury of Scripture Knowledge), CC BY."
MIN_VOTES = 10          # a link with this many votes counts as well attested
STRONG_VOTES = 100      # and with this many, as one of the best known
NAME_MOST = 6           # how many missed links a footer names

PROGRAM_DIR = os.path.dirname(os.path.abspath(__file__))
REF = re.compile(r"^(.+?) (\d+):(\d+)(?:-(\d+))?$")


def parse_ref(ref):
    """'Psalms 36:8-9' -> ('Psalms', 36, 8, 9); 'Revelation 7:17' -> ('Revelation', 7, 17, 17); None if not a verse."""
    m = REF.match(ref.strip())
    if not m:
        return None
    book, ch, v, v2 = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    return book, ch, v, int(v2) if v2 else v


def candidate_paths():
    """Where the cross references may be: bibles.db as the atlas finds it, or an export beside the program."""
    paths = []
    try:
        # Imported here, not at the top: the Reader carries a copy of this
        # module for parse_footer and has no atlas_text
        import atlas_text
        paths.append(atlas_text.find_database())
    except (ImportError, SystemExit):
        pass
    paths.append(os.path.join(PROGRAM_DIR, "cross_references.db"))
    return paths


class CrossRefs:
    """
    The cross references in memory, indexed by verse on both sides, so
    that the votes for a link between any two verses are one lookup.
    """

    def __init__(self, path=None):
        self.path = None
        self.available = False
        self.by_verse = {}          # (book, chapter, verse) -> [(book, chapter, start, end, votes)]
        self.count = 0
        for p in ([path] if path else candidate_paths()):
            if p and os.path.exists(p) and self._load(p):
                self.path = p
                self.available = True
                break

    def _load(self, path):
        uri = "file:" + path.replace("\\", "/") + "?mode=ro"
        try:
            db = sqlite3.connect(uri, uri=True)
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "cross_references" not in tables:
                db.close()
                return False
            rows = db.execute("SELECT from_book, from_chapter, from_verse_start, from_verse_end, "
                              "to_book, to_chapter, to_verse_start, to_verse_end, relevance_score "
                              "FROM cross_references").fetchall()
            db.close()
        except sqlite3.Error:
            return False
        for fb, fc, fs, fe, tb, tc, ts, te, votes in rows:
            if None in (fb, fc, fs, tb, tc, ts):
                continue
            fe = fe or fs
            te = te or ts
            votes = int(votes or 0)
            # Both directions: a link is a pair, whichever side listed it
            for v in range(fs, fe + 1):
                self.by_verse.setdefault((fb, fc, v), []).append((tb, tc, ts, te, votes))
            for v in range(ts, te + 1):
                self.by_verse.setdefault((tb, tc, v), []).append((fb, fc, fs, fe, votes))
        self.count = len(rows)
        return True

    # --- lookups ------------------------------------------------------------------------
    def votes(self, ref_a, ref_b):
        """The most votes for a listed link between the two verses, or None when none is listed."""
        a, b = parse_ref(ref_a), parse_ref(ref_b)
        if not a or not b:
            return None
        best = None
        for book, ch, start, end, votes in self.by_verse.get((a[0], a[1], a[2]), []):
            if book == b[0] and ch == b[1] and (start <= b[2] <= end or start <= b[3] <= end):
                best = votes if best is None else max(best, votes)
        return best

    def votes_for_pairs(self, here, there):
        """The most votes over every (here verse, there verse) pair of a row, or None."""
        best = None
        for h in here:
            for t in there:
                v = self.votes(h, t)
                if v is not None and (best is None or v > best):
                    best = v
        return best

    def links_from(self, refs, other_books=None, same_book=None, min_votes=MIN_VOTES):
        """
        The listed links from these verses with at least min_votes:
        to the books in other_books (every other book when None), or,
        with same_book set, within that book but to another chapter.
        Returns {(from ref, to ref text): votes}, the to ref as a range
        ('Psalms 36:8-9') when the list gives one.
        """
        out = {}
        for ref in refs:
            r = parse_ref(ref)
            if not r:
                continue
            for book, ch, start, end, votes in self.by_verse.get((r[0], r[1], r[2]), []):
                if votes < min_votes:
                    continue
                if same_book is not None:
                    if book != same_book or ch == r[1]:
                        continue
                elif other_books is not None and book not in other_books:
                    continue
                elif other_books is None and book == r[0]:
                    continue
                to = f"{book} {ch}:{start}" + (f"-{end}" if end != start else "")
                key = (f"{r[0]} {r[1]}:{r[2]}", to)
                # Within a book a link is listed from both ends; keep one
                if same_book is not None and (ch, start) < (r[1], r[2]):
                    key = (to, f"{r[0]} {r[1]}:{r[2]}")
                if votes > out.get(key, -1):
                    out[key] = votes
        return out


def scope_refs(atlas, book, chapters=None):
    """Every verse reference of a book, or of some of its chapters."""
    if chapters:
        chapters = sorted(set(chapters))
        marks = ",".join("?" * len(chapters))
        rows = atlas.db.execute(f"SELECT reference FROM verses WHERE book = ? AND chapter IN ({marks})",
                                (book, *chapters))
    else:
        rows = atlas.db.execute("SELECT reference FROM verses WHERE book = ?", (book,))
    return [r[0] for r in rows]


def get(atlas):
    """The CrossRefs for this atlas, loaded once and kept on it."""
    if not hasattr(atlas, "_crossrefs"):
        atlas._crossrefs = CrossRefs()
    return atlas._crossrefs


def found_pairs(sec):
    """The (from, to) verse pairs a table's rows connect, from each row's refs, first ref against the rest."""
    pairs = set()
    for refs in sec.refs:
        if len(refs) >= 2:
            for t in refs[1:]:
                pairs.add((refs[0], t))
    return pairs


def covered(pair, found):
    """Whether a listed link (from ref, to ref or range) is among the pairs a table found."""
    f, t = pair
    tr = parse_ref(t)
    for a, b in found:
        if a != f and b != f:
            continue
        other = b if a == f else a
        o = parse_ref(other)
        if o and tr and o[0] == tr[0] and o[1] == tr[1] and tr[2] <= o[2] <= tr[3]:
            return True
    return False


def footer_for(sec, crossrefs, refs, other_books=None, same_book=None, what="other books", found=None):
    """
    Add the listed-links footer to a section: how many of the well-voted
    links from these verses the table holds, the strongest it does not,
    and the credit line.  The counts are written in one fixed form so
    atlas_results can read them back across a run.
    """
    if not crossrefs.available:
        sec.footer.append("Listed links: no cross references available (bibles.db without the "
                          "cross_references table, and no cross_references.db beside the program).")
        return
    links = crossrefs.links_from(refs, other_books=other_books, same_book=same_book)
    # The pairs the table found: every candidate it weighed, not only the
    # rows it shows, since a cap on rows is not a failure to find
    if found is None:
        found = found_pairs(sec)
    missed = {pair: v for pair, v in links.items() if not covered(pair, found)}
    held = len(links) - len(missed)
    strong = {pair: v for pair, v in links.items() if v >= STRONG_VOTES}
    strong_held = sum(1 for pair in strong if pair not in missed)
    line = (f"Listed links ({MIN_VOTES} or more votes) from these verses to {what}: {len(links)}; "
            f"this table holds {held} of them (counting every candidate echo, shown or not); "
            f"of the {len(strong)} with {STRONG_VOTES} or more votes, {strong_held}.")
    if missed:
        strongest = sorted(missed.items(), key=lambda kv: (-kv[1], kv[0]))[:NAME_MOST]
        line += "  Strongest not found: " + "; ".join(f"{a} -> {b} ({v})" for (a, b), v in strongest)
        if len(missed) > NAME_MOST:
            line += f"; and {len(missed) - NAME_MOST} more"
        line += ("." if len(missed) <= NAME_MOST else ".")
    sec.footer.append(line + "  " + CREDIT)


LISTED_RE = re.compile(r"Listed links \((\d+) or more votes\) from these verses to (.+?): (\d+); this table holds (\d+)"
                       r".*?of the (\d+) with (\d+) or more votes, (\d+)")


def parse_footer(text):
    """(min votes, what, listed, held, strong listed, strong held) from a listed-links footer, or None."""
    m = LISTED_RE.search(text)
    if not m:
        return None
    return int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(7))
