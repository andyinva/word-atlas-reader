#!/usr/bin/env python3
"""
atlas_listed.py  -  the cross references, an outside check on the echoes

The echo tables (4, 4e, 6) find shared wording on their own, with no
list of known connections to tell them what they ought to find.  This
module gives them one: the cross references in Bible Search Lite's
bibles.db, the OpenBible.info set, which was built on the Treasury of
Scripture Knowledge (1830s) and then voted on by readers for years,
some 345,000 listings (about half that many distinct pairs, since most
are listed from both ends) each with its votes.  Used under its Creative
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
        self.rows = []              # one record per listing: (fb, fc, fs, fe, tb, tc, ts, te, votes)
        self.by_verse = {}          # (book, chapter, verse) -> [(row index, side)]; side 0 = from, 1 = to
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
        seen = {}
        for fb, fc, fs, fe, tb, tc, ts, te, votes in rows:
            if None in (fb, fc, fs, tb, tc, ts):
                continue
            fe = fe or fs
            te = te or ts
            # One record per link, found from either end: the set lists
            # most pairs twice, once from each verse with its own votes,
            # and a range on either side is one link however many verses
            # it spans; the two listings of a pair fold to one record
            # with the greater votes
            votes = int(votes or 0)
            this, other = (fb, fc, fs, fe), (tb, tc, ts, te)
            key = (this, other) if this <= other else (other, this)
            n = seen.get(key)
            if n is not None:
                row = self.rows[n]
                if votes > row[8]:
                    self.rows[n] = row[:8] + (votes,)
                continue
            n = len(self.rows)
            seen[key] = n
            self.rows.append((fb, fc, fs, fe, tb, tc, ts, te, votes))
            for v in range(fs, fe + 1):
                self.by_verse.setdefault((fb, fc, v), []).append((n, 0))
            for v in range(ts, te + 1):
                self.by_verse.setdefault((tb, tc, v), []).append((n, 1))
        self.count = len(self.rows)
        return True

    def ends(self, n, side):
        """The two ends of row n as (this side, other side), each (book, chapter, start, end)."""
        fb, fc, fs, fe, tb, tc, ts, te, votes = self.rows[n]
        this, other = (fb, fc, fs, fe), (tb, tc, ts, te)
        return (this, other) if side == 0 else (other, this)

    @staticmethod
    def text(end):
        """'Psalms 118:6-9' or 'Hebrews 13:6' for an end."""
        book, ch, start, stop = end
        return f"{book} {ch}:{start}" + (f"-{stop}" if stop != start else "")

    # --- lookups ------------------------------------------------------------------------
    def votes(self, ref_a, ref_b):
        """The most votes for a listed link between the two verses, or None when none is listed."""
        a, b = parse_ref(ref_a), parse_ref(ref_b)
        if not a or not b:
            return None
        best = None
        for n, side in self.by_verse.get((a[0], a[1], a[2]), []):
            _, (book, ch, start, end) = self.ends(n, side)
            if book == b[0] and ch == b[1] and (start <= b[2] <= end or start <= b[3] <= end):
                votes = self.rows[n][8]
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
        Returns {row: (this end, other end, votes)}, each listing once
        however many of these verses it spans, the ends as (book,
        chapter, start, end) with this end the one in these verses.
        """
        out = {}
        for ref in refs:
            r = parse_ref(ref)
            if not r:
                continue
            for n, side in self.by_verse.get((r[0], r[1], r[2]), []):
                if n in out:
                    continue
                this, other = self.ends(n, side)
                votes = self.rows[n][8]
                if votes < min_votes:
                    continue
                book, ch = other[0], other[1]
                if same_book is not None:
                    if book != same_book or ch == this[1]:
                        continue
                elif other_books is not None and book not in other_books:
                    continue
                elif other_books is None and book == this[0]:
                    continue
                out[n] = (this, other, votes)
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


def within(ref, end):
    """Whether a verse reference falls inside an end (book, chapter, start, stop)."""
    r = parse_ref(ref)
    return bool(r) and r[0] == end[0] and r[1] == end[1] and end[2] <= r[2] <= end[3]


def covered(link, found):
    """Whether a listed link (this end, other end, votes) is lit by a pair a table found: one verse in each end."""
    this, other, _ = link
    for a, b in found:
        if (within(a, this) and within(b, other)) or (within(b, this) and within(a, other)):
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
    held = {n for n, link in links.items() if covered(link, found)}
    # Kept on the section so that 4 and 4e can be reconciled once both
    # exist (reconcile below): what one holds, the other need not call missed
    sec.listed_links = {"links": links, "held": held, "what": what, "other": {}}
    sec.footer.append(render_footer(sec))


def render_footer(sec):
    """The listed-links footer from the data kept on the section."""
    data = sec.listed_links
    links, held, what, other = data["links"], data["held"], data["what"], data["other"]
    strong = {n for n, (a, b, v) in links.items() if v >= STRONG_VOTES}
    line = (f"Listed links ({MIN_VOTES} or more votes) from these verses to {what}: {len(links)}; "
            f"this table holds {len(held)} of them (counting every candidate echo, shown or not); "
            f"of the {len(strong)} with {STRONG_VOTES} or more votes, {len(strong & held)}.")
    # Links another echo table on the page holds are not misses of the
    # page, only of this table: counted apart and left off the list
    elsewhere = set()
    for label, held_there in other.items():
        found_there = (set(links) - held) & held_there
        if found_there:
            line += f"  {len(found_there)} more found by {label}."
            elsewhere |= found_there
    missed = {n: link for n, link in links.items() if n not in held and n not in elsewhere}
    if missed:
        strongest = sorted(missed.items(), key=lambda kv: (-kv[1][2], kv[0]))[:NAME_MOST]
        line += "  Strongest not found: " + "; ".join(
            f"{CrossRefs.text(a)} -> {CrossRefs.text(b)} ({v})" for n, (a, b, v) in strongest)
        if len(missed) > NAME_MOST:
            line += f"; and {len(missed) - NAME_MOST} more"
        line += "."
    return line + "  " + CREDIT


def reconcile(report):
    """
    Once a page has both table 4 and table 4e, let each footer count
    the links the other holds, so a quotation found in Greek is not
    called a miss of the page under the English table, nor the reverse.
    Called after 4e is built; a page with only one of the two is left
    as it is.
    """
    from atlas_report import number_of
    fours = [s for s in report.sections if number_of(s.title) == "4" and hasattr(s, "listed_links")]
    four_es = [s for s in report.sections if number_of(s.title) == "4e" and hasattr(s, "listed_links")]
    if not fours or not four_es:
        return
    held_4 = set().union(*(s.listed_links["held"] for s in fours))
    held_4e = set().union(*(s.listed_links["held"] for s in four_es))
    for s in fours:
        s.listed_links["other"]["4e (in Greek)"] = held_4e
    for s in four_es:
        s.listed_links["other"]["4 (by English wording)"] = held_4
    for s in fours + four_es:
        s.footer = [render_footer(s) if f.startswith("Listed links (") else f for f in s.footer]


LISTED_RE = re.compile(r"Listed links \((\d+) or more votes\) from these verses to (.+?): (\d+); this table holds (\d+)"
                       r".*?of the (\d+) with (\d+) or more votes, (\d+)")


def parse_footer(text):
    """(min votes, what, listed, held, strong listed, strong held) from a listed-links footer, or None."""
    m = LISTED_RE.search(text)
    if not m:
        return None
    return int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(7))
