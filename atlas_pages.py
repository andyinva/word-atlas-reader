"""
Word Atlas - the pages
======================

Builds every atlas page as DATA rather than text: a Report made of
Sections, each Section a table of columns and rows, with a note under
it and, for every row, the verse references and the link it can lead
to.  The command-line script (atlas_query.py) renders a Report as
plain text; the window (word_atlas.py) shows the same Report as
tables.  One set of logic, two displays.

    Report
      .title, .notes (lines under the title)
      .sections: [Section]
    Section
      .title, .note, .columns, .rows
      .refs[i]   verse references behind row i (shown when the row is clicked)
      .links[i]  where row i can lead: {"word": root} or {"book": b, "chapter": c}

Pages: book_page, chapter_page, word_page, kin_page.

Author: Andrew Hopkins (with Claude)
"""

import math
import os
import re
import sqlite3
import time
from collections import Counter, defaultdict

from atlas_function import book_table as function_book_table, section_table as function_section_table
from atlas_septuagint import vocabulary_sections as septuagint_vocabulary_sections, \
    echoes_section as septuagint_echoes_section
from atlas_sections import (FEW_WORDS, SMALL_WORDS, divisions_of, find_section, sections_of, section_date,
                            section_of, seam_chapters, span_text, cross_divisions, find_cross_section,
                            cross_sections_of_book, is_cross_group, parts_text)
from atlas_function import cross_section_table as function_cross_section_table
from atlas_text import (ATLAS_PATH, ECHO_MAX_TOTAL, FOCUS_MIN_OCCURRENCES,
                        FORMULA_LENGTHS, PARALLEL_METHOD, PARALLEL_MIN_SHARED,
                        PARALLEL_RUN, PARALLEL_RUN_CONTENT, PARALLEL_SHARE, STOPLIST,
                        Stemmer, has_substance, log_likelihood, relation_in_time, trim_formula, BOOK_DATES,
                        CRITICAL_DATES, DISPUTED_DATES, dating_dispute)

# A Strong's number as a root or inside a printed label ("lord H3068")
STRONGS_IN_TEXT = re.compile(r"(?:^|\s|\()([HG]\d{1,5})(?:$|\s|\))")


def is_strongs(root):
    """Is this root a Strong's number (H3068, G3056) rather than an English stem?"""
    return bool(root) and root[0] in "HG" and root[1:].isdigit()


VERSION = "0.10.74"   # the program version; the window title and every report print it

TOP_N = 25          # rows per table
COMPANY_N = 15      # rows per neighbors column
ECHO_N = 60         # echoes shown per page, best first
KIN_N = 25          # kin chapters shown
KIN_CHAPTER_N = 8   # kin chapters at the foot of a chapter page
KIN_MIN_SHARED = 3  # rare words two verses must share to count as kin
VOCAB_MAX_CHAPTERS = 5   # 6d: a word in more chapters of the book than this is the book's, not a pair's
VOCAB_MIN_RARITY = 200   # 6d: words commoner than 1 in this many across the Bible are left out
LOCAL_SHARE = 0.2   # a signature word is "local" below this share of chapters
LOCAL_RENDERING_SHARE = 0.5   # a rendering is this text's own when it holds this share of the Bible's uses
NEST_COVER = 0.8    # a shorter formula folds into a longer one covering this share of its verses
FOCUS_WORDS = ["day", "LORD"]   # always shown on a book page, plus top signature words
HOME_PER_BOOK = 2               # roots per book on the testament home map
HOME_MIN_WEIGHT = 5             # a root needs this many occurrences to be a home word
HOME_LIST_N = 150               # roots in the "whose word is this" table
GROUP_SMALL_WORDS = 30000       # a baseline group (1b) under this many words is marked 'small kind'
BOOK_SMALL_WORDS = 5000         # a book under this many words is marked 'small book' in 1 and 1b: most rows rest on 5 to 7 uses
GROUP_KEYNESS_FLOOR = 6.63      # 1b shows a row only above this group keyness: the 1 percent line of a one-degree log-likelihood
WORDS_PER_OCCURRENCE = 1500     # 1b's occurrence floor scales with the book: one use per this many words ...
SHORT_BOOK_MIN_WEIGHT = 3       # ... never under this (Nahum's Nineveh, lion and prey have three or four uses each) and never over HOME_MIN_WEIGHT
REACH_DEPTH_N = 40              # words on the reach-and-depth chart, by keyness
REACH_DEPTH_DEEP_N = 20         # plus this many by depth, so the local piles are on it
COMPANION_SHARE = 0.3           # an absorbed word shown with its root when beside this share of it
# The KJV's hyphenated three-word renderings, joined before the
# commonest-spelling choice: "law (mother) H2545" reads as "mother-in-law"
JOINED_RENDERINGS = {("law", "mother"): "mother-in-law", ("law", "father"): "father-in-law",
                     ("law", "daughter"): "daughter-in-law", ("law", "son"): "son-in-law",
                     ("law", "brother"): "brother-in-law"}
CROSS_MIN_PHRASES = 5           # a chapter's closest partner counts toward order only from this many phrases
CROSS_REFRAIN_MIN_VERSES = 4    # between books a refrain must also fill this many verses of its book
CROSS_LIST_MIN_PHRASES = 3      # a closest partner is printed from this many shared phrases, or ...
CROSS_LIST_MIN_WEIGHT = 35      # ... from this weight (two rare phrases, or one very rare one) ...
CROSS_LIST_FLOOR = 0.1          # ... and always from this share of the page's third strongest pair
CROSS_MAX_VERSES = 12           # a phrase in more verses of the two compared books is idiom, not a link
REFRAIN_MIN_CHAPTERS = 3        # a phrase in this many chapters of a book is a refrain, not a pair
DOUBLET_GAP = 3                 # chapters this far apart that share phrasing are doublet candidates
WITHIN_PAIRS_N = 12             # strongest chapter pairs named under the within-book map
WITHIN_MAX_VERSES = 12          # a phrase in more verses of the book than this is the book's idiom, not a self-echo
LEADING_MIN_DEPTH = 10          # a chapter's leading words need at least this depth
LEADING_FILL_TO = 4             # fewer leading words than this are filled out with the chapter's key words
ORDER_RUN_GAPPED_MIN = 6        # a run with any gap needs this many pointers to be reported
ORDER_RUN_MIN = 4               # chapters in order before 4b reports "follows the order of"
PARALLEL_TRIALS = (0.4, 0.5)    # shares tried beside PARALLEL_SHARE in the 4d footer
PARALLEL_COMMON_SHARE = 0.10    # a root in more of a book's verses than this is formulaic there
GOSPELS = {"Matthew", "Mark", "Luke", "John"}
INTERJECTIONS = {"oh", "o", "ah", "alas", "behold", "lo", "yea", "nay", "amen", "selah", "woe"}
RATIO_MIN_ECHOES = 20           # obs/exp on fewer echoes is marked 'few'
QUOTE_MIN_WORDS = 5             # an echo this long in exactly two verses is quotation grade
PARALLEL_MIN_APPLIES = 0.05     # 4d is left out when fewer verses than this share have a parallel
DIVINE_ROOTS = {"H3068", "H3069", "H136", "H430", "H410", "H433", "H3050", "H7706",   # names of God, not of the cast
                "G2962", "G2316", "G2424", "G5547"}                                    # ... and Jesus, Christ
NARROW_PARTNER_SHARE = 0.8      # a partner with this share of its echo weight in five chapters is too narrow for 4d
WHO_READS_N = 3                 # rarest echoes cited per partner in the who-reads-whom table


# Report and Section, what a page is made of, live in atlas_report.py
# (the reporting module) and are imported here, so that atlas_pages.Report
# and atlas_pages.Section keep working for the window and the scripts
from atlas_report import Report, Section  # noqa: E402,F401

# ---------------------------------------------------------------------------
# Atlas: read-only access to atlas.db
# ---------------------------------------------------------------------------

class Atlas:
    """A read-only view of atlas.db with the queries the pages need."""

    def __init__(self, path=ATLAS_PATH):
        if not os.path.exists(path):
            raise SystemExit(f"{path} not found.  Run build_atlas.py first.")
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        # An atlas.db built by an older build_atlas.py lacks columns the
        # pages need; say so plainly rather than failing mid-query
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(words)")}
        if "form" not in columns:
            raise SystemExit(f"{path} was built by an older version of build_atlas.py.  "
                             f"Run build_atlas.py again (about a minute) and retry.")
        self.settings = dict(self.db.execute("SELECT key, value FROM settings"))
        self.path = path
        # Depth (0.6.0) needs columns an older build lacks; the pages
        # leave the depth sections out rather than fail
        self.has_depth = "depth" in {r[1] for r in self.db.execute("PRAGMA table_info(word_book)")}
        # Formulas on root units (phase 5, last step): the verses table
        # then carries a phrase_string beside word_string, and ngrams and
        # echoes carry an English display beside their unit key
        verse_columns = {r[1] for r in self.db.execute("PRAGMA table_info(verses)")}
        self.formula_roots = self.settings.get("formula_roots", "english")
        self.phrase_column = "phrase_string" if "phrase_string" in verse_columns else "word_string"
        self.has_display = "display" in {r[1] for r in self.db.execute("PRAGMA table_info(ngrams)")}
        self.books = [r["book"] for r in self.db.execute(
            "SELECT book FROM books ORDER BY order_index")]
        self.book_info = {r["book"]: dict(r) for r in self.db.execute("SELECT * FROM books")}
        self.n_bible = sum(b["words"] for b in self.book_info.values())
        # Words per testament: a Strong's number is compared with its own
        # testament (H with the Old, G with the New), an English stem
        # with the whole Bible
        self.n_testament = Counter()
        for b in self.book_info.values():
            self.n_testament[b["testament"]] += b["words"]
        self.books_in_testament = Counter(b["testament"] for b in self.book_info.values())
        self.window = int(self.settings["window"])
        # The stemmer only needs the vocabulary to root a typed word;
        # the tokens table already holds the roots the build used
        vocab = {r[0] for r in self.db.execute("SELECT DISTINCT surface FROM tokens")}
        self.stemmer = Stemmer(vocab)
        # Display form for every root ("hundred" for the stem "hundr")
        self.forms = dict(self.db.execute("SELECT root, form FROM words"))
        # Phase 5: are the roots Strong's numbers?  If so the lexicon
        # table gives each number its Hebrew or Greek word and glosses.
        self.roots_mode = self.settings.get("roots", "english")
        self.lexicon = {}
        if "lexicon" in {r[0] for r in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}:
            self.lexicon = {r[0]: (r[1], r[2], r[3]) for r in self.db.execute(
                "SELECT number, word, kjv_def, strongs_def FROM lexicon")}
        self._stem_groups = None      # English stem -> surfaces, built when first needed
        self._scope_forms = []        # spellings of the page's book and chapter (use_scope)
        # Does this text print the divine name in capitals?  Count the
        # spellings so a page can say which it is looking at.
        self.name_forms = {r[0]: r[1] for r in self.db.execute(
            "SELECT surface, COUNT(*) FROM tokens WHERE surface IN ('LORD','Lord','lord','GOD') "
            "GROUP BY surface")}

    def testament_of_root(self, root):
        """'Old' for H numbers, 'New' for G numbers, None for an English stem."""
        if is_strongs(root):
            return "Old" if root[0] == "H" else "New"
        return None

    def comparison_words(self, root):
        """How many words a root is judged against: its testament or the Bible."""
        t = self.testament_of_root(root)
        return self.n_testament[t] if t else self.n_bible

    def comparison_books(self, root):
        """How many books a root could reach: 39, 27 or 66."""
        t = self.testament_of_root(root)
        return self.books_in_testament[t] if t else 66

    def renderings(self, root):
        """
        How many different English words the text uses for a root, with
        inflections folded (leave, left and leaveth are one rendering;
        forgive and let are two more).  1 for an English stem.
        """
        if not is_strongs(root):
            return 1
        stems = {sp if sp.isupper() else self.stemmer.root(sp.lower())
                 for sp, n in self.spellings(root, limit=40) if n >= 2}
        return max(1, len(stems))

    def is_name(self, root):
        """
        Is this root a proper name?  Judged from the text itself: its
        commonest spelling appears with a capital letter inside verses
        (not at their start) more often than without.  Catches Job,
        Jerusalem, Satan and the divine names alike.
        """
        cache = self.__dict__.setdefault("_names", {})
        if root not in cache:
            spelling = self.forms.get(root, root)
            if spelling in INTERJECTIONS:
                cache[root] = False
            elif not spelling or not spelling[0].isalpha() or spelling.isupper():
                cache[root] = spelling.isupper() if spelling else False
            else:
                # Counted once for every word of the text in one pass
                # (the verses holding the word with a capital inside the
                # verse, and those holding it without), not with two
                # scans of all 31,000 verses per word: at 20 milliseconds
                # a scan, the 25 signature words of a chapter page cost
                # most of a second each page, which was the chapter
                # pages' doubled time in the canon-wide run
                counts = self.capital_counts()
                low, cap = spelling.lower(), spelling[0].upper() + spelling[1:]
                cache[root] = counts.get(cap, 0) > counts.get(low, 0)
        return cache[root]

    def capital_counts(self):
        """
        word -> the number of verses holding that exact spelling inside
        the verse (after the first word, which the old test skipped too,
        since every verse begins with a capital), capitalised and
        uncapitalised counted apart.  Built once.
        """
        cache = self.__dict__.get("_capital_counts")
        if cache is not None:
            return cache
        import re as _re
        # The text joins compound names with an en dash (Beer–sheba,
        # Eli–ezer, Pedah–zur), not an ASCII hyphen, so the dash must sit
        # in the word class or the second half breaks off as a lowercase
        # word of its own: 0.10.55 counted "sheba" 43 times that way and
        # lost Sheba, Er, Ur and Ezer their names
        word_re = _re.compile(r"[A-Za-z][A-Za-z'\-‐‑–]*")
        cache = Counter()
        for (text,) in self.db.execute("SELECT text FROM verses"):
            seen = set()
            # Scan from the first character and skip the match that
            # starts there; scanning from the second character instead
            # (as 0.10.55 did) clips the verse's first word to its tail,
            # so "Our" and "Her" were counted as the words "ur" and "er"
            # and outvoted the names Ur and Er
            for m in word_re.finditer(text):
                if m.start() == 0:
                    continue
                w = m.group().rstrip("'-")
                if w and w not in seen:
                    seen.add(w)
            cache.update(seen)
        self._capital_counts = cache
        return cache

    def form(self, root):
        """
        A root as the pages print it: its commonest spelling, and, when
        the root is a Strong's number, the number after it ("lord H3068",
        "lord H136") so two roots with one English spelling stay apart.
        """
        # On a book or chapter page the spelling is the scope's own
        # commonest: H1540 is "captive" across the Bible but "uncover"
        # in Leviticus 18, and H2490 "began" everywhere but "profane" in
        # Leviticus 21.  The chapter's spelling first, then the book's,
        # then the Bible's.
        spelling = None
        for scoped in self._scope_forms:
            if root in scoped:
                spelling = scoped[root]
                break
        if spelling is None:
            spelling = self.forms.get(root, root)
        if is_strongs(root):
            # A word absorbed into this root often enough is shown with
            # it: "law (father) H2859", "priests (chief) G749",
            # "offering (burnt) H5930"
            companion = self.companions().get(root)
            if companion:
                joined = JOINED_RENDERINGS.get((spelling, companion))
                if joined:
                    return f"{joined} {root}"
                return f"{spelling} ({companion}) {root}"
            return f"{spelling} {root}"
        return spelling

    def companions(self):
        """
        root -> the word most often absorbed into it, when that word
        stands beside at least COMPANION_SHARE of the root's occurrences.
        Built once from the tokens marked "=".
        """
        cache = self.__dict__.get("_companions")
        if cache is not None:
            return cache
        best = {}
        for root, surface, n in self.db.execute(
                "SELECT root, surface, COUNT(*) FROM tokens WHERE strongs LIKE '=%' GROUP BY root, surface"):
            if root not in best or n > best[root][1]:
                best[root] = (surface, n)
        cache = {}
        for root, (surface, n) in best.items():
            row = self.word_row(root)
            if row and n >= COMPANION_SHARE * row["weight"]:
                cache[root] = surface
        self._companions = cache
        return cache

    def use_scope(self, book=None, chapter=None):
        """
        Make form() prefer the spellings of one book, and of one chapter
        within it, until called again with no arguments.  One query per
        scope: root -> commonest spelling there.
        """
        self._scope_forms = []
        if book is None:
            return
        scopes = [(book, chapter)] if chapter is not None else []
        scopes.append((book, None))
        for b, c in scopes:
            sql = ("SELECT t.root, t.surface, COUNT(*) AS n FROM tokens t JOIN verses v USING (verse_id) "
                   "WHERE v.book = ? AND t.is_stop = 0" + (" AND v.chapter = ?" if c is not None else "")
                   + " GROUP BY t.root, t.surface")
            best = {}
            for root, surface, n in self.db.execute(sql, (b, c) if c is not None else (b,)):
                if root not in best or n > best[root][1]:
                    best[root] = (surface, n)
            self._scope_forms.append({r: sp for r, (sp, n) in best.items()})

    def lexicon_entry(self, root):
        """(original word, KJV glosses, Strong's definition) for a number, or None."""
        return self.lexicon.get(root)

    def gloss(self, root):
        """A short line for a Strong's number: 'יְהֹוָה: Jehovah, the Lord'."""
        entry = self.lexicon.get(root)
        if not entry:
            return ""
        word, kjv_def, strongs_def = entry
        text = clean_gloss(kjv_def or strongs_def, 80)
        return f"{word}: {text}" if word else text

    def aramaic_roots(self):
        """
        The Strong's numbers the lexicon marks as Aramaic (its derivation
        opens "(Aramaic)" or, in older printings, "(Chaldee)"): about 675
        of the Hebrew numbers, H4430 "king" beside the Hebrew H4428.
        Empty when no lexicon is loaded.  Cached for the session.
        """
        if not hasattr(self, "_aramaic"):
            try:
                self._aramaic = {r[0] for r in self.db.execute(
                    "SELECT number FROM lexicon WHERE derivation LIKE '(Aramaic)%' "
                    "OR derivation LIKE '(Chaldee)%'")}
            except sqlite3.OperationalError:
                self._aramaic = set()
        return self._aramaic

    def language_note(self, book, chapter=None):
        """
        One line saying where a book's tagged words are Aramaic rather
        than Hebrew, chapter by chapter, or None when none are.  The
        Aramaic of Daniel 2:4 to 7:28 and Ezra 4:8 to 6:18 and 7:12 to
        7:26 is found through the lexicon's marking of the roots, with
        no list of passages typed in; the odd Aramaic verse (Jeremiah
        10:11, the two words of Genesis 31:47) shows as a count with its
        reference.  With a chapter, the line is for that chapter alone.
        Only tagged content words count (root H..., not a stop word), so
        the share is of the words the atlas counts; inferred tags (~) are
        left out, since inference at book scope can hand a Hebrew word in
        Daniel 1 or Genesis 20 an Aramaic number ("sawest" ~H2370), and
        the placed tags are the tagger's own word.
        """
        aramaic = self.aramaic_roots()
        if not aramaic or self.book_info[book]["testament"] != "Old":
            return None
        where = "v.book = ?" + (" AND v.chapter = ?" if chapter else "")
        args = (book, chapter) if chapter else (book,)
        tagged, found = Counter(), Counter()
        refs = {}
        for ch, verse, root in self.db.execute(
                "SELECT v.chapter, v.verse, t.root FROM tokens t JOIN verses v USING (verse_id) "
                f"WHERE {where} AND t.root LIKE 'H%' AND t.is_stop = 0 "
                "AND t.strongs NOT LIKE '~%'", args):
            tagged[ch] += 1
            if root in aramaic:
                found[ch] += 1
                refs.setdefault(ch, set()).add(verse)
        if not found:
            return None
        parts = []
        for ch in sorted(found):
            share = found[ch] / tagged[ch]
            if share >= 0.05:
                parts.append(f"{ch} ({share:.0%})")
            else:
                verses = sorted(refs[ch])
                where_ = ", ".join(f"{ch}:{v}" for v in verses[:3]) + (" ..." if len(verses) > 3 else "")
                parts.append(f"{ch} ({found[ch]} word{'s' if found[ch] != 1 else ''}, {where_})")
        total = sum(found.values()) / max(1, sum(tagged.values()))
        head = (f"Languages: Aramaic roots (marked so in Strong's lexicon) carry {total:.0%} of the tagged "
                f"words of {book}" + (f" {chapter}" if chapter else "") + "; by chapter, the share that is Aramaic: ")
        return head + "; ".join(parts) + ".  The rest is Hebrew."

    def baseline_groups(self):
        """
        book -> its baseline group (Law, History, Poetry, Prophecy, NT
        Narrative, Epistles) from the books table of metadata.db, the
        catalogue of decided knowledge kept beside the atlas (see
        METADATA_IN_WORD_ATLAS.md).  Empty when the file is not there, and
        the group table (1b) is then left off the page.  Read once.
        """
        if not hasattr(self, "_groups"):
            self._groups = {}
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metadata.db")
            if os.path.exists(path):
                try:
                    meta = sqlite3.connect(path)
                    self._groups = dict(meta.execute("SELECT name, baseline_group FROM books"))
                    meta.close()
                except sqlite3.Error:
                    self._groups = {}
        return self._groups

    def passages(self):
        """
        The named passages of metadata.db: name -> (description, [(book,
        chapter_start, verse_start, chapter_end, verse_end)]), a verse_end
        of 999 meaning the chapter's end.  A passage is any set of verse
        ranges in any books ("Harlot city": Ezekiel 16 and 23 with
        Revelation 17 to 19), kept in the catalogue and made to be
        measured; atlas_passages.py adds and removes them.  Empty when
        the file is not there.  Read once per session.
        """
        if not hasattr(self, "_passages"):
            self._passages = {}
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metadata.db")
            if os.path.exists(path):
                try:
                    meta = sqlite3.connect(path)
                    for name, desc, book, c1, v1, c2, v2 in meta.execute(
                            "SELECT p.name, p.description, b.name, r.chapter_start, r.verse_start, "
                            "r.chapter_end, r.verse_end FROM passages p JOIN passage_ranges r USING (passage_id) "
                            "JOIN books b USING (book_num) ORDER BY p.name COLLATE NOCASE, b.book_num, "
                            "r.chapter_start, r.verse_start"):
                        self._passages.setdefault(name, (desc, []))[1].append((book, c1, v1, c2, v2))
                    meta.close()
                except sqlite3.Error:
                    self._passages = {}
        return self._passages

    def passage_verses(self, name):
        """The verse rows of a named passage, in canonical order; [] when unknown."""
        entry = self.passages().get(name)
        if entry is None:
            for key, value in self.passages().items():
                if key.lower() == name.lower():
                    entry = value
                    break
        if entry is None:
            return []
        out, seen = [], set()
        for book, c1, v1, c2, v2 in entry[1]:
            for v in self.verses_of(book):
                ch, vs = v["chapter"], v["verse"]
                if (ch, vs) < (c1, v1) or (ch, vs) > (c2, v2):
                    continue
                if v["verse_id"] not in seen:
                    seen.add(v["verse_id"])
                    out.append(v)
        return out

    def aramaic_refs(self):
        """
        The references of the verses the build judged Aramaic by their
        placed tags (verses.language, from 0.10.15): Daniel 2:4 to 7:28,
        Ezra 4:8 to 6:18 and 7:12 to 7:26, Jeremiah 10:11.  Empty on an
        older build, which then has no bridge inside a testament.
        """
        if not hasattr(self, "_aramaic_refs"):
            try:
                self._aramaic_refs = {r[0] for r in self.db.execute(
                    "SELECT reference FROM verses WHERE language = 'Aramaic'")}
            except sqlite3.OperationalError:
                self._aramaic_refs = set()
        return self._aramaic_refs

    def language_of(self, reference, book=None):
        """
        "Hebrew", "Aramaic" or "Greek" for a verse.  Two verses in
        different languages share no root, so the pages bridge them by
        English wording, as they always did between the testaments.
        """
        book = book or reference.rsplit(" ", 1)[0]
        if self.book_info[book]["testament"] == "New":
            return "Greek"
        return "Aramaic" if reference in self.aramaic_refs() else "Hebrew"

    def languages_of(self, book):
        """The languages a book's verses are in: {"Hebrew", "Aramaic"} for Daniel."""
        if self.book_info[book]["testament"] == "New":
            return {"Greek"}
        prefix = book + " "
        two = any(r.startswith(prefix) for r in self.aramaic_refs())
        return {"Hebrew", "Aramaic"} if two else {"Hebrew"}

    def local_renderings(self, book, limit=12):
        """
        Every form a book owns, by the rule of local_rendering(), over
        all its roots at once (two grouped queries rather than two per
        root): [(root, form, n_here, n_all, kind)], most held first.
        Lists the idioms the formulas cannot form ("rising up early" is
        one root), under section 1 of the book page.
        """
        # kind: 0 a spelling of the root (a content token), 1 a word absorbed
        # into it (strongs '=N'); a placed tag on a stop word is neither
        kind_sql = "CASE WHEN t.strongs LIKE '=%' THEN 1 WHEN t.is_stop = 0 THEN 0 ELSE NULL END"
        here = {}
        for root, absorbed, surface, n in self.db.execute(
                f"SELECT t.root, {kind_sql}, LOWER(t.surface), COUNT(*) FROM tokens t JOIN verses v "
                "USING (verse_id) WHERE v.book = ? AND (t.root LIKE 'H%' OR t.root LIKE 'G%') "
                "GROUP BY 1, 2, 3", (book,)):
            if absorbed is not None:
                here.setdefault((root, absorbed), []).append((surface, n))
        if not hasattr(self, "_forms_everywhere"):
            everywhere = {}
            for root, absorbed, surface, n in self.db.execute(
                    f"SELECT t.root, {kind_sql}, LOWER(t.surface), COUNT(*) FROM tokens t "
                    "WHERE t.root LIKE 'H%' OR t.root LIKE 'G%' GROUP BY 1, 2, 3"):
                if absorbed is not None:
                    everywhere.setdefault((root, absorbed), {})[surface] = n
            self._forms_everywhere = everywhere
        everywhere = self._forms_everywhere
        out = []
        for (root, absorbed), forms in here.items():
            if not is_strongs(root):
                continue
            form, n_here = max(forms, key=lambda fn: fn[1])
            all_forms = everywhere.get((root, absorbed), {})
            n_all = all_forms.get(form, n_here)
            total_forms = sum(all_forms.values()) or 1
            if n_here >= 3 and n_here >= LOCAL_RENDERING_SHARE * n_all and n_all / total_forms < 0.5:
                out.append((root, form, n_here, n_all, "absorbed word" if absorbed else "spelling"))
        out.sort(key=lambda t: (-t[2], t[0]))
        return out[:limit]

    def local_rendering(self, root, book, chapter=None):
        """
        A rendering this text owns: the commonest spelling of the root
        here, or the commonest word absorbed into it here ("rising" into
        H7925 "early"), when this text holds at least half of that
        form's occurrences in the Bible and the form is not the root's
        usual one everywhere (under half of its Bible-wide forms).
        "Rising up early" is Jeremiah's idiom (11 of the Bible's 14),
        though the root H7925 is common and cannot be a formula.
        Returns a note string or None.
        """
        for absorbed in (0, 1):
            # absorbed = a word folded into the root by the gloss or company
            # rule (strongs '=N'); a placed tag that the source put on a
            # pronoun ("before me", H6440 on "me") is a stop token and not
            # a rendering of anything
            sql = ("SELECT LOWER(t.surface), COUNT(*) FROM tokens t JOIN verses v USING (verse_id) "
                   "WHERE t.root = ? AND v.book = ? AND "
                   + ("t.strongs LIKE '=%'" if absorbed else "t.is_stop = 0"))
            params = [root, book]
            if chapter is not None:
                sql += " AND v.chapter = ?"
                params.append(chapter)
            sql += " GROUP BY 1 ORDER BY 2 DESC LIMIT 1"
            here = self.db.execute(sql, params).fetchone()
            if not here:
                continue
            form, n_here = here[0], here[1]
            everywhere = dict(self.db.execute(
                "SELECT LOWER(surface), COUNT(*) FROM tokens WHERE root = ? AND "
                + ("strongs LIKE '=%'" if absorbed else "is_stop = 0") + " GROUP BY 1",
                (root,)).fetchall())
            n_all = everywhere.get(form, n_here)
            total_forms = sum(everywhere.values()) or 1
            if n_here >= LOCAL_RENDERING_SHARE * n_all and n_all / total_forms < 0.5 and n_here >= 3:
                what = "absorbed word" if absorbed else "spelling"
                return f"local rendering: '{form}' ({n_here} of the Bible's {n_all}, {what})"
        return None

    def spellings(self, root, limit=6, book=None, chapter=None):
        """How the text spells a root, commonest first: [(surface, count)],
        across the Bible or within one book or chapter."""
        # Absorbed words ("thus" folded into H559, "burnt" into H5930) are
        # stop tokens carrying the root and are not spellings of it
        if book is None:
            return [(r[0], r[1]) for r in self.db.execute(
                "SELECT surface, COUNT(*) FROM tokens WHERE root = ? AND is_stop = 0 GROUP BY surface "
                "ORDER BY COUNT(*) DESC LIMIT ?", (root, limit))]
        sql = ("SELECT t.surface, COUNT(*) FROM tokens t JOIN verses v USING (verse_id) "
               "WHERE t.root = ? AND t.is_stop = 0 AND v.book = ?")
        params = [root, book]
        if chapter is not None:
            sql += " AND v.chapter = ?"
            params.append(chapter)
        sql += " GROUP BY t.surface ORDER BY COUNT(*) DESC LIMIT ?"
        params.append(limit)
        return [(r[0], r[1]) for r in self.db.execute(sql, params)]

    def roots_behind(self, word, testament=None):
        """
        The roots the text gives an English word, commonest first, as
        [(root, count)].  Under Strong's roots 'lord' comes back as
        H3068, G2962, H136, H113 ... with their counts; under English
        roots it is the one stem.  Every spelling that shares the word's
        English stem is counted (day, days, day's).  With a testament
        ('Old' or 'New') only that testament's tokens are counted, so
        'day' on a Gospel page means G2250 rather than H3117.
        """
        if self._stem_groups is None:
            # One pass over the tokens: (testament, stem) -> root -> count.
            # Kept in memory because root_of() is asked hundreds of
            # times a page.
            groups = defaultdict(Counter)
            for testament_, surface, root, n in self.db.execute(
                    "SELECT b.testament, t.surface, t.root, COUNT(*) FROM tokens t "
                    "JOIN verses v USING (verse_id) JOIN books b USING (book) "
                    "WHERE t.is_stop = 0 GROUP BY b.testament, t.surface, t.root"):
                key = surface if surface.isupper() else self.stemmer.root(surface.lower())
                groups[(testament_, key)][root] += n
                groups[(None, key)][root] += n
            self._stem_groups = groups
        key = word if (word.isupper() and len(word) > 1) else self.stemmer.root(word.lower())
        return self._stem_groups.get((testament, key), Counter()).most_common()

    def divine_name_note(self):
        """One line saying how this text spells the divine name."""
        if self.roots_mode == "strongs":
            counts = {root: self.word_row(root)["weight"] if self.word_row(root) else 0
                      for root in ("H3068", "H136", "G2962")}
            placed = self.settings.get("tags_placed", "")
            return (f"Roots are Strong's numbers ({placed} tags placed), so the divine name "
                    f"H3068 ({counts['H3068']} times), the title H136 Adonai ({counts['H136']}) "
                    f"and the Greek G2962 kurios ({counts['G2962']}) are three roots whatever "
                    f"the English prints.  Untagged words keep their English stem.")
        caps = self.name_forms.get("LORD", 0)
        title = self.name_forms.get("Lord", 0)
        if caps >= 100:
            return (f"This text prints the divine name as LORD ({caps} times) and the title as "
                    f"Lord ({title} times); the atlas keeps them separate.")
        return (f"This text does not print the divine name in capitals (LORD appears {caps} "
                f"times), so LORD and Lord are one word here: 'lord'.")

    # -- lookups -------------------------------------------------------------------

    def root_of(self, word, testament=None):
        """
        The root the build would have given a typed word.  With a
        testament, the commonest number behind the word in that
        testament (for the focus words of a book page).

        LORD and GOD stay as typed when the text really uses them as
        the divine name.  A copy of the KJV that prints "Lord" all the
        way through has only a handful of stray capitals (Revelation
        19:16 "KING OF KINGS, AND LORD OF LORDS"), so a capitalised word
        with fewer than 100 occurrences falls back to the ordinary root.
        """
        # A Strong's number, typed bare ('H3068') or as a page prints it
        # ('lord H3068'), is its own root
        m = STRONGS_IN_TEXT.search(word)
        if m:
            return m.group(1)
        if self.roots_mode == "strongs":
            # The commonest number behind the English word; a word the
            # tagger never marked keeps its English stem
            behind = self.roots_behind(word, testament)
            if behind:
                return behind[0][0]
        if word.isupper() and len(word) > 1:
            row = self.word_row(word)
            if row is not None and row["weight"] >= 100:
                return word
            return self.stemmer.root(word.lower())
        return self.stemmer.root(word.lower())

    def find_testament(self, name):
        """'Old' or 'New' from any of: old, new, ot, nt, Old Testament, New Testament."""
        key = (name or "").strip().lower().replace("testament", "").strip()
        if key in ("old", "ot", "o"):
            return "Old"
        if key in ("new", "nt", "n"):
            return "New"
        raise SystemExit(f"Testament not found: {name} (use Old or New)")

    def find_book(self, name):
        """Match a book name loosely ('joel', 'Song', '1 sam')."""
        name_l = name.lower()
        for book in self.books:
            if book.lower() == name_l:
                return book
        for book in self.books:
            if book.lower().startswith(name_l):
                return book
        raise SystemExit(f"Book not found: {name}")

    def verses_of(self, book, chapter=None):
        """Verse rows (reference, word_string, text) for a book or chapter."""
        if chapter is None:
            return self.db.execute(
                "SELECT * FROM verses WHERE book = ? ORDER BY verse_id", (book,)).fetchall()
        return self.db.execute(
            "SELECT * FROM verses WHERE book = ? AND chapter = ? ORDER BY verse_id",
            (book, chapter)).fetchall()

    def word_row(self, root):
        """Bible-scale row for a root, or None."""
        return self.db.execute("SELECT * FROM words WHERE root = ?", (root,)).fetchone()

    def neighbors(self, scope, root, limit=COMPANY_N):
        """Neighbors of a root at a scope, best pull first."""
        # A single meeting cannot say anything about neighbors, so book-
        # scale pairs (stored down to a count of 1 for the rest-of-Bible
        # arithmetic) are shown only from a count of 2
        return self.db.execute("""
            SELECT companion AS neighbor, count, pull FROM pairs
            WHERE scope = ? AND focus = ? AND count >= 2 ORDER BY pull DESC LIMIT ?""",
            (scope, root, limit)).fetchall()

    def neighbors_rest(self, book, root, limit=COMPANY_N):
        """
        Neighbors of a root in the REST of the Bible (Bible minus one book),
        so a book is never compared with itself.  Counts are Bible
        counts minus the book's own, and pull is recomputed on the
        remainder.  Book-scale pairs are stored down to a count of 1, so
        the subtraction is exact for every stored Bible-scale pair.
        """
        bible = {r["neighbor"]: r["count"] for r in self.db.execute(
            "SELECT companion AS neighbor, count FROM pairs WHERE scope = 'Bible' AND focus = ?", (root,))}
        book_pairs = {r["neighbor"]: r["count"] for r in self.db.execute(
            "SELECT companion AS neighbor, count FROM pairs WHERE scope = ? AND focus = ?", (book, root))}
        win_b = self.db.execute("SELECT window_tokens FROM focus_windows WHERE scope='Bible' AND focus=?",
                                (root,)).fetchone()
        win_k = self.db.execute("SELECT window_tokens FROM focus_windows WHERE scope=? AND focus=?",
                                (book, root)).fetchone()
        inside = (win_b[0] if win_b else 0) - (win_k[0] if win_k else 0)
        n_rest = self.n_bible - self.book_info[book]["words"]
        rows = []
        for neighbor, count_bible in bible.items():
            a = count_bible - book_pairs.get(neighbor, 0)
            if a < 2:
                continue
            w_bible = self.word_row(neighbor)["weight"]
            w_book = self.db.execute("SELECT weight FROM word_book WHERE root=? AND book=?",
                                     (neighbor, book)).fetchone()
            b = w_bible - (w_book[0] if w_book else 0) - a
            rows.append({"neighbor": neighbor, "count": a,
                         "pull": log_likelihood(a, b, inside, n_rest - inside)})
        rows.sort(key=lambda r: -r["pull"])
        return rows[:limit]

    def ref_key(self, reference):
        """
        A sort key that puts references in canonical order: book as the
        canon has it, then chapter, then verse.  Used to break ties, so
        two builds of the same text give the same tables (a Python set
        or dict would otherwise decide, and its order changes from run
        to run).
        """
        book, rest = reference.rsplit(" ", 1)
        ch, _, v = rest.partition(":")
        return (self.books.index(book) if book in self.books else 99, int(ch), int(v or 0))

    def build_line(self):
        """
        One line saying which program and which build made a report:
        the version, the build label and date, the roots rule and the
        window.  Printed under the title of every text report, so a
        file read weeks later says what produced it.
        """
        label = self.settings.get("label") or "unlabelled"
        roots = "Strong's numbers" if self.roots_mode == "strongs" else "English stems"
        gloss = self.settings.get("tags_absorbed_by_gloss")
        rules = (f"gloss rule on ({gloss} absorbed)" if gloss else
                 "built before the gloss rule of 0.9.7: rebuild with build_atlas.py")
        return (f"Word Atlas {VERSION}; build '{label}' made {self.settings.get('built', '?')}, "
                f"roots {roots}, {rules}, window {self.window}, {self.settings.get('translation', '')}.")

    def english_stems(self):
        """
        A Bible-wide index of English stems, built once and kept: stem ->
        list of the verse_ids holding it (a verse repeated once per
        occurrence, so the length is the stem's count), and a cache of
        surface -> stem.  On a Strong's build a Hebrew root never
        matches a Greek one, so kin across the testaments has to be
        found by the English words instead; this is what it is found by.
        """
        if getattr(self, "_english_stems", None) is None:
            stems, surfaces = {}, {}
            for verse_id, surface in self.db.execute("SELECT verse_id, surface FROM tokens WHERE is_stop = 0"):
                key = surface.lower()
                stem = surfaces.get(key)
                if stem is None:
                    stem = surfaces[key] = self.stemmer.root(key)
                stems.setdefault(stem, []).append(verse_id)
            self._english_stems = (stems, surfaces)
        return self._english_stems

    def english_rarity(self, stem):
        """Rarity of an English stem across the whole Bible, as rarity() scores it."""
        stems, _ = self.english_stems()
        n = len(stems.get(stem, ()))
        return -math.log(n / self.n_bible) if n else 0.0

    def rarity(self, root):
        """
        How rare a root is across the Bible, as -log(share of all words).
        A word that is 1 in 1,000 scores about 6.9; 1 in 100,000 about 11.5.
        """
        row = self.word_row(root)
        if row is None:
            return 0.0
        return -math.log(row["weight"] / self.comparison_words(root))

    def occurrences(self, scope, root):
        """How often a root occurs at a scope."""
        row = self.db.execute(
            "SELECT occurrences FROM focus_windows WHERE scope = ? AND focus = ?",
            (scope, root)).fetchone()
        return row[0] if row else 0

    def count_phrase_outside(self, phrase, book):
        """Verses outside a book that contain a phrase (used for grown formulas)."""
        return self.db.execute(
            f"SELECT COUNT(*) FROM verses WHERE book != ? AND {self.phrase_column} LIKE ?",
            (book, f"% {phrase} %")).fetchone()[0]

    def display_of(self, key, references):
        """
        The commonest English wording of a unit key (a formula as the
        tables store it) among the verses given, read off the verses
        themselves: the words at the positions where the key occurs.
        Under English formulas the key is its own wording.
        """
        if self.phrase_column == "word_string":
            return key
        if key.startswith("en:"):
            return key[3:]
        parts = key.split()
        n = len(parts)
        wordings = Counter()
        marks = ",".join("?" * len(references))
        for ws, ps in self.db.execute(
                f"SELECT word_string, phrase_string FROM verses WHERE reference IN ({marks})", references):
            words, units = ws.split(), ps.split()
            for i in range(len(units) - n + 1):
                if units[i:i + n] == parts:
                    wordings[" ".join(words[i:i + n])] += 1
        if wordings:
            return wordings.most_common(1)[0][0]
        row = self.db.execute("SELECT display FROM ngrams WHERE phrase = ?", (key,)).fetchone() \
            if self.has_display else None
        return row[0] if row else key

    def content_units(self, key):
        """The content units of a formula key (stop words left out).  An
        English-keyed echo ("en:full of eyes", found across the
        testaments by wording) gives the roots of its words."""
        if key.startswith("en:"):
            return tuple(self.root_of(w) for w in key[3:].split() if w not in STOPLIST)
        return tuple(u for u in key.split() if u not in STOPLIST)

    # -- growing formulas (same idea as phase 1, now against stored strings) --------

    def grow_formula(self, phrase, word_strings):
        """
        Extend a formula left and right for as long as every verse in
        word_strings continues it with the same word, then tidy it.
        """
        while True:
            grew = False
            for side in ("right", "left"):
                choices = []
                needle = f" {phrase} "
                for text in word_strings:
                    words = set()
                    start = 0
                    while True:
                        i = text.find(needle, start)
                        if i < 0:
                            break
                        if side == "right":
                            after = text[i + len(needle):].split(" ", 1)[0]
                            if after:
                                words.add(after)
                        else:
                            before = text[:i + 1].rstrip().rsplit(" ", 1)[-1]
                            if before:
                                words.add(before)
                        start = i + 1
                    choices.append(words)
                common = set.intersection(*choices) if choices else set()
                if len(common) == 1:
                    word = common.pop()
                    phrase = f"{phrase} {word}" if side == "right" else f"{word} {phrase}"
                    grew = True
            if not grew:
                return trim_formula(phrase)

    # -- lookups for the window ------------------------------------------------------

    def verse_by_reference(self, reference):
        """The verse row for a reference such as 'Joel 2:1', or None."""
        return self.db.execute("SELECT * FROM verses WHERE reference = ?", (reference,)).fetchone()

    def verses_with(self, root, book=None, chapter=None, limit=200):
        """
        References of verses containing a root, in canonical order,
        optionally limited to one book or one chapter.
        """
        sql = "SELECT DISTINCT v.verse_id, v.reference FROM tokens t JOIN verses v USING (verse_id) WHERE t.root = ?"
        params = [root]
        if book:
            sql += " AND v.book = ?"
            params.append(book)
        if chapter:
            sql += " AND v.chapter = ?"
            params.append(chapter)
        sql += " ORDER BY v.verse_id LIMIT ?"
        params.append(limit)
        return [r[1] for r in self.db.execute(sql, params)]

    def verses_with_phrase(self, phrase, book=None, limit=200, key=False):
        """References of verses containing a formula, optionally within one
        book.  With key=True the phrase is a unit key (Strong's numbers)
        and is looked for in phrase_string; otherwise it is English
        wording looked for in word_string."""
        if key and phrase.startswith("en:"):
            phrase, key = phrase[3:], False
        column = self.phrase_column if key else "word_string"
        sql = f"SELECT reference FROM verses WHERE {column} LIKE ?"
        params = [f"% {phrase} %"]
        if book:
            sql += " AND book = ?"
            params.append(book)
        sql += " ORDER BY verse_id LIMIT ?"
        params.append(limit)
        return [r[0] for r in self.db.execute(sql, params)]


# ---------------------------------------------------------------------------
# Building blocks shared by the pages
# ---------------------------------------------------------------------------

def occurrence_floor(n_words):
    """
    How many occurrences a root needs before a keyness table measures
    it, scaled to the text's size: one per WORDS_PER_OCCURRENCE words,
    never under SHORT_BOOK_MIN_WEIGHT and never over HOME_MIN_WEIGHT.
    Used by 1b for a book and by section 7 for a section, so a part of
    900 words (Galatians' ethics) is treated as a small book is.
    """
    return min(HOME_MIN_WEIGHT, max(SHORT_BOOK_MIN_WEIGHT, round(n_words / WORDS_PER_OCCURRENCE)))


def per_thousand(count, total):
    """Occurrences per 1,000 words."""
    return round(1000 * count / total, 2) if total else 0.0


def phrases_in(verses, phrase_column="word_string"):
    """
    Formula counts for a set of verse rows: key -> (verses, times).  The
    key is the unit key (phrase_string) when the build has one, else the
    English wording; function words are judged on the English either way.
    """
    counts = {}
    for v in verses:
        words = v["word_string"].split()
        units = v[phrase_column].split() if phrase_column != "word_string" else words
        stops = [w in STOPLIST for w in words]
        seen = set()
        for n in FORMULA_LENGTHS:
            for i in range(len(words) - n + 1):
                if stops[i + n - 1]:
                    continue
                phrase = " ".join(units[i:i + n])
                a, t = counts.get(phrase, (0, 0))
                counts[phrase] = (a + (0 if phrase in seen else 1), t + 1)
                seen.add(phrase)
    return counts


def lcs_length(a, b):
    """Longest common subsequence of two short lists."""
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        ai = a[i - 1]
        row, prev = table[i], table[i - 1]
        for j in range(1, len(b) + 1):
            row[j] = prev[j - 1] + 1 if ai == b[j - 1] else max(prev[j], row[j - 1])
    return table[len(a)][len(b)]


def common_roots(atlas, book):
    """
    The roots that occur in more than PARALLEL_COMMON_SHARE of a book's
    verses: its formulaic vocabulary, set aside when looking for
    parallels.  Cached on the atlas.
    """
    cache = atlas.__dict__.setdefault("_common_roots", {})
    if book not in cache:
        n_verses = atlas.book_info[book]["verses"]
        rows = atlas.db.execute(
            "SELECT root, verses_reached FROM word_book WHERE book = ? AND verses_reached > ?",
            (book, PARALLEL_COMMON_SHARE * n_verses)).fetchall()
        cache[book] = {r[0] for r in rows}
    return cache[book]


def parallels(atlas, book, partner, share=None):
    """
    Verse-to-verse parallels between two books, by the rule in
    atlas_text (PARALLEL_METHOD).

    "overlap": two verses are parallel when the content roots they share
    in the same order (longest common subsequence, anything between)
    number at least PARALLEL_MIN_SHARED and make up at least
    PARALLEL_SHARE of the shorter verse's content roots.  Scores the
    pair by the number of shared roots, so the closest parallel comes
    first.
    "runs": a run of PARALLEL_RUN adjacent words with at least
    PARALLEL_RUN_CONTENT content words.  Scores by runs shared.

    Returns:
        dict: book verse reference -> Counter(partner reference -> score)
    """
    if PARALLEL_METHOD == "runs":
        return parallels_by_runs(atlas, book, partner)
    share = PARALLEL_SHARE if share is None else share
    # Cached on the atlas: every chapter page of a book asks for the
    # same two partner tables, and a dossier asks for them 48 times
    cache = atlas.__dict__.setdefault("_parallels", {})
    key = (book, partner, share)
    if key in cache:
        return cache[key]
    cache[key] = result = _parallels_overlap(atlas, book, partner, share)
    return result


def _parallels_overlap(atlas, book, partner, share):
    """The overlap rule itself; see parallels()."""

    # The book's own formulaic words (in more than PARALLEL_COMMON_SHARE
    # of its verses: Ezekiel's lord, god, saith, know) are set aside on
    # both sides, or "thus saith the Lord GOD" would pair every oracle
    # with some verse of Jeremiah
    skip = common_roots(atlas, book)
    # Across the testaments a Hebrew root never matches a Greek one, so
    # the English stems of the words stand in for the roots (as the
    # cross-testament echoes and kin do); the book's formulaic words
    # are then the stems in more than PARALLEL_COMMON_SHARE of its verses
    cross = (atlas.roots_mode == "strongs"
             and atlas.book_info[book]["testament"] != atlas.book_info[partner]["testament"])
    # Within a testament, a book in two languages (Daniel, Ezra) needs the
    # stems too: a verse pair in different languages (Daniel 7 against
    # Ezekiel 1) is judged on stems, a pair in one language on roots
    mixed = (atlas.roots_mode == "strongs" and not cross
             and len(atlas.languages_of(book) | atlas.languages_of(partner)) > 1)
    if cross or mixed:
        _, surfaces = atlas.english_stems()

    def content_roots(name, stems):
        out = {}
        column = "surface" if stems else "root"
        skip_here = skip_stems if stems else skip
        for ref, unit in atlas.db.execute(
                f"SELECT v.reference, t.{column} FROM tokens t JOIN verses v USING (verse_id) "
                "WHERE v.book = ? AND t.is_stop = 0 ORDER BY t.verse_id, t.position", (name,)):
            if stems:
                unit = surfaces.get(unit.lower()) or atlas.stemmer.root(unit.lower())
            if unit not in skip_here:
                out.setdefault(ref, []).append(unit)
        return out

    skip_stems = set()
    if cross or mixed:
        # The formulaic stems of the book, counted by verses reached
        reached = {}
        for ref, unit in atlas.db.execute(
                "SELECT v.reference, t.surface FROM tokens t JOIN verses v USING (verse_id) "
                "WHERE v.book = ? AND t.is_stop = 0", (book,)):
            stem = surfaces.get(unit.lower()) or atlas.stemmer.root(unit.lower())
            reached.setdefault(stem, set()).add(ref)
        limit = PARALLEL_COMMON_SHARE * atlas.book_info[book]["verses"]
        skip_stems = {stem for stem, refs in reached.items() if len(refs) > limit}

    # modes: 0 roots, 1 stems.  Across the testaments only stems; within
    # one, roots, plus stems for the verse pairs whose languages differ
    modes = [1] if cross else ([0, 1] if mixed else [0])
    units = {m: (content_roots(book, m == 1), content_roots(partner, m == 1)) for m in modes}
    index = {m: {} for m in modes}
    for m in modes:
        for ref, roots in units[m][1].items():
            for r in set(roots):
                index[m].setdefault(r, set()).add(ref)
    matches = {}
    refs_all = sorted({ref for m in modes for ref in units[m][0]}, key=atlas.ref_key)
    for ref in refs_all:
        best = Counter()
        for m in modes:
            roots = units[m][0].get(ref, [])
            theirs = units[m][1]
            # Candidates: partner verses sharing enough distinct units at all
            shared_count = Counter()
            for r in set(roots):
                for pref in index[m].get(r, ()):
                    shared_count[pref] += 1
            for pref, n in shared_count.items():
                if n < PARALLEL_MIN_SHARED or pref in best:
                    continue
                if mixed:
                    # stems only where the two verses' languages differ,
                    # roots only where they agree
                    differ = atlas.language_of(ref, book) != atlas.language_of(pref, partner)
                    if differ != (m == 1):
                        continue
                other = theirs[pref]
                in_order = lcs_length(roots, other)
                if in_order >= PARALLEL_MIN_SHARED and in_order / min(len(roots), len(other)) >= share:
                    best[pref] = in_order
        if best:
            # Rebuilt in canonical order among equal scores, so a later
            # "closest first, at most four" cut is the same on every run
            ordered = Counter()
            for pref, score in sorted(best.items(), key=lambda kv: (-kv[1], atlas.ref_key(kv[0]))):
                ordered[pref] = score
            matches[ref] = ordered
    return matches


def parallels_by_runs(atlas, book, partner):
    """The runs rule: see parallels()."""
    n, min_content = PARALLEL_RUN, PARALLEL_RUN_CONTENT

    def runs_of(verses):
        index = {}
        for v in verses:
            words = v["word_string"].split()
            for i in range(len(words) - n + 1):
                run = words[i:i + n]
                if sum(1 for w in run if w not in STOPLIST) < min_content:
                    continue
                index.setdefault(" ".join(run), set()).add(v["reference"])
        return index

    partner_index = runs_of(atlas.verses_of(partner))
    matches = {}
    for v in atlas.verses_of(book):
        words = v["word_string"].split()
        for i in range(len(words) - n + 1):
            hits = partner_index.get(" ".join(words[i:i + n]))
            if hits:
                counts = matches.setdefault(v["reference"], Counter())
                for h in hits:
                    counts[h] += 1
    return matches


def chief_partners(atlas, book, count=2, chapters=None):
    """
    The books this book (or these chapters of it) shares the most
    distinct echoes with, from the echoes table.  With chapters, a
    section's own chief partners: 2 Kings 18 to 20 give Isaiah, 21 to 25
    Jeremiah, where the book as a whole gives 2 Chronicles and Isaiah.
    """
    if chapters:
        rows = atlas.db.execute(
            "SELECT e2.book, COUNT(DISTINCT e1.phrase) AS n FROM echoes e1 "
            "JOIN verses v ON v.verse_id = e1.verse_id JOIN echoes e2 ON e2.phrase = e1.phrase "
            "WHERE e1.book = ? AND e2.book != ? AND v.chapter IN (" + ",".join("?" * len(chapters)) + ") "
            "GROUP BY e2.book ORDER BY n DESC LIMIT ?",
            (book, book, *chapters, count)).fetchall()
    else:
        rows = atlas.db.execute(
            "SELECT e2.book, COUNT(DISTINCT e1.phrase) AS n FROM echoes e1 JOIN echoes e2 USING (phrase) "
            "WHERE e1.book = ? AND e2.book != ? GROUP BY e2.book ORDER BY n DESC LIMIT ?",
            (book, book, count)).fetchall()
    return [r[0] for r in rows]


def signature_words_section(atlas, report, title, rows, n_scope, scope_label,
                            book, chapter=None, chapters_total=None):
    """
    Add a signature words table from rows of
    (root, weight, chapters_reached or None, keyness).

    Spread (keyness scaled by the share of chapters the word reaches)
    and the "local" mark are given when chapters_total is known, that
    is on a book page.  Returns the roots in table order.
    """
    has_spread = chapters_total is not None
    has_depth = has_spread and atlas.has_depth and chapter is None
    columns = ["word", "count", f"{scope_label}/1000", "rest/1000", "chapters", "books", "keyness", "note"]
    if has_spread:
        columns.insert(7, "spread")
    if has_depth:
        columns[8:8] = ["depth", "deepest"]
    depths = {}
    if has_depth:
        depths = {r[0]: (r[1], r[2]) for r in atlas.db.execute(
            "SELECT root, depth, depth_chapter FROM word_book WHERE book = ?", (book,))}
    note = ("depth is the highest keyness the word reaches in any one chapter, and 'deepest' that "
            "chapter: reach is horizontal, depth vertical.  "
            if has_depth else "") + (
            "rest/1000, books and keyness compare the word with the rest of its own testament "
            "when it is a Strong's number (H with the Old Testament, G with the New), and with "
            "the rest of the Bible when it is an English stem; a Greek word cannot occur in the "
            "Old Testament, so the Bible as a whole would make every Greek word look key.  "
            "'N renderings' means the text gives the root that many different English words; "
            "'local rendering' that a form of the root belongs to this text: its commonest spelling "
            "here, or the word absorbed into it here ('rising' into H7925 'early', Jeremiah's "
            "'rising up early', 11 of the Bible's 14), when this text holds at least half of that "
            "form's uses and the form is not the root's usual one elsewhere.  The idiom is this "
            "text's own even where the root is not.")
    if atlas.roots_mode != "strongs":
        note = ""
    # A small book (under BOOK_SMALL_WORDS words) says so in the title
    # and the note: the lower rows rest on a handful of occurrences
    if chapter is None and chapters_total is not None and n_scope < BOOK_SMALL_WORDS:
        title = title + " (small book)"
        note += (f"  {scope_label} holds {n_scope} words, under {BOOK_SMALL_WORDS}: most rows rest on "
                 f"five to seven occurrences, and the lower rows are suggestions rather than findings.")
    sec = report.section(title, columns, note=note)
    top, spread_rows = [], []
    for root, weight, chapters, keyness in rows[:TOP_N]:
        w = atlas.word_row(root)
        row = [atlas.form(root), weight, per_thousand(weight, n_scope),
               per_thousand(w["weight"], atlas.comparison_words(root)),
               f"{chapters}/{chapters_total}" if chapters is not None else "-",
               f"{w['books_reached']}/{atlas.comparison_books(root)}", round(keyness, 1)]
        notes = []
        if has_spread:
            # Spread-weighted keyness: a word used many times in a small
            # space casts a smaller shadow than one spread over the book
            share = chapters / chapters_total
            spread = keyness * share
            row.append(round(spread, 1))
            if share < LOCAL_SHARE:
                notes.append("local")
            spread_rows.append((root, spread, share))
        if has_depth:
            d = depths.get(root, (0, None))
            row += [round(d[0] or 0, 1), f"ch {d[1]}" if d[1] else "-"]
        renderings = atlas.renderings(root)
        if renderings > 1:
            notes.append(f"{renderings} renderings")
        # A local rendering: the root's commonest spelling here is not
        # its commonest across the Bible.  "Rising up early" (H7925) is
        # Jeremiah's idiom, but the root is one word and cannot be a
        # formula, and Genesis's "rose up early" dilutes it as a word;
        # the spelling is what marks it as this book's own
        if is_strongs(root) and book:
            local = atlas.local_rendering(root, book, chapter)
            if local:
                notes.append(local)
        row.append(", ".join(notes))
        sec.add(row, refs=None, link={"word": root, "book": book, "chapter": chapter})
        top.append(root)
    # Verse references are looked up lazily by the display (they can be
    # hundreds); the link carries what is needed to find them.
    total = sum(r[3] for r in rows[:TOP_N]) or 1
    concentration = sum(r[3] for r in rows[:3]) / total
    sec.footer.append(f"Concentration: the top three signature words carry {concentration:.0%} "
                      f"of the keyness in the top {TOP_N}.")
    # The same with proper names set aside: a book named after its hero
    # (Job, Joshua, Esther) will always have him first, which says
    # nothing about how concentrated its ordinary vocabulary is
    names = [r for r in rows[:TOP_N] if atlas.is_name(r[0])]
    if names:
        plain = [r for r in rows[:TOP_N] if r not in names]
        if plain:
            total_plain = sum(r[3] for r in plain) or 1
            conc_plain = sum(r[3] for r in plain[:3]) / total_plain
            sec.footer.append(
                f"Names in the top {TOP_N}: " + ", ".join(atlas.form(r[0]) for r in names)
                + f".  Without them the top three ({', '.join(atlas.form(r[0]) for r in plain[:3])}) "
                f"carry {conc_plain:.0%}.")
    if has_spread:
        local = [atlas.form(r) for r, sp, share in spread_rows if share < LOCAL_SHARE]
        if local:
            sec.footer.append(f"Local words (under {LOCAL_SHARE:.0%} of chapters), a book within "
                              f"the book: " + ", ".join(local) + ".")
        spread_rows.sort(key=lambda r: -r[1])
        sec.footer.append("By spread-weighted keyness: "
                          + ", ".join(atlas.form(r) for r, sp, share in spread_rows[:10]) + ".")
        # The forms this book owns, over every root and not only the top
        # 25: the idioms a formula cannot form because they are one root
        if book and chapter is None and atlas.roots_mode == "strongs":
            owned = atlas.local_renderings(book)
            if owned:
                def owned_entry(root, form, n_here, n_all, kind):
                    # An absorbed word that makes a hyphenated rendering with
                    # the root's own spelling is printed joined: 'son-in-law'
                    # for H2859 in 1 Samuel 18, where the Bible has father-in-law
                    if kind == "absorbed word":
                        spelling = atlas.form(root).rsplit(" ", 1)[0].split(" (")[0].split("-")[-1]
                        joined = JOINED_RENDERINGS.get((spelling, form))
                        if joined:
                            return (f"'{joined}' for {root} ({n_here} of the Bible's {n_all}; "
                                    f"{atlas.form(root).rsplit(' ', 1)[0]} elsewhere)")
                    return (f"'{form}' for {atlas.form(root)} ({n_here} of the Bible's {n_all}"
                            + (", absorbed word" if kind == "absorbed word" else "") + ")")
                sec.footer.append("Local renderings (forms this book owns, over every root): " + "; ".join(
                    owned_entry(*entry) for entry in owned) + ".")
    lexicon_section(atlas, report, title, top, book, chapter, scope_label)
    return top


# Strong's dictionary marks its glosses with "[idiom]", "[phrase]" and
# the like; the pages leave the marks out
GLOSS_MARKS = re.compile(r"\[[a-z ]+\]\s*")


def clean_gloss(text, limit=90):
    """A dictionary gloss without its bracketed marks, cut to a length."""
    text = GLOSS_MARKS.sub("", (text or "").strip())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def group_words_section(atlas, report, title, book, testament_top):
    """
    Section 1b: the book's signature words measured against the other
    books of its own kind, the baseline group that metadata.db gives it
    (Joel against the prophets, Hebrews against the epistles), beside
    the testament figure of section 1.  Against the whole testament a
    prophet's list is full of words that are merely common in prophecy;
    against its peers, Isaiah's leading words become redeemed, created,
    remnant.  The group is read from the books table (baseline_group)
    and can be changed there; the book is always left out of its own
    baseline.  Roots only, at least HOME_MIN_WEIGHT occurrences, so a
    word used twice cannot claim a large keyness on thin evidence.
    Returns the roots shown, for the lexicon table.
    """
    groups = atlas.baseline_groups()
    group = groups.get(book)
    if not group:
        return []
    peers = [b for b in atlas.books if groups.get(b) == group and b != book]
    # A Greek root cannot occur in a Hebrew book, so a baseline from the
    # other testament would make every word key: Revelation against the
    # Prophecy group, which is seventeen Old Testament books, came out as
    # its own frequency list with the group rate 0.0 on every row.  Keep
    # only peers from the book's own testament, as section 1 does, and
    # when none remain say so in a note instead of printing a table
    testament = atlas.book_info[book]["testament"]
    peers = [b for b in peers if atlas.book_info[b]["testament"] == testament]
    if not peers:
        # The header stays, with the reason in place of the table: a
        # reader who finds no 1b would take it that the catalogue gave
        # the book no kind, which is the opposite of the truth
        others = [b for b in atlas.books if groups.get(b) == group and b != book]
        report.section(
            title, ["word"],
            note=f"Not measured.  The catalogue (metadata.db) gives {book} the baseline group '{group}', "
                 f"which is right as a kind; but its other books ({', '.join(others)}) are all in the "
                 f"other testament, and a root of one testament never occurs in the other, so a keyness "
                 f"against them is not a measurement: every word would be key.  The comparison of "
                 f"{book} with the {'Hebrew prophets' if testament == 'New' else 'Greek books'} by "
                 f"vocabulary is the Septuagint bridge's work (atlas_lift.py with --text lxx, and the "
                 f"root equivalents of the catalogue).  Section 1 measures {book} against the rest of "
                 f"its testament.")
        return []
    n_here = atlas.book_info[book]["words"]
    n_peers = sum(atlas.book_info[b]["words"] for b in peers)
    marks = ",".join("?" * len(peers))
    peer_counts = dict(atlas.db.execute(
        f"SELECT root, SUM(weight) FROM word_book WHERE book IN ({marks}) GROUP BY root", peers))
    # The same guard a root at a time, inside the testament: an Aramaic
    # root has no peer in a Hebrew kind (Ezra against History put
    # eighteen Aramaic rows at a group rate of 0.0; Daniel against the
    # prophets would do the same), so Aramaic roots are measured only
    # when the kind holds at least FEW_WORDS words of Aramaic, and are
    # otherwise left out and counted in a footer.  The Aramaic chapters
    # have their own place in the Language sections
    aramaic = atlas.aramaic_roots()
    peer_aramaic_words = atlas.db.execute(
        f"SELECT COALESCE(SUM(LENGTH(word_string) - LENGTH(REPLACE(word_string, ' ', '')) - 1), 0) "
        f"FROM verses WHERE language = 'Aramaic' AND book IN ({marks})", peers).fetchone()[0] \
        if aramaic else 0
    aramaic_measured = peer_aramaic_words >= FEW_WORDS
    # A book in two languages (Daniel) is measured a language at a time,
    # each with its own denominators: its Aramaic roots against the
    # kind's Aramaic words, its Hebrew roots against the kind's Hebrew.
    # With one denominator for both, an Aramaic root the kind seldom
    # uses scores nearly its count against 23,000 words while a Hebrew
    # root of chapter 9 faces 22,000 words of real competition, and the
    # smaller language wins every row
    bilingual = len(atlas.languages_of(book)) > 1 and aramaic_measured
    if bilingual:
        here_aramaic = atlas.db.execute(
            "SELECT COALESCE(SUM(LENGTH(word_string) - LENGTH(REPLACE(word_string, ' ', '')) - 1), 0) "
            "FROM verses WHERE language = 'Aramaic' AND book = ?", (book,)).fetchone()[0]
        denominators = {"Aramaic": (here_aramaic, peer_aramaic_words),
                        "Hebrew": (n_here - here_aramaic, n_peers - peer_aramaic_words)}
    # HOME_MIN_WEIGHT was set for home words in a testament; on a book of
    # 1,300 words it shuts out nearly everything that matters (Nahum's
    # Nineveh, cankerworm, prey and lion all have three or four uses;
    # five in Hosea's 5,000 words is a word per thousand, five in
    # Jeremiah's 42,000 one in eight thousand).  So the floor scales
    # with the book, one occurrence per WORDS_PER_OCCURRENCE words,
    # never under SHORT_BOOK_MIN_WEIGHT and never over HOME_MIN_WEIGHT:
    # 3 up to Hosea, 4 for Ecclesiastes to Zechariah, 5 from Hebrews on.
    # The keyness floor below keeps the two rules honest with each
    # other: more words are let in, and only the ones that clear it stay
    min_weight = occurrence_floor(n_here)
    left_out = 0
    scored = []
    measured = {}                    # every root the table measured, with its group keyness
    for root, weight, testament_keyness in atlas.db.execute(
            "SELECT root, weight, keyness FROM word_book WHERE book = ? AND weight >= ?",
            (book, min_weight)):
        if not is_strongs(root):
            continue
        if root in aramaic and not aramaic_measured:
            left_out += 1
            continue
        b = peer_counts.get(root, 0)
        n1, n2 = n_here, n_peers
        if bilingual:
            n1, n2 = denominators["Aramaic" if root in aramaic else "Hebrew"]
        keyness = log_likelihood(weight, b, n1, n2) if n1 and n2 else 0
        measured[root] = keyness
        # A floor rather than a count: section 1 fills to TOP_N because
        # its baseline is a whole testament and the 25th row is still
        # well above it, but a short book against its kind runs out of
        # evidence first (Habakkuk's last rows were earth 0.5, people
        # 0.2, come 0.0, a word used at exactly the kind's rate), so a
        # row is shown only above GROUP_KEYNESS_FLOOR, the 1 percent line
        if keyness >= GROUP_KEYNESS_FLOOR:
            scored.append((keyness, root, weight, b, testament_keyness, n1, n2))
    scored.sort(key=lambda s: (-s[0], s[1]))
    # A kind under GROUP_SMALL_WORDS words is marked in the title, as a
    # small section is: the keyness is sound, the bottom rows are not
    # to be quoted as firmly as Isaiah's
    small = n_peers < GROUP_SMALL_WORDS
    if small:
        title = title + " (small kind)"
    # ... and a small book the other way round: Lamentations' 3,400 words
    # put most of its rows on five to seven occurrences, and the last ten
    # are suggestions rather than findings
    small_book = n_here < BOOK_SMALL_WORDS
    if small_book:
        title = title + " (small book)"
    sec = report.section(
        title, ["word", "count", f"{book}/1000", f"{group}/1000", "keyness (group)", "keyness (testament)", "note"],
        note=f"Section 1 measures each word against the rest of its testament; this table measures it "
             f"against the other books of its own kind, the baseline group '{group}' that metadata.db "
             f"gives {book} ({len(peers)} books, {n_peers} words; the book is left out of its own "
             f"baseline).  A word merely common in the kind falls, and what remains is what sets this "
             f"book apart from its peers.  'new' marks a word not among section 1's top {TOP_N}.  The "
             f"group is the baseline_group column of the books table in metadata.db, and can be "
             f"changed there.  Roots only, at least {min_weight} occurrences"
             + (f" (the usual {HOME_MIN_WEIGHT} scaled to the book's size, one per {WORDS_PER_OCCURRENCE} "
                f"words of its {n_here}, never under {SHORT_BOOK_MIN_WEIGHT}; {min_weight} occurrences is "
                f"the floor these rows stand on)"
                if min_weight != HOME_MIN_WEIGHT else "")
             + f".  A row is shown only while its group keyness is at least {GROUP_KEYNESS_FLOOR}, the "
             f"1 percent line of the measure, and the table stops there rather than filling to {TOP_N}: "
             f"a keyness near 0 is a word used at exactly the kind's rate.  Click a row for "
             f"the verses; double-click for the word's page."
             + (f"  The kind holds {n_peers} words, under {GROUP_SMALL_WORDS}: read the lower rows lightly."
                if small else "")
             + (f"  {book} holds {n_here} words, under {BOOK_SMALL_WORDS}: most rows rest on a handful of "
                f"occurrences, and the lower rows are suggestions rather than findings."
                if small_book else "")
             + (f"  {book} is in two languages, so each word is measured in its own: an Aramaic root "
                f"against the kind's Aramaic ({denominators['Aramaic'][0]} words here, "
                f"{denominators['Aramaic'][1]} in the kind), a Hebrew root against its Hebrew "
                f"({denominators['Hebrew'][0]} here, {denominators['Hebrew'][1]} in the kind); the rates "
                f"are per 1,000 words of that language, and the note says which."
                if bilingual else ""))
    shown = []
    for keyness, root, weight, b, tk, n1, n2 in scored[:TOP_N]:
        notes = []
        if root not in testament_top:
            notes.append("new")
        if bilingual:
            notes.append("Aramaic" if root in aramaic else "Hebrew")
        sec.add([atlas.form(root), weight, per_thousand(weight, n1), per_thousand(b, n2),
                 round(keyness, 1), round(tk, 1) if tk is not None else "", ", ".join(notes)],
                refs=atlas.verses_with(root, book), link={"word": root, "book": book})
        shown.append(root)
    sec.footer.append(f"The group: " + ", ".join(peers) + ".")
    if bilingual:
        # Which peers hold the Aramaic the Aramaic rows are measured
        # against, and how much: "common to the kind" for Daniel's
        # Aramaic means common to Ezra 4 to 7, and a root Ezra uses
        # three times is already two per thousand of that baseline
        holders = [(b, n) for b, n in atlas.db.execute(
            f"SELECT book, SUM(LENGTH(word_string) - LENGTH(REPLACE(word_string, ' ', '')) - 1) FROM verses "
            f"WHERE language = 'Aramaic' AND book IN ({marks}) GROUP BY book", peers) if n]
        sec.footer.append(
            f"The Aramaic baseline: {peer_aramaic_words} words, held by "
            + ", ".join(f"{b} ({n})" for b, n in holders)
            + f", beside the kind's {n_peers} words in all; 'common to the kind' for an Aramaic root means "
            f"common to that baseline, where a root used three times is already two per thousand.")
    if len(scored) < TOP_N:
        # Say plainly that the table is short because the evidence is,
        # not because the book has few words worth measuring
        under = sum(1 for k in measured.values() if k < GROUP_KEYNESS_FLOOR)
        sec.footer.append(
            f"{len(scored)} row{'s' if len(scored) != 1 else ''}: of the {len(measured)} roots measured, "
            f"{under} sit under the keyness floor of {GROUP_KEYNESS_FLOOR} and are not shown.")
    if left_out:
        sec.footer.append(
            f"{left_out} Aramaic root{'s' if left_out != 1 else ''} of {book} left out: the kind holds "
            f"{peer_aramaic_words} words of Aramaic, under {FEW_WORDS}, so an Aramaic root has no peer "
            f"there and its keyness would be only its count.  The Aramaic chapters are measured in "
            f"the Languages line and the Language division (section 7).")
    # Section 1 words missing here fell for one of two reasons: the kind
    # shares them (group keyness under the floor), or the list is only
    # TOP_N long and new entrants pushed them off (group keyness still
    # above it).  Only the first is a finding about the book, so the two
    # are named apart, and the line between them is the same floor the
    # rows were chosen by.  A section 1 word the table never measured
    # (under min_weight occurrences, an English stem, or an Aramaic root
    # with no peer) is neither common nor displaced, and is named apart:
    # the Song's apples and spikenard are nobody's common property
    shown_set = set(shown)
    fallen = [r for r in testament_top if r not in shown_set]
    common = [atlas.form(r) for r in fallen if r in measured and measured[r] < GROUP_KEYNESS_FLOOR]
    displaced = [atlas.form(r) for r in fallen if r in measured and measured[r] >= GROUP_KEYNESS_FLOOR]
    unmeasured = [atlas.form(r) for r in fallen if r not in measured]
    if unmeasured:
        sec.footer.append(f"Of section 1's words, not measured here (under {min_weight} occurrences, "
                          f"an English stem, or an Aramaic root with no peer): "
                          + ", ".join(unmeasured[:12]) + ("..." if len(unmeasured) > 12 else "") + ".")
    if common:
        sec.footer.append(f"Of section 1's words, common to the kind (group keyness under "
                          f"{GROUP_KEYNESS_FLOOR}): " + ", ".join(common[:12])
                          + ("..." if len(common) > 12 else "") + ".")
    if displaced:
        sec.footer.append(f"Of section 1's words, still key against the kind but displaced from the top "
                          f"{TOP_N}: " + ", ".join(displaced[:12]) + ("..." if len(displaced) > 12 else "") + ".")
    return shown


RICHNESS_MIN_RUNS = 5           # 1d's footer names the supplying books when fewer than this many could supply a run
RICHNESS_CACHE = "richness_cache.json"   # 1d's run figures, kept beside the program, keyed by the build stamp


def richness_cache_load(atlas):
    """
    The on-disk cache of 1d's run figures: {key: [roots, hapaxes, own,
    runs]} under the build stamp, so a rebuild invalidates it and the
    window never pays for a table twice.  Held on the atlas once read.
    """
    cache = getattr(atlas, "_richness_cache", None)
    if cache is None:
        stamp = f"{atlas.settings.get('roots', '')}|{atlas.settings.get('built', '')}|{VERSION}"
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), RICHNESS_CACHE)
        cache = {"stamp": stamp, "path": path, "runs": {}, "dirty": False}
        try:
            import json
            with open(path, encoding="utf-8") as f:
                stored = json.load(f)
            if stored.get("stamp") == stamp:
                cache["runs"] = stored.get("runs", {})
        except (OSError, ValueError):
            pass
        atlas._richness_cache = cache
    return cache


def richness_cache_save(atlas):
    cache = getattr(atlas, "_richness_cache", None)
    if not cache or not cache["dirty"]:
        return
    try:
        import json
        with open(cache["path"], "w", encoding="utf-8") as f:
            json.dump({"stamp": cache["stamp"], "runs": cache["runs"]}, f)
        cache["dirty"] = False
    except OSError:
        pass            # a read-only folder: the figures are still computed, only not kept


def richness_runs(atlas, books, prefix):
    """
    The chapter-level material 1d's size yardstick is cut from: for each
    book, its chapters in order with their word counts and the roots
    each holds, plus the testament's hapax roots and each book's own
    roots.  Built once per call of richness_section.
    """
    hapax = {r[0] for r in atlas.db.execute("SELECT root FROM words WHERE weight = 1 AND root GLOB ?",
                                            (prefix + "[0-9]*",))}
    # The runs are Hebrew (or Greek) text: an Aramaic chapter of Daniel
    # or Ezra would put a run's own-root and hapax rates out of reach,
    # since almost nothing else is in Aramaic, so Aramaic roots are left
    # out of every chapter and a chapter mostly in Aramaic is skipped
    aramaic = atlas.aramaic_roots() if prefix == "H" else set()
    aramaic_chapters = set()
    if aramaic:
        for b2, ch, n_ar, n_all in atlas.db.execute(
                "SELECT book, chapter, SUM(CASE WHEN language = 'Aramaic' THEN LENGTH(word_string) - "
                "LENGTH(REPLACE(word_string, ' ', '')) + 1 ELSE 0 END), SUM(LENGTH(word_string) - "
                "LENGTH(REPLACE(word_string, ' ', '')) + 1) FROM verses GROUP BY book, chapter"):
            if n_all and n_ar > n_all / 2:
                aramaic_chapters.add((b2, ch))
    own = {}
    chapters = {}
    for b in books:
        own[b] = {r[0] for r in atlas.db.execute(
            "SELECT root FROM word_book wb JOIN words w USING (root) WHERE wb.book = ? AND w.books_reached = 1 "
            "AND root GLOB ?", (b, prefix + "[0-9]*"))}
        words = {r[0]: r[1] for r in atlas.db.execute(
            "SELECT chapter, SUM(LENGTH(word_string) - LENGTH(REPLACE(word_string, ' ', '')) - 1) "
            "FROM verses WHERE book = ? GROUP BY chapter", (b,))}
        roots = {}
        for ch, root, w in atlas.db.execute(
                "SELECT chapter, root, weight FROM word_chapter WHERE book = ? AND root GLOB ?",
                (b, prefix + "[0-9]*")):
            if root not in aramaic:
                roots.setdefault(ch, {})[root] = w
        chapters[b] = [(ch, words.get(ch, 0), roots.get(ch, {})) for ch in sorted(words)
                       if (b, ch) not in aramaic_chapters]
    return hapax, own, chapters


def richness_expected(material, n_words):
    """
    What a run of consecutive chapters of about n_words words, cut from
    the books in the material, gives: the median roots per 1,000,
    hapaxes per 1,000 and own roots per 1,000 over every such run, and
    the median once-here share, and the number of runs.  A run is taken
    from each starting chapter,
    extended until it holds 0.8 n_words, and kept if it holds no more
    than 1.25 n_words; a book shorter than 0.8 n_words gives none.
    """
    hapax, own, chapters = material
    runs = []
    by_book = {}                     # book -> its runs, so each supplying book counts once
    for b, chs in chapters.items():
        for start in range(len(chs)):
            n, roots = 0, {}
            for ch, w, rs in chs[start:]:
                n += w
                for r, wt in rs.items():
                    roots[r] = roots.get(r, 0) + wt
                if n >= 0.8 * n_words:
                    break
            if n < 0.8 * n_words or n > 1.25 * n_words:
                continue
            run = (per_thousand(len(roots), n), per_thousand(sum(1 for r in roots if r in hapax), n),
                   per_thousand(sum(1 for r in roots if r in own[b]), n),
                   round(sum(1 for w in roots.values() if w == 1) / len(roots), 2) if roots else 0)
            runs.append(run)
            by_book.setdefault(b, []).append(run)
    if not runs:
        return None
    # The median of each supplying book's own median, so that a book
    # with many short chapters (Matthew offers eight starting points
    # for a 20,000-word run, John one) does not outvote the others; at
    # the largest sizes only three or four books can supply a run at
    # all, and the figure is then the median of those few, which the
    # footer names
    def med(values):
        values = sorted(values)
        return values[len(values) // 2]
    book_medians = [tuple(med([r[i] for r in rs]) for i in range(4)) for rs in by_book.values()]
    return (med([m[0] for m in book_medians]), med([m[1] for m in book_medians]),
            med([m[2] for m in book_medians]), med([m[3] for m in book_medians]), len(runs),
            sorted(by_book))


def richness_section(atlas, report, title, book, peers, group):
    """
    1d: the measure 1b and 1c cannot see, how rich a book's vocabulary
    is.  Hebrews has about 150 Greek words found nowhere else in the
    New Testament, the highest rate of any book its size, which is what
    the stylists meant when they called its author a man of letters;
    James and 2 Peter are the other two.  Three figures per book, roots
    only (Strong's numbers, the glossing rule's absorptions counted into
    their roots): hapax legomena, the roots used once in the whole
    testament (a Hebrew number never occurs in the Greek testament, so
    a testament hapax and a Bible hapax are the same root here); the
    book's own roots, used in no other book of the testament; and the
    share of the book's roots used once in the book.  All three per
    1,000 words or as a share, since the counts grow with the book.
    The rates still lean on size (a long book has more room for a root
    to recur), so beside each rate stands what a run of chapters of the
    book's own size cut from the kind's other books gives, the same
    run-cutting the Delta yardsticks use (Harrison's 1921 case on the
    Pastorals rested on hapaxes per page, and his critics answered that
    size and subject explain much of it; the run column is that answer
    as a number).  Rows: the book, then the peers by size, largest
    first, so that like sizes sit together.
    """
    testament = atlas.book_info[book]["testament"]
    kin = [b for b in peers if atlas.book_info[b]["testament"] == testament]
    prefix = "H" if testament == "Old" else "G"
    alone = ("" if kin else
             f"Not measured against the kind: the other books of '{group}' are all in the other testament, "
             f"and a root of one testament never occurs in the other, so {book}'s row stands alone, its run "
             f"figures come from its own testament's books (marked 't'), and the footer names its nearest "
             f"books there.  ")
    sec = report.section(
        title, ["text", "words", "roots", "roots/1000", "run", "hapaxes", "hapaxes/1000", "run",
                "own roots", "own/1000", "run", "once here", "once here (share)", "run"],
        note=alone + f"How rich the vocabulary is, {book} beside each book of its kind, the baseline group "
             f"'{group}' (own testament only).  Roots only (Strong's numbers).  'roots' is the distinct "
             f"roots the book uses and 'roots/1000' that count per 1,000 words, a type-to-token figure; "
             f"'hapaxes' is the book's roots used once in the whole testament (a root of one testament "
             f"never occurs in the other, so a testament hapax is a Bible hapax); 'own roots' is the "
             f"book's roots found in no other book of the testament, used once or many times; "
             f"'once here' is the book's roots used once in the book, and the share of all its roots they "
             f"are.  Every rate falls as a book grows (a long book has more room for a root to recur), so "
             f"each 'run' column gives what a run of consecutive chapters of that row's size, cut from the "
             f"testament's other books (every book but the row's own, Aramaic chapters left out), typically "
             f"yields, the median over every such run; a rate well above its run figure is richness, a "
             f"rate near it is size.  The runs come from the whole testament and not the kind alone, so "
             f"that every row of a size is read against the same supply of text: in a four-book kind the "
             f"books that happen to supply the runs move the figure more than the size does.  One caution: a hapax and an own root "
             f"are measured against the other books of the testament, so a book with a sibling that shares "
             f"its text scores low for a reason that is not poverty (a Synoptic Gospel beside the other two, "
             f"Kings beside Chronicles, Ephesians beside Colossians, 2 Peter beside Jude); a shared tradition "
             f"lowers the hapax rate as surely as a small vocabulary does, and for such a book the rate to "
             f"read is 'once here (share)', which no sibling can touch.  Section 1b asks which words the book "
             f"owns; 1c whose habits it has; this table how wide its vocabulary is, the second axis that "
             f"separates Hebrews from Romans where the particles do not.  The peers are in order of size, "
             f"largest first.  Click a row for the book's page.")
    # The run figures depend only on the books cut and the size, so they
    # are computed once and kept on disk under the build stamp; the
    # chapter material is loaded only when a figure is missing
    cache = richness_cache_load(atlas)
    material = {}                    # "kind" / "testament" -> the chapter material, loaded on demand
    testament_books = [b for b in atlas.books if atlas.book_info[b]["testament"] == testament]

    # The ceiling: the largest run size at least RICHNESS_MIN_RUNS books
    # of the testament can supply with a remainder.  Above it the rows
    # were read against different supplies (a 24,000-word run can come
    # only from Luke and Acts, a 26,000-word one from nothing), so a row
    # larger than the ceiling is read against runs of the ceiling's
    # size, which hapaxes and own roots per 1,000 allow, since they
    # barely move with size; the footer says so for those rows
    sizes = sorted((atlas.book_info[b]["words"] for b in testament_books), reverse=True)
    ceiling = int(sizes[RICHNESS_MIN_RUNS - 1] / 1.25) if len(sizes) >= RICHNESS_MIN_RUNS else sizes[-1]
    capped = []

    def expected_for(which, books, b, n_words):
        size = min(n_words, ceiling)
        if size < n_words:
            capped.append(b)
        key = f"{which}|{b}|{size}"
        if key in cache["runs"]:
            return cache["runs"][key]
        if which not in material:
            material[which] = richness_runs(atlas, books, prefix)
        hx, ow, chs = material[which]
        found = richness_expected((hx, ow, {k: v for k, v in chs.items() if k != b}), size)
        cache["runs"][key] = list(found) if found else None
        cache["dirty"] = True
        return cache["runs"][key]

    # A book in two languages (Daniel, Ezra) is measured a language at a
    # time: its Hebrew roots against its Hebrew words, with the run
    # figures for that size, and its Aramaic roots as a row of their own
    # with no run figure, since the Aramaic corpus (Daniel 2:4 to 7:28,
    # Ezra 4:8 to 6:18 and 7:12 to 26) is too small to cut a yardstick
    # from and its own-root and hapax rates are high by construction,
    # almost nothing else being in Aramaic.  Before this, Daniel showed
    # 35 own roots per 1,000 against a run figure of 4
    aramaic = atlas.aramaic_roots() if prefix == "H" else set()
    aramaic_rows = []

    def figures(b, lang=None):
        """(words, roots, hapax, own, once_here) for a book, or for one of its languages."""
        if lang is None:
            n_words = atlas.book_info[b]["words"]
            where, args = "", ()
        else:
            n_words = atlas.db.execute(
                "SELECT COALESCE(SUM(LENGTH(word_string) - LENGTH(REPLACE(word_string, ' ', '')) - 1), 0) "
                "FROM verses WHERE book = ? AND language = ?", (b, lang)).fetchone()[0]
        rows_ = atlas.db.execute(
            "SELECT wb.root, wb.weight, w.weight, w.books_reached FROM word_book wb JOIN words w USING (root) "
            "WHERE wb.book = ? AND root GLOB ?", (b, prefix + "[0-9]*")).fetchall()
        if lang == "Aramaic":
            rows_ = [r for r in rows_ if r[0] in aramaic]
        elif lang is not None:
            rows_ = [r for r in rows_ if r[0] not in aramaic]
        return (n_words, len(rows_), sum(1 for r in rows_ if r[2] == 1), sum(1 for r in rows_ if r[3] == 1),
                sum(1 for r in rows_ if r[1] == 1))

    rows = []
    few_suppliers = []               # (row book, the books that supplied its runs) when under RICHNESS_MIN_RUNS
    for b in [book] + kin:
        lang = None
        if aramaic:
            n_ar = atlas.db.execute(
                "SELECT COALESCE(SUM(LENGTH(word_string) - LENGTH(REPLACE(word_string, ' ', '')) - 1), 0) "
                "FROM verses WHERE book = ? AND language = 'Aramaic'", (b,)).fetchone()[0]
            if n_ar >= FEW_WORDS:
                lang = "Hebrew"
                aw, ar, ah, ao, aonce = figures(b, "Aramaic")
                aramaic_rows.append((b + " (Aramaic)", aw, ar, per_thousand(ar, aw), "-", ah, per_thousand(ah, aw),
                                     "-", ao, per_thousand(ao, aw), "-", aonce, round(aonce / ar, 2) if ar else 0,
                                     "-"))
        n_words, roots, hapax, own, once_here = figures(b, lang)
        roots = roots or 0
        # The run figures for this size, always from the testament's
        # other books.  Struck from the kind's books they depended on
        # who supplied the runs: in NT Narrative, Matthew's hapax figure
        # came from Luke and Acts (rich) at 9.4 while Luke's came from
        # Matthew, Mark and John (sibling-depressed) at 3.5, a threefold
        # difference at the same size.  The testament gives every row the
        # same supply, and the footer names the books that gave runs
        expected = expected_for("testament", testament_books, b, n_words)
        if expected is None:
            run = ("-", "-", "-", "-")
        else:
            run = tuple(f"{x:.1f}" for x in expected[:3]) + (f"{expected[3]:.2f}",)
            if len(expected) > 5 and len(expected[5]) < RICHNESS_MIN_RUNS:
                few_suppliers.append((b, expected[5]))
        rows.append((b, n_words, roots, per_thousand(roots, n_words), run[0], hapax, per_thousand(hapax, n_words),
                     run[1], own, per_thousand(own, n_words), run[2], once_here or 0,
                     round((once_here or 0) / roots, 2) if roots else 0, run[3]))
    first, rest = rows[0], sorted(rows[1:], key=lambda r: -r[1])
    for r in [first] + rest:
        label = r[0] + (" (small book)" if r[1] < BOOK_SMALL_WORDS else "")
        if any(r[0] == a[0].replace(" (Aramaic)", "") for a in aramaic_rows):
            label += " (Hebrew)"
        sec.add([label] + list(r[1:]), link={"book": r[0]})
    for a in aramaic_rows:
        sec.add(list(a), link={"book": a[0].replace(" (Aramaic)", "")})
    if aramaic_rows:
        sec.footer.append(
            "A book in two languages is measured a language at a time: its Hebrew row against the run "
            "figures, and its Aramaic roots in a row of their own with no run figure, since the Aramaic "
            "corpus (Daniel 2:4 to 7:28, Ezra 4:8 to 6:18 and 7:12 to 26) is too small to cut a yardstick "
            "from and its own-root and hapax rates are high by construction, almost nothing else being "
            "in Aramaic.  The runs themselves leave Aramaic chapters and roots out.")
    sec.footer.append("Rates fall as books grow: read each rate beside its 'run' figure, what the testament's "
                      "other books give at that size.")
    if capped:
        sec.footer.append(
            f"Runs are cut no larger than {ceiling:,} words, the largest size at least {RICHNESS_MIN_RUNS} "
            f"books of the testament can supply with a remainder, so that every row is read against the "
            f"same supply of text; the rows larger than that ({', '.join(dict.fromkeys(capped))}) are read "
            f"against runs of {ceiling:,} words, which hapaxes and own roots per 1,000 allow, since they "
            f"barely move with size, and roots per 1,000 does not: for those rows read the hapax and "
            f"own-root columns.")
    if few_suppliers:
        sec.footer.append(
            f"Where fewer than {RICHNESS_MIN_RUNS} books are large enough to supply a run of the row's size, "
            f"the run figure is the median of those few, and which they are matters: "
            + "; ".join(f"{b} from {', '.join(bs)}" for b, bs in few_suppliers) + ".")
    # The nearest books outside the kind on the two rates that do not
    # lean on size, hapaxes and own roots per 1,000 (a hapax is a
    # property of the root, not of the run it sits in), so that 1 John
    # can be seen beside John's Gospel and Lamentations beside Psalms
    own_row = rows[0]
    outside = []
    for b in testament_books:
        if b == book or b in kin:
            continue
        n = atlas.book_info[b]["words"]
        h = atlas.db.execute(
            "SELECT COUNT(*) FROM word_book wb JOIN words w USING (root) WHERE wb.book = ? AND w.weight = 1 "
            "AND root GLOB ?", (b, prefix + "[0-9]*")).fetchone()[0]
        o = atlas.db.execute(
            "SELECT COUNT(*) FROM word_book wb JOIN words w USING (root) WHERE wb.book = ? AND w.books_reached = 1 "
            "AND root GLOB ?", (b, prefix + "[0-9]*")).fetchone()[0]
        hr, orate = per_thousand(h, n), per_thousand(o, n)
        outside.append((abs(hr - own_row[6]) + abs(orate - own_row[9]), b, n, hr, orate))
    outside.sort(key=lambda r: r[0])
    if outside:
        sec.footer.append(
            f"Nearest beyond the kind on hapaxes and own roots per 1,000 (the two rates that do not lean on "
            f"size; {book} has {own_row[6]} and {own_row[9]}): " + "; ".join(
                f"{b} {hr} and {orate} ({n} words)" for _, b, n, hr, orate in outside[:3]) + ".")
    richness_cache_save(atlas)


def lexicon_section(atlas, report, title, roots, book=None, chapter=None, scope_label="Bible"):
    """
    The Hebrew or Greek behind a signature words table: each root with
    its original word from Strong's dictionary, the KJV glosses, and
    how this text spells it.  Only on a Strong's build, and only for
    roots that are numbers.
    """
    if atlas.roots_mode != "strongs" or not atlas.lexicon:
        return
    numbered = [r for r in roots if is_strongs(r) and atlas.lexicon_entry(r)]
    if not numbered:
        return
    head = title.split(".")[0]
    sec = report.section(
        f"{head}a. The words behind section {head}",
        ["word", "original", "KJV glosses", f"spelled in {scope_label}", "spelled in the Bible"],
        note="Each Strong's number of the table above with its Hebrew or Greek word and the "
             "English the King James translators used for it (Strong's dictionary), then the "
             f"spellings used for it in {scope_label} and across the Bible, commonest first with "
             "counts.  Double-click a row for the word's page.")
    for root in numbered:
        word, kjv_def, strongs_def = atlas.lexicon_entry(root)
        glosses = clean_gloss(kjv_def or strongs_def)
        here = ", ".join(f"{sp} {n}" for sp, n in atlas.spellings(root, limit=5, book=book, chapter=chapter))
        bible = ", ".join(f"{sp} {n}" for sp, n in atlas.spellings(root, limit=5))
        sec.add([atlas.form(root), word, glosses, here, bible], link={"word": root})


def signature_formulas_section(atlas, report, title, verses, book, n_scope):
    """Add the signature formulas table for a set of verses."""
    n_out = atlas.n_bible - n_scope
    strings = {v["reference"]: v[atlas.phrase_column] for v in verses}
    phrase_counts = phrases_in(verses, atlas.phrase_column)

    scored = []
    for phrase, (a, times) in phrase_counts.items():
        if a < 2:
            continue                       # must be spread over 2+ verses
        row = atlas.db.execute("SELECT verses_total FROM ngrams WHERE phrase = ?", (phrase,)).fetchone()
        total = row[0] if row else a
        b = total - a
        scored.append((phrase, a, times, b, log_likelihood(a, b, n_scope, n_out)))
    scored.sort(key=lambda r: (-r[4], -len(r[0])))

    # Grow overlapping pieces into one phrase and keep each once
    kept = {}
    for phrase, a, times, b, g2 in scored:
        refs = [ref for ref, s in strings.items() if f" {phrase} " in s]
        grown = atlas.grow_formula(phrase, [strings[r] for r in refs])
        if grown in kept:
            continue
        # "and joseph" trims to "joseph": a name after a conjunction is
        # not a formula, so anything left with one word is passed over
        if len(grown.split()) < 2:
            continue
        if grown != phrase:
            b = atlas.count_phrase_outside(grown, book)
            g2 = log_likelihood(a, b, n_scope, n_out)
            times = sum(strings[r].count(f" {grown} ") for r in refs)
        kept[grown] = (grown, a, times, b, g2, refs)
        if len(kept) >= TOP_N * 3:
            break

    # Fold nested duplicates.  "the lord god" and "lord god" are pieces of
    # "saith the lord god" when nearly every verse holding them holds the
    # longer formula too; the longer one is kept.  A shorter formula
    # with a real life of its own (more than a tenth of its verses lie
    # outside the longer one) stays: "day of the lord" beside "the day
    # of the lord is near".
    rows = sorted(kept.values(), key=lambda r: (-r[4], -len(r[0])))
    folded = []
    for row in rows:
        phrase, refs = row[0], set(row[5])
        nested = False
        for other in rows:
            if other[0] != phrase and phrase in other[0] and len(other[0]) > len(phrase):
                covered = len(refs & set(other[5])) / max(len(refs), 1)
                if covered >= NEST_COVER:
                    nested = True
                    break
        if not nested:
            folded.append(row)
    rows = folded

    by_roots = atlas.phrase_column != "word_string"
    sec = report.section(
        title, ["formula", "verses", "times", "rest", "keyness", "where"],
        note="Runs of 2 to 5 words found in at least two different verses, ranked by how much "
             "more often this text uses them than the rest of the Bible.  Keyness is judged on "
             "verses, so a phrase repeated inside one verse counts once; 'times' is the raw count."
             + ("  A formula is a run of Strong's roots, so it is found however its words are "
                "spelled (the heathen and the nations are one formula); the wording shown is "
                "its commonest here." if by_roots else ""))
    for phrase, a, times, b, g2, refs in rows[:TOP_N]:
        where = ", ".join(r.split(" ", 1)[1] if r.startswith(book + " ") else r for r in refs[:6])
        if len(refs) > 6:
            where += ", ..."
        shown = atlas.display_of(phrase, refs) if by_roots else phrase
        sec.add([shown, a, times, b, round(g2, 1), where], refs=refs,
                link={"phrase": shown, "key": phrase})
    sec.merge_duplicates()


def neighbors_section(atlas, report, title, scope, root, word, scope_label):
    """Neighbors of a root inside a book beside its neighbors in the rest of the Bible."""
    occ_scope = atlas.occurrences(scope, root)
    occ_bible = atlas.occurrences("Bible", root)
    if occ_scope < FOCUS_MIN_OCCURRENCES:
        sec = report.section(title, [])
        sec.note = (f"Skipped: '{word}' occurs only {occ_scope} times in {scope_label} "
                    f"(needs {FOCUS_MIN_OCCURRENCES}).")
        return
    sec = report.section(
        title, [f"in {scope_label}", "count", "pull", "", "in the rest of the Bible", "count", "pull"],
        note=f"'{root}' [{scope_label}] ({occ_scope} times), '{root}' [Bible - {scope_label}] "
             f"({occ_bible - occ_scope} times).  A neighbor is a word within {atlas.window} words "
             f"either side, inside the verse; count is meetings, pull is how much more often "
             f"than chance.  Left: 'x' + '{root}' [{scope_label}]; right: [Bible - {scope_label}].")
    left = atlas.neighbors(scope, root)
    right = atlas.neighbors_rest(scope, root)
    for i in range(max(len(left), len(right))):
        l = left[i] if i < len(left) else None
        r = right[i] if i < len(right) else None
        row = ([atlas.form(l["neighbor"]), l["count"], round(l["pull"], 1)] if l else ["", "", ""])
        row += [""]
        row += ([atlas.form(r["neighbor"]), r["count"], round(r["pull"], 1)] if r else ["", "", ""])
        # Clicking a neighbors row leads to that neighbor's word page
        sec.add(row, refs=None,
                link={"word": l["neighbor"], "book": scope, "pair": root} if l else None)


def echoes_section(atlas, report, title, book, chapter=None, scope_name=None, date=None,
                   verse_ids=None, books=None):
    """
    Echoes between a book (or chapter, or chapter range, or passage) and
    other books, rarest first.  chapter is None for the whole book, an
    int for one chapter, or a list of chapters for a section (not always
    a run: Asaph is Psalm 50 and 73 to 83); scope_name is how a section
    is called in the titles; date is a section's own conventional date,
    used in place of the book's for the earlier/contemporary/later
    labels.  A passage from metadata.db gives verse_ids, the verses it
    holds, and books, the books it touches (book is then the first of
    them, for the labels and dates); its partners are the books outside
    it, and the chapter tables are drawn only when it lies in one book.
    """
    is_range = isinstance(chapter, (tuple, list, set, frozenset))
    books = list(books) if books else [book]
    multi = len(books) > 1
    if verse_ids is not None:
        ids = sorted(verse_ids)
        is_range = not multi
        here_rows = atlas.db.execute(
            "SELECT echoes.phrase, echoes.reference FROM echoes "
            "WHERE echoes.verse_id IN (" + ",".join("?" * len(ids)) + ")", ids).fetchall()
        if is_range:
            chapter = sorted({int(r["reference"].rsplit(" ", 1)[1].split(":")[0]) for r in here_rows}) or [1]
    else:
        if is_range:
            chapter = sorted(chapter)
            where = " AND verses.chapter IN (" + ",".join("?" * len(chapter)) + ")"
            params = (book, *chapter)
        elif chapter:
            where, params = " AND verses.chapter = ?", (book, chapter)
        else:
            where, params = "", (book,)
        here_rows = atlas.db.execute(
            "SELECT echoes.phrase, echoes.reference FROM echoes JOIN verses USING (verse_id) "
            "WHERE echoes.book = ?" + where, params).fetchall()
    by_phrase = {}
    for r in here_rows:
        by_phrase.setdefault(r["phrase"], []).append(r["reference"])
    found = []
    not_books = "book NOT IN (" + ",".join("?" * len(books)) + ")"
    for phrase, here in by_phrase.items():
        there = [r[0] for r in atlas.db.execute(
            f"SELECT reference FROM echoes WHERE phrase = ? AND {not_books}", (phrase, *books))]
        if there:
            found.append((phrase, here, there))

    by_roots = atlas.phrase_column != "word_string"

    def rarity_of(phrase):
        if by_roots:
            return sum(atlas.rarity(u) for u in atlas.content_units(phrase))
        return sum(atlas.rarity(atlas.root_of(w)) for w in phrase.split() if w not in STOPLIST)
    found.sort(key=lambda f: (-rarity_of(f[0]), -len(f[0].split()), len(f[2])))

    # Grow each echo against every verse it occurs in, then fold
    # duplicates.  Two echoes are the same echo when their content words
    # have the same roots in the same order: "a ram without blemish",
    # "ram without blemish" and "rams without blemish" all fold to one
    # ("stand", "stood" and "standing afar off" likewise).  The longest
    # spelling is shown and the locations are pooled.
    def root_key(phrase):
        if by_roots:
            return atlas.content_units(phrase)
        return tuple(atlas.root_of(w) for w in phrase.split() if w not in STOPLIST)

    kept = {}                 # root key -> [phrase, here, there]
    order = []
    for phrase, here, there in found:
        if len(kept) >= ECHO_N * 2:
            break
        refs = list(here) + list(there)
        marks = ",".join("?" * len(refs))
        english = phrase.startswith("en:")
        column = "word_string" if english else atlas.phrase_column
        strings = [r[0] for r in atlas.db.execute(
            f"SELECT {column} FROM verses WHERE reference IN ({marks})", refs)]
        bare = phrase[3:] if english else phrase
        grown = atlas.grow_formula(bare, strings) if strings else bare
        if english:
            grown = "en:" + grown
        key = root_key(grown)
        # A key nested inside a longer kept key with the same places is a piece
        if any(len(k) > len(key) and any(k[i:i + len(key)] == key for i in range(len(k)))
               and set(there) <= set(kept[k][2]) for k in kept):
            continue
        if key in kept:
            entry = kept[key]
            if len(grown) > len(entry[0]):
                entry[0] = grown
            entry[1] = list(dict.fromkeys(entry[1] + list(here)))
            entry[2] = list(dict.fromkeys(entry[2] + list(there)))
            continue
        kept[key] = [grown, list(here), list(there)]
        order.append(key)

    sec = report.section(
        title, ["echo", "grade", "here", "elsewhere"],
        note=f"Shared runs of words, found as formulas of 3 to 5 words and then grown to the whole "
             f"run the two places share (so an echo may be a whole sentence), that occur here and in "
             f"another book, and in no more "
             f"than {ECHO_MAX_TOTAL} verses of the whole Bible.  Ranked by the rarity of their "
             f"words.  Each is a possible quotation, "
             f"allusion or shared idiom; only reading the two passages can say which."
             + ("  Echoes are runs of Strong's roots, found however their words are spelled, so "
                "'the heathen' and 'the nations' are one echo; the wording shown is the commonest "
                "among the verses listed.  Between the testaments, and between Hebrew and Aramaic "
                "verses (Daniel 2 to 7, Ezra's decrees), where roots never match, echoes are found "
                "by English wording instead and marked 'by English'."
                if by_roots else "  Spellings of one echo are folded together.")
             + f"  'quotation' marks an echo of {QUOTE_MIN_WORDS} or more words found in exactly two "
               f"verses of the whole Bible: the strongest kind of evidence the table has; 'by English' "
               f"an echo across the testaments that meets the same test by wording alone, weaker "
               f"evidence, since the translators' idiom can make it.")
    for key in order[:ECHO_N]:
        phrase, here, there = kept[key]
        shown = atlas.display_of(phrase, here + there) if by_roots else phrase
        # Quotation grade: five or more words, in exactly two verses of the Bible
        # An echo found by English wording across the testaments passes the
        # same test on weaker ground (idiom the translators shared), so
        # it is marked as such rather than graded with the root echoes
        if len(shown.split()) >= QUOTE_MIN_WORDS and len(here) + len(there) == 2:
            grade = "by English" if phrase.startswith("en:") else "quotation"
        else:
            grade = ""
        sec.add([shown, grade, ", ".join(here), ", ".join(there)], refs=here + there,
                link={"phrase": shown, "key": phrase})
    # An echo found by root and again by wording shows once
    sec.merge_duplicates(score_column="grade")
    if len(found) > ECHO_N:
        sec.footer.append(f"{len(found) - ECHO_N} more candidate echoes not shown; the tallies "
                          f"below count all of them.")

    # -- tallies over ALL candidates, not just the ones shown ----------------
    # Which books does this text echo, and from which of its chapters?
    # Counted on distinct root keys so spellings and nested pieces do not
    # inflate the numbers.  Each echo also carries a WEIGHT, the summed
    # rarity of its content words, so that "ten thousand times ten
    # thousand" outweighs a bland "a voice from heaven saying" instead of
    # being outvoted by it.
    partner_keys = {}          # partner book -> {root key: weight}
    chapter_keys = {}          # source chapter -> {root key: weight}
    cell_keys = {}             # (source chapter, partner) -> {root key: weight}
    cell_refs = {}             # (source chapter, partner) -> verse refs on both sides
    verse_partners = {}        # source verse ref -> set of partner books it echoes
    points_to = {}             # source chapter -> {(partner, partner chapter): {key: weight}}
    partner_echoes = {}        # partner book -> [(weight, words, quotation grade, key, here, there)]
    for phrase, here, there in found:
        key = root_key(phrase)
        weight = sum(atlas.rarity(r) for r in key)
        there_by_pb = {}
        for r in there:
            there_by_pb.setdefault(r.rsplit(" ", 1)[0], []).append(r)
        for pb in there_by_pb:
            partner_keys.setdefault(pb, {})[key] = weight
            # Kept for the who-reads-whom table: every echo with this
            # partner, its weight, its length and whether it is
            # quotation grade (five or more words in exactly two verses
            # of the whole Bible)
            n_words = len(phrase.split())
            total_verses = len(here) + len(there)
            # 2 = quotation grade on roots, 1 = the same test met by English
            # wording across the testaments (weaker: the translators' idiom),
            # 0 = neither
            if n_words >= QUOTE_MIN_WORDS and total_verses == 2:
                grade = 1 if phrase.startswith("en:") else 2
            else:
                grade = 0
            partner_echoes.setdefault(pb, []).append(
                (weight, n_words, grade, phrase, list(here), list(there_by_pb[pb])))
        here_by_ch = {}
        for r in here:
            ch = int(r.rsplit(" ", 1)[1].split(":")[0])
            here_by_ch.setdefault(ch, []).append(r)
            verse_partners.setdefault(r, set()).update(there_by_pb)
        # Which chapter of each partner the echoes of each chapter point to
        for ch in here_by_ch:
            for pb, t_refs in there_by_pb.items():
                for t in t_refs:
                    pch = int(t.rsplit(" ", 1)[1].split(":")[0])
                    points_to.setdefault(ch, {}).setdefault((pb, pch), {})[key] = weight
        # One entry per distinct echo per chapter and per (chapter, partner),
        # so an echo with two verses in one chapter counts once there; 4b
        # and 4c are then summed from the same dictionary and agree
        for ch, h_refs in here_by_ch.items():
            chapter_keys.setdefault(ch, {})[key] = weight
            for pb, t_refs in there_by_pb.items():
                cell_keys.setdefault((ch, pb), {})[key] = weight
                cell_refs.setdefault((ch, pb), []).extend(h_refs + t_refs)

    # Observed against expected.  If this book's echoes fell on the rest
    # of the Bible in proportion to length alone, a partner would get
    # total echoes x (partner words / words outside this book).  The
    # ratio says how far a partner is above or below that, and it can be
    # compared from one book page to another because it no longer
    # depends on the size of either book.
    total_echoes = sum(len(keys) for keys in partner_keys.values())
    words_outside = atlas.n_bible - sum(atlas.book_info[b]["words"] for b in books)

    # The scope as the titles print it: the chapter on a chapter page,
    # whose tallies are the chapter's own, the book on a book page
    scope_label = scope_name or (f"{book} {chapter}" if chapter else book)
    tally = report.section(
        title.split(".")[0] + f"a. Echo partners [{scope_label}] -> which books",
        ["partner book", "echoes", "weight", "obs/exp", "per 1000 words of partner", "in time"],
        note="Counted over every candidate echo, not only the ones shown above.  'echoes' is "
             "distinct echoes (spellings folded); 'weight' adds up the rarity of their words, so "
             "strong echoes count for more than shared idiom; 'obs/exp' is echoes against what "
             "the partner's length alone would predict (1.0 = no more than chance; comparable "
             "between book pages); 'in time' places the partner by conventional dates.")
    partner_rows = []
    for pb, keys in partner_keys.items():
        words = atlas.book_info[pb]["words"]
        expected = total_echoes * words / words_outside
        partner_rows.append((pb, len(keys), round(sum(keys.values())),
                             round(len(keys) / expected, 2) if expected else 0,
                             round(1000 * len(keys) / words, 2), relation_in_time(book, pb, date)))
    partner_rows.sort(key=lambda r: -r[2])
    # On a section page a 10,000-word text produces under twenty echoes
    # with most books, so the table would be a list of 'few' caveats:
    # only the partners above the 'few' line are printed, plus any with
    # a quotation-grade echo, and the rest are counted in a footer
    shown_rows = partner_rows[:TOP_N]
    if is_range:
        shown_rows = [row for row in partner_rows[:TOP_N]
                      if row[1] >= RATIO_MIN_ECHOES
                      or any(e[2] == 2 for e in partner_echoes.get(row[0], []))]
        left_out = len(partner_rows[:TOP_N]) - len(shown_rows)
        if left_out:
            tally.footer.append(f"{left_out} partners with fewer than {RATIO_MIN_ECHOES} echoes and no "
                                f"quotation-grade echo are not listed; 4a2 and the map count them.")
    for row in shown_rows:
        shown = list(row)
        # A ratio built on a handful of echoes is not worth its decimals:
        # a small book with a few shared idioms always posts a high one
        if row[1] < RATIO_MIN_ECHOES:
            shown[3] = f"({row[3]}) few"
        tally.add(shown, link={"book": row[0], "chapter": 1})
    tally.note += (f"  An obs/exp in brackets marked 'few' rests on fewer than {RATIO_MIN_ECHOES} "
                   f"echoes and should not be read closely.")

    # Direction: what this book read, against who read this book
    by_time = Counter()
    by_time_weight = Counter()
    for pb, n, w, ratio, rate, rel in partner_rows:
        rel = rel.replace(" (disputed)", "")
        by_time[rel] += n
        by_time_weight[rel] += w
    if date is not None:
        tally.footer.append(
            f"This section is dated {abs(date)} {'BC' if date < 0 else 'AD'} in SECTION_DATES "
            f"(atlas_sections.py), against {abs(BOOK_DATES.get(book, 0))} for {book} as a whole in "
            f"BOOK_DATES; the earlier, contemporary and later labels here follow the section's date.")
    tally.footer.append(
        "By conventional dating (edit BOOK_DATES in atlas_text.py to change): echoes with "
        + ", ".join(f"{rel} books {by_time[rel]} (weight {by_time_weight[rel]})"
                    for rel in ("earlier", "contemporary", "later") if by_time[rel])
        + ".  Echoes with earlier books are what this text COULD have read; echoes in later "
          "books are who could have read it; the table cannot tell direction for contemporaries.  "
          "Earlier is not the same as source: an earlier partner may share idiom with this text "
          "without either having read the other.")
    # The same totals under the critical dates, so the two datings can be
    # compared in numbers and not only by reading the disputed partners
    crit_time, crit_weight = Counter(), Counter()
    for pb, n, w, ratio, rate, rel in partner_rows:
        d = dating_dispute(book, pb, date)
        crit_rel = d[1][2] if d else rel.replace(" (disputed)", "")
        crit_time[crit_rel] += n
        crit_weight[crit_rel] += w
    if crit_time != by_time:
        tally.footer.append(
            "By the critical dating (CRITICAL_DATES): echoes with "
            + ", ".join(f"{rel} books {crit_time[rel]} (weight {crit_weight[rel]})"
                        for rel in ("earlier", "contemporary", "later") if crit_time[rel]) + ".")
    # Where the critical dates put a partner on the other side of this
    # text, say so once, with both datings, for every such partner shown
    disputes = []
    for row in partner_rows[:TOP_N]:
        d = dating_dispute(book, row[0], date)
        if d:
            (a, b, conv), (ac, bc, crit) = d
            disputes.append(f"{row[0]} {conv} by the conventional dates ({abs(a)} and {abs(b)}), "
                            f"{crit} by the critical ones ({abs(ac)} and {abs(bc)})")
    if disputes:
        tally.footer.append(
            "'(disputed)' marks a partner the two datings place on different sides: "
            + "; ".join(disputes) + ".  Both tables are in atlas_text.py (BOOK_DATES, CRITICAL_DATES); "
            "the labels follow the conventional one.")
    elif book in DISPUTED_DATES:
        # No partner changes side, and the reader should not have to work
        # out why: say how the shown partners fall under both datings
        # (on Daniel, the Old Testament partners are earlier and the New
        # Testament ones later whether Daniel is 530 or 165)
        shown = [rel.replace(" (disputed)", "") for _, _, _, _, _, rel in partner_rows[:TOP_N]]
        counts = Counter(shown)
        falls = ", ".join(f"{counts[rel]} {rel}" for rel in ("earlier", "contemporary", "later") if counts[rel])
        tally.footer.append(
            f"The date of {book} is disputed (conventional {abs(BOOK_DATES.get(book, 0))}, critical "
            f"{abs(CRITICAL_DATES.get(book, 0))}), but the labels do not depend on it: of the partners "
            f"shown ({falls}), every one falls on the same side of {book} under both dates.")

    # -- who reads whom: each partner's rarest echoes, with both references ------
    # The partner table rewards volume; this one shows the evidence.
    # For each partner in time order, its three rarest echoes (highest
    # summed rarity, longest first among equals) with the verse on each
    # side, and how many of its echoes are quotation grade.  Sources
    # and readers can be cited from here without combing the chapters.
    who = report.section(
        title.split(".")[0] + f"a2. Who reads whom [{scope_label}]: the rarest echo with each partner",
        ["partner book", "in time", "echoes", "quotation grade", "rarest echoes (here -> there)"],
        note=f"For each partner, its {WHO_READS_N} best echoes: quotation grade first, then the "
             f"rarest (summed rarity of their words, longest first among equals), each with the "
             f"verse here and the verse there.  "
             f"'quotation grade' counts echoes of {QUOTE_MIN_WORDS} or more words found in exactly "
             f"two verses of the whole Bible: one here, one there, and nowhere else; an echo that "
             f"meets the test only by English wording across the languages (between the testaments, "
             f"or between Hebrew and Aramaic verses: the translators' "
             f"idiom, not a shared root) is counted apart as 'by English'.  Earlier "
             f"partners are what {book} could have read, later ones who could have read it "
             f"('(disputed)' where the critical dates would say otherwise; see 4a); "
             f"the rarest echo is the one to cite, and the ratio in 4a is the one to distrust "
             f"when the count is small.  Click a row for the verses on both sides.")
    order_in_time = {"earlier": 0, "contemporary": 1, "later": 2, "?": 3}
    # The partners shown in 4a, plus any partner beyond them with two or
    # more quotation-grade echoes: Revelation's few exact borrowings from
    # Ezekiel would otherwise be outvoted by its low volume
    listed = list(partner_rows[:TOP_N])
    for row in partner_rows[TOP_N:]:
        if sum(1 for e in partner_echoes.get(row[0], []) if e[2]) >= 2:
            listed.append(row)
    for pb, n, w, ratio, rate, rel in sorted(listed, key=lambda r: (order_in_time.get(r[5].replace(" (disputed)", ""), 3), -r[2])):
        # Quotation-grade echoes first, then by rarity: summed rarity alone
        # favours long runs of moderately common words
        echoes_pb = sorted(partner_echoes.get(pb, []), key=lambda e: (-e[2], -e[0], -e[1]))
        grade_n = sum(1 for e in echoes_pb if e[2] == 2)
        english_n = sum(1 for e in echoes_pb if e[2] == 1)
        grade_cell = f"{grade_n}" + (f" (+{english_n} by English)" if english_n else "")
        cited, refs, taken = [], [], []
        for weight, n_words, grade, key, here, there in echoes_pb:
            if len(cited) == WHO_READS_N:
                break
            # A piece of an echo already cited ("young bullock without
            # blemish" inside "a young bullock without blemish") is passed over
            # A second echo between the same two verses is nearly always
            # an overlapping piece of the first, so one per verse pair
            pair = (here[0], there[0])
            if pair in taken:
                continue
            taken.append(pair)
            shown = atlas.display_of(key, here + there) if by_roots else key
            h = here[0].split(" ", 1)[1] if here[0].startswith(book + " ") else here[0]
            mark = {2: " (q)", 1: " (q, by English)"}.get(grade, "")
            cited.append(f'"{shown}" {h} -> {there[0]}' + mark)
            refs += here[:1] + there[:1]
        who.add([pb, rel, n, grade_cell, "; ".join(cited)], refs=refs, link={"book": pb, "chapter": 1})

    if (chapter is None or is_range) and len(chapter_keys) > 1 and not multi:
        # -- the echo map: chapters down the side, partners across ----------
        # Cell = summed weight of the echoes between that chapter and
        # that partner; the verses behind a cell are kept for clicking.
        top_partners = [row[0] for row in partner_rows[:12]]
        # Kept on the report for the section layer (section 7)
        if not is_range:
            report.echo_cells = cell_keys
            report.echo_partners = top_partners
        # Column totals: the chapters of each chief partner this text
        # draws on most, summed over every chapter here
        partner_chapter = {}
        for ch, targets in points_to.items():
            for (pb, pch), keys in targets.items():
                partner_chapter.setdefault(pb, Counter())[pch] += sum(keys.values())
        echo_map = report.section(
            title.split(".")[0] + f"c. Echo map [{book}] -> partner books",
            ["chapter"] + top_partners,
            note="Chapters down the side, the twelve chief partner books across.  Each cell is the "
                 "weight of the echoes between that chapter and that book; darker is heavier.  "
                 "In the window, click a cell for the verses on both sides, double-click it to turn "
                 "to that chapter's page and synopsis, and tick 'each column "
                 "on its own scale' when one or two partners swamp the rest.",
            kind="heatmap")
        chapters_sorted = sorted(chapter_keys)
        for i, ch in enumerate(chapters_sorted):
            row = [ch] + [round(sum(cell_keys.get((ch, pb), {}).values())) for pb in top_partners]
            echo_map.add(row, link={"book": book, "chapter": ch})
            for j, pb in enumerate(top_partners):
                refs = cell_refs.get((ch, pb))
                if refs:
                    echo_map.cell_refs[(i, j + 1)] = list(dict.fromkeys(refs))
        for pb in top_partners[:4]:
            top_chs = partner_chapter.get(pb, Counter()).most_common(4)
            if top_chs:
                echo_map.footer.append(f"Chapters of {pb} most drawn on: "
                                       + ", ".join(f"{pch} ({round(w)})" for pch, w in top_chs) + ".")

        by_ch = report.section(
            title.split(".")[0] + f"b. Echoes by chapter [{book} {min(chapter_keys)}..{max(chapter_keys)}]",
            ["chapter", "echoes", "weight", "per 100 words", "chief partners (by weight)", "points to"],
            note="Where in this book the echoes fall, with the three partner books each chapter "
                 "echoes most, judged by weight rather than count so idiom does not outvote "
                 "quotation, and the partner chapter its echoes point to most.  A run of chapters "
                 "echoing one partner is a section with a source; a straight ascending run in "
                 "'points to' means this book follows that partner's order.")
        chapter_words = {r[0]: r[1] for r in atlas.db.execute(
            "SELECT chapter, SUM(LENGTH(word_string) - LENGTH(REPLACE(word_string, ' ', '')) - 1) "
            "FROM verses WHERE book = ? GROUP BY chapter", (book,))}
        # Where each chapter points, per partner: the partner chapter
        # carrying the most weight, kept only when it holds at least a
        # tenth of the chapter's whole weight (a chapter with almost
        # nothing from a partner would otherwise point at random)
        pointer = {}                 # (chapter, partner) -> partner chapter
        for ch in sorted(chapter_keys):
            n = len(chapter_keys[ch])
            words = chapter_words.get(ch, 1) or 1
            chapter_total = sum(chapter_keys[ch].values()) or 1
            partner_weight = Counter()
            for (c, pb), keys in cell_keys.items():
                if c == ch:
                    partner_weight[pb] += sum(keys.values())
            chief = ", ".join(f"{pb} ({round(w)})" for pb, w in partner_weight.most_common(3))
            targets = Counter({k: sum(v.values()) for k, v in points_to.get(ch, {}).items()})
            # Each chief partner gets its own best chapter first (so a
            # chapter with two strong Matthew pointers still shows its
            # Mark pointer), then the next best overall, three in all,
            # every one above the floor
            chosen = []
            for pb, _n, _w, _r, _rate, _rel in partner_rows[:2]:
                own = [(k, w) for k, w in targets.most_common() if k[0] == pb]
                if own and own[0][1] >= 0.1 * chapter_total:
                    chosen.append(own[0])
                    pointer[(ch, pb)] = own[0][0][1]
            for k, w in targets.most_common():
                if len(chosen) == 3 or w < 0.1 * chapter_total:
                    break
                if all(k != c[0] for c in chosen):
                    chosen.append((k, w))
            chosen.sort(key=lambda kw: -kw[1])
            shown = [f"{pb} {pch} ({round(w)})" for (pb, pch), w in chosen]
            to = "; ".join(shown) if shown else "-"
            by_ch.add([ch, n, round(sum(chapter_keys[ch].values())), round(100 * n / words, 1), chief, to],
                      link={"book": book, "chapter": ch})

        # The order argument in a sentence: for each chief partner, every
        # run of ORDER_RUN_MIN or more chapters whose pointers to that
        # partner never go backwards.  A chapter with no pointer to the
        # partner is skipped, not a break: Matthew 25 points only to Luke,
        # but 26 to 28 carry on from Mark 14 to 16, so Matthew follows
        # Mark from 12 to 28.
        for pb, _n, _w, _r, _rate, _rel in partner_rows[:2]:
            pointed = [(ch, pointer[(ch, pb)]) for ch in sorted(chapter_keys) if (ch, pb) in pointer]
            runs = []
            start = 0
            for i in range(1, len(pointed) + 1):
                if i == len(pointed) or pointed[i][1] < pointed[i - 1][1]:
                    count = i - start
                    if count >= ORDER_RUN_MIN:
                        first, last = pointed[start][0], pointed[i - 1][0]
                        # A run must be dense to mean anything: more
                        # pointers than skipped chapters, or five or more
                        # with no gap wider than two.  Five pointers with a
                        # six-chapter hole (Ezekiel on Jeremiah) say nothing.
                        skipped = (last - first + 1) - count
                        gaps = [pointed[k + 1][0] - pointed[k][0] - 1 for k in range(start, i - 1)]
                        dense = count > skipped or (count >= 5 and max(gaps, default=0) <= 2)
                        if dense and (skipped == 0 or count >= ORDER_RUN_GAPPED_MIN):
                            runs.append((first, last, count))
                    start = i
            for first, last, count in runs:
                # Chapters inside the run with no pointer to this partner,
                # as ranges: Luke's travel narrative (10 to 16) shows here
                have = {ch for ch, _p in pointed}
                gaps, gap_start = [], None
                for ch in range(first, last + 2):
                    if ch <= last and ch not in have:
                        gap_start = ch if gap_start is None else gap_start
                    elif gap_start is not None:
                        gaps.append(f"{gap_start}" if gap_start == ch - 1 else f"{gap_start} to {ch - 1}")
                        gap_start = None
                passed = f"; passing over {', '.join(gaps)}, with no {pb} pointer" if gaps else ""
                by_ch.footer.append(
                    f"Follows the order of {pb} from chapter {first} to {last} "
                    f"({count} chapters whose echoes point to {pb} chapters in non-decreasing order{passed}).")

        # The map is built before the chapter table (the table needs its
        # cells) but reads after it, so 4b comes before 4c on the page
        report.sections.remove(echo_map)
        report.sections.insert(report.sections.index(by_ch) + 1, echo_map)

        # -- sharing between the two chief partners, verse by verse -------------
        # For a Gospel this is the classic source map: verses echoing
        # both Matthew and Mark are the triple tradition, Matthew only
        # the sayings source, Mark only Luke's use of Mark, and neither
        # is Luke's own material.  For any other book it still says
        # whether its two chief partners overlap or divide the text.
        if len(partner_rows) >= 2 and verse_ids is None:
            # The two heaviest partners whose echoes are spread through
            # the book: one with NARROW_PARTNER_SHARE or more of its weight
            # in five chapters (2 Kings in Isaiah 7 and 36 to 39, 94
            # percent) would hold a column that is empty elsewhere, while a
            # pointed partner spread through the book (Daniel in
            # Revelation, 59 percent) keeps its place
            candidates = [row[0] for row in partner_rows[:6]]

            def concentration(pb):
                """Share of the partner's echo weight held by its five heaviest chapters here."""
                by_ch = sorted((sum(keys.values()) for (ch, p), keys in cell_keys.items() if p == pb),
                               reverse=True)
                total = sum(by_ch)
                return sum(by_ch[:5]) / total if total else 1.0

            broad = [pb for pb in candidates if concentration(pb) <= NARROW_PARTNER_SHARE]
            ranked = broad + [pb for pb in candidates if pb not in broad]
            a_book, b_book = ranked[0], ranked[1]
            gospel = book in GOSPELS and a_book in GOSPELS and b_book in GOSPELS
            reading = (f"For a Gospel: both is the triple tradition, one partner only is material "
                       f"shared with that Gospel alone, neither is this Gospel's own.  "
                       if gospel else
                       f"Here both is a verse that echoes both partners, one partner only a verse "
                       f"that echoes that book alone, neither a verse that echoes neither.  ")
            common = common_roots(atlas, book)
            share = report.section(
                title.split(".")[0] + f"d. Verses shared with {a_book} and {b_book}, by chapter",
                ["chapter", "verses", "both", f"{a_book} only", f"{b_book} only", "neither"],
                note=f"Each verse of {book} is tagged by which of its two chief partners it has a "
                     f"parallel in.  Two verses are parallel when the content words they share in the "
                     f"same order number at least {PARALLEL_MIN_SHARED} and make up at least "
                     f"{PARALLEL_SHARE:.0%} of the shorter verse (no Bible-wide rarity cap: between two "
                     f"books the question is parallel, not allusion).  Words in more than "
                     f"{PARALLEL_COMMON_SHARE:.0%} of {book}'s verses are set aside first, so its own "
                     f"formulas do not count as parallels"
                     + (f" (here: {', '.join(atlas.form(r) for r in sorted(common))})" if common else "")
                     + f".  A verse carrying a quotation-grade echo with a partner (see 4a2) counts as "
                     f"a parallel too.  The two partners are the heaviest whose echoes are spread through "
                     f"{book}: a partner with more than {NARROW_PARTNER_SHARE:.0%} of its echo weight in "
                     f"five chapters (2 Kings in Isaiah 7 and 36 to 39) is passed over, so it does not "
                     f"hold a column empty everywhere else.  "
                     f"'both' = a parallel in {a_book} and one in {b_book}; 'neither' = no "
                     f"parallel with either.  " + reading
                     + "An empty stretch in one column is a passage the partner does not have.")
            chapter_verses = {r[0]: r[1] for r in atlas.db.execute(
                "SELECT chapter, COUNT(*) FROM verses WHERE book = ? GROUP BY chapter", (book,))}
            if is_range:
                chapter_verses = {c: n for c, n in chapter_verses.items() if c in chapter}
            with_a = dict(parallels(atlas, book, a_book))
            with_b = dict(parallels(atlas, book, b_book))
            # A verse carrying a quotation-grade echo with the partner is a
            # parallel too: the share rule was made for the Synoptics,
            # where whole verses are shared, and misses a five-word
            # borrowing inside a long verse (Revelation 5:11 from Daniel 7:10)
            quoted = Counter()
            for partner, table in ((a_book, with_a), (b_book, with_b)):
                for weight, n_words, grade, key, here, there in partner_echoes.get(partner, []):
                    if grade:
                        for h in here:
                            if h not in table:
                                table[h] = Counter({there[0]: 1})
                                quoted[partner] += 1
            tagged = len(set(with_a) | set(with_b))
            all_verses = sum(chapter_verses.values())
            if tagged < PARALLEL_MIN_APPLIES * all_verses:
                # A table that is nearly all "neither" says only that the
                # section does not fit the book: say so in one line instead
                share.note = (f"Not shown: fewer than {PARALLEL_MIN_APPLIES:.0%} of {book}'s verses "
                              f"({tagged} of {all_verses}) have a parallel in {a_book} or {b_book} by "
                              f"the share rule or a quotation-grade echo.  {book} borrows phrases "
                              f"rather than verses; section 4a2 is the table to read.")
                share.columns = []
                return
            tags_by_ch = {}
            share_refs = {}
            for ref in set(with_a) | set(with_b):
                ch = int(ref.rsplit(" ", 1)[1].split(":")[0])
                if ch not in chapter_verses:
                    continue
                tag = "both" if ref in with_a and ref in with_b else "a" if ref in with_a else "b"
                tags_by_ch.setdefault(ch, Counter())[tag] += 1
                share_refs.setdefault((ch, tag), []).append(ref)
            for ch in sorted(chapter_verses):
                t = tags_by_ch.get(ch, Counter())
                total = chapter_verses[ch]
                neither = total - t["both"] - t["a"] - t["b"]
                refs = share_refs.get((ch, "both"), []) + share_refs.get((ch, "a"), []) + share_refs.get((ch, "b"), [])
                share.add([ch, total, t["both"], t["a"], t["b"], neither],
                          refs=sorted(refs, key=lambda r: int(r.rsplit(":", 1)[1])),
                          link={"book": book, "chapter": ch})
            totals = Counter()
            for t in tags_by_ch.values():
                totals.update(t)
            share.footer.append(
                f"Whole book: {totals['both']} verses with both, {totals['a']} with {a_book} only, "
                f"{totals['b']} with {b_book} only, "
                f"{all_verses - totals['both'] - totals['a'] - totals['b']} with neither, "
                f"of {all_verses} (share {PARALLEL_SHARE:.0%}"
                + (f"; {quoted[a_book]} verses added by quotation-grade echoes with {a_book}, "
                   f"{quoted[b_book]} with {b_book}" if quoted else "") + ").")
            # The same tallies at the trial shares, so the reader can see
            # how far the columns move with the threshold
            for trial in PARALLEL_TRIALS:
                ta = parallels(atlas, book, a_book, share=trial)
                tb = parallels(atlas, book, b_book, share=trial)
                both = sum(1 for r in ta if r in tb)
                share.footer.append(
                    f"At share {trial:.0%}: {both} with both, {len(ta) - both} with {a_book} only, "
                    f"{len(tb) - both} with {b_book} only, "
                    f"{all_verses - len(ta) - len(tb) + both} with neither.")


# ---------------------------------------------------------------------------
# The pages
# ---------------------------------------------------------------------------

def book_page(atlas, book_name):
    """The four reports for one book."""
    book = atlas.find_book(book_name)
    atlas.use_scope(book)
    info = atlas.book_info[book]
    report = Report(f"book_{book.lower().replace(' ', '_')}",
                    f"Book page [{book}] ({atlas.settings['translation']})")
    report.notes.append(f"{book}: {info['verses']} verses, {info['chapters']} chapters, "
                        f"{info['words']} words.  Rest of the Bible: {atlas.n_bible - info['words']} words.")
    report.notes.append(atlas.divine_name_note())
    # Where the book's tagged words are Aramaic (Daniel 2 to 7, Ezra 4 to
    # 7, a verse of Jeremiah 10), by chapter; nothing when none are
    language = atlas.language_note(book)
    if language:
        report.notes.append(language)

    rows = [(r["root"], r["weight"], r["chapters_reached"], r["keyness"]) for r in atlas.db.execute(
        "SELECT root, weight, chapters_reached, keyness FROM word_book "
        "WHERE book = ? AND weight >= 2 ORDER BY keyness DESC LIMIT ?", (book, TOP_N))]
    top = signature_words_section(atlas, report, f"1. Signature words [{book}]", rows,
                                  info["words"], book, book, None, info["chapters"])
    # 1b: the same words against the book's own kind, the baseline group
    # from metadata.db, where the two lines of the project meet
    group_words_section(atlas, report, f"1b. Signature words against the book's kind [{book}]", book, top)
    # 1c: the function-word profile against the same kind (atlas_function.py)
    groups = atlas.baseline_groups()
    if groups.get(book):
        peers = [b for b in atlas.books if groups.get(b) == groups[book] and b != book]
        function_book_table(atlas, report, f"1c. Function words against the book's kind [{book}]",
                            book, peers, groups[book])
        richness_section(atlas, report, f"1d. Vocabulary richness against the book's kind [{book}]",
                         book, peers, groups[book])
    # 1e and 1f: a New Testament book's Greek against the Septuagint
    # (atlas_septuagint.py), the comparison 1b cannot make across the
    # testaments; nothing yet for an Old Testament book, whose measured
    # text is the Hebrew behind the KJV
    if info["testament"] == "New":
        septuagint_vocabulary_sections(atlas, report, "1", book)

    verses = atlas.verses_of(book)
    signature_formulas_section(atlas, report, f"2. Signature formulas [{book}]",
                               verses, book, info["words"])

    # The focus roots: the fixed words resolved in this book's testament
    # (day is H3117 in Isaiah and G2250 in Luke), then the top signature
    # words not already there
    testament = info["testament"]
    focus = [atlas.root_of(w, testament) for w in FOCUS_WORDS]
    for r in top:
        if r not in focus and len(focus) < len(FOCUS_WORDS) + 3:
            focus.append(r)
    for i, root in enumerate(focus):
        neighbors_section(atlas, report, f"3.{i + 1} Neighbors of '{atlas.form(root)}' [{book}]",
                        book, root, atlas.forms.get(root, root), book)

    echoes_section(atlas, report, f"4. Echoes [{book}] -> other books", book)
    # 4b: the echoes across the testaments in Greek, through the
    # Septuagint (atlas_septuagint.py): section 4's 'by English' rows
    # tested by root
    far = "Greek Old Testament" if info["testament"] == "New" else "New Testament, in Greek"
    septuagint_echoes_section(atlas, report, f"4e. Septuagint echoes [{book}] -> {far}", book)
    if atlas.has_depth:
        reach_depth_section(atlas, report, f"5. Reach and depth [{book}]", book, info)
    if info["chapters"] > 2:
        within_book_section(atlas, report, f"6. Echoes within [{book}]: chapter against chapter", book)
        kin_within_section(atlas, report, f"6c. Kin within [{book}]: chapters sharing rare words in any order", book)
        shared_vocabulary_section(atlas, report, f"6d. Shared vocabulary [{book}]: chapters drawing on the same uncommon words", book)
    if sections_of(book, None, info["chapters"]):
        sections_section(atlas, report, f"7. Sections [{book}]", book, info)
    # The sections that take chapters of this book and of another
    # (the Succession Narrative runs from 2 Samuel into 1 Kings): named
    # here, measured on their own Section page
    n_chapters_of = {b: atlas.book_info[b]["chapters"] for b in atlas.books}
    crossing = cross_sections_of_book(book, n_chapters_of)
    if crossing:
        sec = report.section(
            f"7x. Sections crossing the book's boundary [{book}]",
            ["section", "parts", "division"],
            note=f"Sections of CROSS_SECTIONS (atlas_sections.py) that take chapters of {book} and of another "
                 f"book, measured as one text on their own Section page (section {book}: <name>), where "
                 f"'the rest' is the books the division touches taken together less the section.")
        for group, division, name, parts in crossing:
            sec.add([name, parts_text(parts), f"{group}: {division}"],
                    link={"book": book, "chapter": next(chs[0] for b, chs in parts if b == book), "section": name})
    return report


def sections_section(atlas, report, title, book, info):
    """
    The section layer: the parts of a book listed in atlas_sections.py
    (the five books of the Psalter, then its collections and the
    Elohistic block; Ezekiel's four parts), each with its size and its
    leading words (keyness against the rest of the book), then the echo
    map and the within-book map summed to section scale, and the
    reach-and-depth chart with the section as its unit.  Runs from the
    cells sections 4 and 6 already computed.  The first division gets
    7, 7a, 7b, 7c; a second gets 7.2, 7.2a ...
    """
    # Words per chapter counted from the spaces of word_string, which is
    # stored with a space at each end, so the words are the spaces less
    # one.  Five of these counts added one instead until 0.10.65 and
    # ran two words per verse high (the Succession Narrative read
    # 15,210 words in section 7 and 14,306 in its header), which the
    # reviewer saw as two counts on one page that did not agree
    words_by_ch = {r[0]: r[1] for r in atlas.db.execute(
        "SELECT chapter, SUM(LENGTH(word_string) - LENGTH(REPLACE(word_string, ' ', '')) - 1) "
        "FROM verses WHERE book = ? GROUP BY chapter", (book,))}
    verses_by_ch = {r[0]: r[1] for r in atlas.db.execute(
        "SELECT chapter, COUNT(*) FROM verses WHERE book = ? GROUP BY chapter", (book,))}
    # Word weights per chapter, for keyness of a section against the rest of the book
    weight = {}                      # root -> {chapter: weight}
    for root, ch, w in atlas.db.execute(
            "SELECT root, chapter, weight FROM word_chapter WHERE book = ?", (book,)):
        weight.setdefault(root, {})[ch] = w
    book_words = sum(words_by_ch.values())
    number = title.split(".")[0]
    # A book in two languages (Daniel) measures each root against the
    # rest of the book in the root's own language: "against the rest of
    # the book" is otherwise a language test, and the visions' leading
    # words came out as the commonest Hebrew words of a half-Aramaic
    # book.  Word counts per chapter and language, from the verse
    # languages stored at build; a root is Aramaic when the lexicon
    # marks it so, Hebrew otherwise.  Where the rest of the book holds
    # under FEW_WORDS words of the root's language (the Language division
    # itself), the root is measured against the rest of its testament
    bilingual = len(atlas.languages_of(book)) > 1
    aramaic = atlas.aramaic_roots() if bilingual else set()
    lang_words_by_ch = {}            # (chapter, language) -> words
    if bilingual:
        for ch, lang, n in atlas.db.execute(
                "SELECT chapter, language, SUM(LENGTH(word_string) - LENGTH(REPLACE(word_string, ' ', '')) - 1) "
                "FROM verses WHERE book = ? GROUP BY chapter, language", (book,)):
            lang_words_by_ch[(ch, lang)] = n

    for d_index, (division, secs) in enumerate(divisions_of(book, info["chapters"])):
        prefix = number if d_index == 0 else f"{number}.{d_index + 1}"
        names = [name for name, chs, rest in secs]
        chapters_of = {name: list(chs) for name, chs, rest in secs}
        sec_words = {name: sum(words_by_ch.get(c, 0) for c in chapters_of[name]) for name in names}
        firsts = {name: chs[0] for name, chs, rest in secs}
        # A section under FEW_WORDS words prints 'few' beside its name:
        # per-1,000 scaling amplifies a 446-word psalm into a partner of
        # everything, as 4a's 'few' warns for small partner books
        shown_name = {name: (f"{name} (few)" if sec_words[name] < FEW_WORDS else name) for name in names}

        sec = report.section(
            f"{prefix}. Sections [{book}]: {division}",
            ["section", "chapters", "verses", "words", "leading words (count in N of M chapters, keyness against the rest of the book)"],
            note=f"The parts of {book} by the '{division}' division in atlas_sections.py (edit that file to "
                 f"change them).  Leading words are the words most key to the section against the rest "
                 f"of the book, up to six, each at keyness {GROUP_KEYNESS_FLOOR} or above (a shorter list "
                 f"means the section has fewer words of its own, not that it was cut) and with at least "
                 f"{HOME_MIN_WEIGHT} occurrences, or one per {WORDS_PER_OCCURRENCE} words of a short section "
                 f"down to {SHORT_BOOK_MIN_WEIGHT}; 'in N of M chapters' says whether "
                 f"the word is the section's voice or one chapter's (Psalm 119 gives Book V its "
                 f"commandments, precepts and statutes).  A division that leaves chapters out gets a "
                 f"'Rest of {book}' row holding them.  A section under {FEW_WORDS} words is marked 'few': "
                 f"read its rows lightly.  Double-click a row for its first chapter; the section's own "
                 f"page is [{book}: section name] in the ask box."
                 + (f"  {book} is in two languages, so each word is measured against the rest of the "
                    f"book in its own language (an Aramaic root against the book's other Aramaic, a "
                    f"Hebrew one against its Hebrew); where the rest of the book holds under {FEW_WORDS} "
                    f"words of that language, against the rest of the testament instead."
                    if bilingual else ""))
        for name, chs, is_rest in secs:
            n_words = sec_words[name]
            rest = book_words - n_words
            in_chs = set(chs)
            scored = []
            floor = occurrence_floor(n_words)
            for root, by_ch in weight.items():
                in_sec = {c: w for c, w in by_ch.items() if c in in_chs}
                a = sum(in_sec.values())
                if a < floor:
                    continue
                b = sum(by_ch.values()) - a
                n1, n2 = n_words, rest
                if bilingual:
                    lang = "Aramaic" if root in aramaic else "Hebrew"
                    n1 = sum(lang_words_by_ch.get((c, lang), 0) for c in in_chs)
                    n2 = sum(n for (c, l), n in lang_words_by_ch.items() if l == lang and c not in in_chs)
                    if n2 < FEW_WORDS:
                        # no rest of the book in this language: the testament instead
                        row = atlas.word_row(root)
                        b = (row["weight"] if row else a) - a
                        n2 = atlas.comparison_words(root) - n1
                k = log_likelihood(a, b, n1, n2) if n2 > 0 and n1 > 0 else 0
                # The same floor as 1b: a word at keyness 0 is used at
                # the rest of the book's rate, and printing it because
                # the column fills to six ("jesus (5 in 2/2, 0)" on
                # Galatians' ethics) made it look like a leading word.
                # The list simply ends early
                if k >= GROUP_KEYNESS_FLOOR:
                    scored.append((k, root, a, len(in_sec)))
            scored.sort(key=lambda t: -t[0])
            leading = ", ".join(f"{atlas.form(r)} ({a} in {n}/{len(chs)}, {k:.0f})" for k, r, a, n in scored[:6])
            sec.add([shown_name[name], span_text(chs), sum(verses_by_ch.get(c, 0) for c in chs), n_words,
                     leading or "-"],
                    link={"book": book, "chapter": firsts[name], "section": name})

        # a. The echo map at section scale
        cells = getattr(report, "echo_cells", None)
        partners = getattr(report, "echo_partners", None)
        if cells and partners:
            heat = report.section(
                f"{prefix}a. Echo map by section [{book}] -> partner books",
                ["section"] + partners,
                note=f"Section 4c summed to sections: each cell the weight of the echoes between that part "
                     f"of the book and that partner, per 1,000 words of the part, so a long section does "
                     f"not outweigh a short one.  A section under {SMALL_WORDS} words is marked 'small': "
                     f"the scaling magnifies whatever it touches, so read its row lightly.  Double-click a "
                     f"row for the section's first chapter."
                     + ("  On a Gospel, a row where Matthew and Mark run level is the triple tradition and "
                        "says nothing about which is the source; the row where Matthew stands high and "
                        "Mark low is the double tradition (Q), and it is the diagnostic one.  The Compare "
                        "page's order lines and Mark's sharing table carry the argument for Mark's priority."
                        if book in GOSPELS else "")
                     + ("  This book is in two languages.  A row of Aramaic chapters shares no root with "
                        "a Hebrew partner, so its echoes with the Hebrew books are found by English "
                        "wording (marked 'by English' in section 4), as echoes across the testaments are."
                        if len(atlas.languages_of(book)) > 1 else ""),
                kind="heatmap")
            heat.value_label = "echo weight per 1000 words"
            for name, chs, is_rest in secs:
                n_words = sec_words[name] or 1
                # a short section's per-1,000 figures magnify whatever it
                # touches (Matthew 1 to 4 on Revelation), so it is marked
                label = shown_name[name]
                if FEW_WORDS <= n_words < SMALL_WORDS:
                    label += " (small)"
                row = [label]
                for pb in partners:
                    total = sum(sum(cells.get((c, pb), {}).values()) for c in chapters_of[name])
                    row.append(round(1000 * total / n_words))
                heat.add(row, link={"book": book, "chapter": firsts[name], "section": name})

        # b. The book against itself at section scale
        within = getattr(report, "within_cells", None)
        if within and len(secs) > 1:
            heat = report.section(
                f"{prefix}b. Section against section [{book}]",
                ["section"] + [shown_name[n] for n in names],
                note="Section 6 summed to sections: each cell the shared rare phrasing between two parts "
                     "of the book (summed rarity, per 1,000 words of the two parts together).  The "
                     "diagonal is a part against itself, its own internal repetition; a two-chapter "
                     "part's diagonal is a single chapter pair, and a one-chapter part's is always 0.  "
                     "A low cell between two parts says they share little phrasing, which a change of "
                     "subject produces as surely as a change of hand (2 Corinthians' collection shares "
                     "3 and 4 with its neighbours and nobody takes it for a separate letter), so the "
                     "cell is evidence about a seam only beside the vocabulary that no subject drives.",
                kind="heatmap")
            heat.value_label = "shared weight per 1000 words"
            for name_a, chs_a, rest_a in secs:
                row = [shown_name[name_a]]
                for name_b, chs_b, rest_b in secs:
                    total = 0
                    for ca in chapters_of[name_a]:
                        for cb in chapters_of[name_b]:
                            if ca < cb:
                                total += within.get((ca, cb), 0)
                            elif ca > cb:
                                total += within.get((cb, ca), 0)
                    n_words = (sec_words[name_a] + (sec_words[name_b] if name_a != name_b else 0)) or 1
                    row.append(round(1000 * total / n_words))
                heat.add(row, link={"book": book, "chapter": firsts[name_a], "section": name_a})

        # c. Reach and depth with the section as the unit
        if len(secs) > 1:
            reach_depth_by_section(atlas, report, f"{prefix}c. Reach and depth by section [{book}]",
                                   book, secs, sec_words)
        # d. The function words by section (atlas_function.py): the
        # question 7b cannot answer, whether the hand changed
        if len(secs) > 1:
            function_section_table(atlas, report, f"{prefix}d. Function words by section [{book}]",
                                   book, secs, chapters_of, shown_name, firsts)


def reach_depth_by_section(atlas, report, title, book, secs, sec_words):
    """
    The reach-and-depth chart of section 5 with the section, not the
    chapter, as the unit: reach is the share of the book's sections a
    word occurs in, depth the highest keyness it reaches in one section
    against the rest of its testament, and 'deepest at' that section.
    A word deep in one section and absent from the rest is one part's
    own vocabulary (cubits in the temple vision); a word wide and deep
    belongs to the whole book.
    """
    sec = report.section(
        title, ["word", "reach", "depth", "deepest at", "depth/1000", "deepest/1000 at", "count", "keyness"],
        note=f"The {REACH_DEPTH_N} most key words of {book}, placed by reach (percent of the book's "
             f"{len(secs)} sections the word occurs in) against depth (the highest keyness it reaches "
             f"in one section, against the rest of its testament).  Top right: the whole book's words; "
             f"top left: one section's own.  Keyness grows with the size of the section, so a word "
             f"spread through the book is 'deepest at' its largest part; 'depth/1000' is the same "
             f"keyness per 1,000 words of the section, which removes the size and names the part "
             f"where the word is thickest for its length.  Double-click for the word's page.",
        kind="scatter")
    sec.x_column, sec.y_column = "reach", "depth"
    top = atlas.db.execute(
        "SELECT root, weight, keyness FROM word_book WHERE book = ? AND weight >= 3 "
        "ORDER BY keyness DESC LIMIT ?", (book, REACH_DEPTH_N)).fetchall()
    for r in top:
        root = r["root"]
        by_ch = {c: w for c, w in atlas.db.execute(
            "SELECT chapter, weight FROM word_chapter WHERE book = ? AND root = ?", (book, root))}
        total = atlas.word_row(root)
        total_weight = total["weight"] if total else sum(by_ch.values())
        n_compare = atlas.comparison_words(root)
        best, best_name, reached = 0.0, "-", 0
        best_rate, best_rate_name = 0.0, "-"
        for name, chs, is_rest in secs:
            in_chs = set(chs)
            a = sum(w for c, w in by_ch.items() if c in in_chs)
            if a == 0:
                continue
            reached += 1
            n1 = sec_words[name]
            k = log_likelihood(a, total_weight - a, n1, n_compare - n1)
            if k > best:
                best, best_name = k, name
            rate = 1000 * k / n1 if n1 else 0
            if rate > best_rate:
                best_rate, best_rate_name = rate, name
        reach = round(100 * reached / len(secs))
        sec.add([atlas.form(root), reach, round(best, 1), best_name, round(best_rate, 1), best_rate_name,
                 r["weight"], round(r["keyness"], 1)],
                link={"word": root, "book": book})


def section_page(atlas, book_name, section_name):
    """
    The page of one section of a book (Book II of the Psalter, Ezekiel's
    temple vision): the book page's sections run over the section's
    chapters alone.  Signature words against the rest of the testament,
    formulas, echoes with the map and chapter table, the section
    against itself, and its kin at the head.  The section is named as
    atlas_sections.py names it.
    """
    # A cross-book section is asked for by its group ("Samuel and Kings:
    # The Succession Narrative") or by any book it takes ("2 Samuel: The
    # Succession Narrative"); the group is not a book
    if is_cross_group(book_name):
        return cross_section_page(atlas, section_name, book_name)
    book = atlas.find_book(book_name)
    n_chapters = atlas.book_info[book]["chapters"]
    hit = find_section(book, section_name, n_chapters)
    if hit is None:
        n_chapters_of = {b: atlas.book_info[b]["chapters"] for b in atlas.books}
        if find_cross_section(section_name, n_chapters_of) is not None:
            return cross_section_page(atlas, section_name)
        names = ", ".join(sec[0] for d, secs in divisions_of(book, n_chapters) for sec in secs)
        crossing = ", ".join(n for g, d, n, p in cross_sections_of_book(book, n_chapters_of))
        raise ValueError(f"{book} has no section '{section_name}'"
                         + (f"; its sections are: {names}" if names else "; it has no sections in atlas_sections.py")
                         + (f"; and across its boundary: {crossing}." if crossing else "."))
    division, (name, chapters, is_rest) = hit
    in_chs = set(chapters)
    first, last = chapters[0], chapters[-1]
    verses = [v for v in atlas.verses_of(book) if v["chapter"] in in_chs]
    atlas.use_scope(book)
    n_scope = sum(len(v["word_string"].split()) for v in verses)
    label = f"{book}: {name}"
    report = Report(f"section_{book.lower().replace(' ', '_')}_{first}_{last}",
                    f"Section page [{label}] ({atlas.settings['translation']})")
    report.notes.append(f"{label} ({division}), chapters {span_text(chapters)}: {len(verses)} verses, "
                        f"{n_scope} words; the rest of {book}: "
                        f"{atlas.book_info[book]['words'] - n_scope} words.")

    # Signature words: the section's counts summed from word_chapter,
    # keyness against the rest of the testament (as a book's is)
    counts, chapters_hit = Counter(), {}
    for root, ch, w in atlas.db.execute(
            "SELECT root, chapter, weight FROM word_chapter WHERE book = ? AND chapter IN ("
            + ",".join("?" * len(chapters)) + ")", (book, *chapters)):
        counts[root] += w
        chapters_hit.setdefault(root, set()).add(ch)
    scored = []
    for root, a in counts.items():
        if a < 2:
            continue
        row = atlas.word_row(root)
        total = row["weight"] if row else a
        n_compare = atlas.comparison_words(root)
        k = log_likelihood(a, total - a, n_scope, n_compare - n_scope)
        scored.append((root, a, len(chapters_hit[root]), k))
    scored.sort(key=lambda t: -t[3])
    rows = scored[:TOP_N]
    top = signature_words_section(atlas, report, f"1. Signature words [{label}]", rows,
                                  n_scope, "section", book, None, len(chapters))

    signature_formulas_section(atlas, report, f"2. Signature formulas [{label}]", verses, book, n_scope)

    testament = atlas.book_info[book]["testament"]
    focus = [atlas.root_of(w, testament) for w in FOCUS_WORDS]
    focus += [r for r in top[:3] if r not in focus]
    for i, root in enumerate(focus):
        neighbors_section(atlas, report, f"3.{i + 1} Neighbors of '{atlas.form(root)}' [{book}] (book scale)",
                        book, root, atlas.forms.get(root, root), book)
    report.sections[-len(focus)].note = ("Neighbors is stored at book and Bible scale, so the left "
                                         "column is the whole book.  " + report.sections[-len(focus)].note)

    echoes_section(atlas, report, f"4. Echoes [{label}] -> other books", book, chapters,
                   scope_name=label, date=section_date(book, name))
    far = "Greek Old Testament" if atlas.book_info[book]["testament"] == "New" else "New Testament, in Greek"
    septuagint_echoes_section(atlas, report, f"4e. Septuagint echoes [{label}] -> {far}", book, chapters)
    if len(chapters) > 1:
        within_book_section(atlas, report, f"6. Echoes within [{label}]: chapter against chapter",
                            book, chapter_range=chapters)
        kin_within_section(atlas, report, f"6c. Kin within [{label}]: chapters sharing rare words in any order",
                           book, chapter_range=chapters)
        shared_vocabulary_section(atlas, report, f"6d. Shared vocabulary [{label}]: chapters drawing on the same uncommon words",
                                  book, chapter_range=chapters)
    return report


def cross_section_page(atlas, name, group=None):
    """
    The page of a section that crosses a book boundary (the Succession
    Narrative, 2 Samuel 9 to 20 with 1 Kings 1 to 2), from CROSS_SECTIONS
    in atlas_sections.py.  Its verses from every book it takes are one
    text: signature words against the testament, the words behind
    them, formulas, echoes (partners outside the books the section
    touches), the Septuagint echoes of each part, and then the
    division's tables at section scale, where "the rest" is the books
    the division touches taken together less the section: the leading
    words of each section against that rest, and the function-word
    profile with its Delta from that rest.  The book-against-itself
    tables (6, 6c, 6d) stay on the pages of the books themselves.
    """
    n_chapters_of = {b: atlas.book_info[b]["chapters"] for b in atlas.books}
    hit = find_cross_section(name, n_chapters_of, group)
    if hit is None:
        names = ", ".join(sec[0] for g, d, t, secs in cross_divisions(n_chapters_of) for sec in secs if not sec[2])
        raise ValueError(f"No cross-book section named '{name}'; the cross-book sections are: {names}.")
    group, division, touched, (name, parts, is_rest) = hit
    secs = next(secs for g, d, t, secs in cross_divisions(n_chapters_of) if g == group and d == division)
    books = [b for b, chs in parts]
    verses = []
    for book, chs in parts:
        in_chs = set(chs)
        verses.extend(v for v in atlas.verses_of(book) if v["chapter"] in in_chs)
    atlas.use_scope(books[0])
    ids = [v["verse_id"] for v in verses]
    n_scope = sum(len(v["word_string"].split()) for v in verses)
    n_chapters = sum(len(chs) for b, chs in parts)
    rest_name = " and ".join(touched)
    n_touched = sum(atlas.book_info[b]["words"] for b in touched)
    label = f"{name}: {parts_text(parts)}"
    report = Report("section_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"),
                    f"Section page [{label}] ({atlas.settings['translation']})")
    report.notes.append(f"{name} ({group}: {division}), {parts_text(parts)}: {len(verses)} verses, "
                        f"{n_scope} words in {n_chapters} chapters.  The rest of {rest_name}: "
                        f"{n_touched - n_scope} words.")
    # A reader can reach this page without passing through a book page
    # (the section command lands them on it), and its numbering, 4e and
    # 4f per part, 7 and 7d for the division, is no more guessable than
    # the book page's, so the renderer lists its sections at the head
    report.list_sections = True
    report.notes.append(f"A section across a book boundary, from CROSS_SECTIONS in atlas_sections.py.  Its "
                        f"parts are measured as one text; where a table says 'the rest', it means the books "
                        f"the division touches ({rest_name}) taken together less the section, the frame the "
                        f"question about the section sets it against.  Echo partners are the books outside "
                        f"{' and '.join(books)}.  The book-against-itself tables (6, 6c, 6d) are on each "
                        f"book's own page.")

    top = verses_signature_section(atlas, report, f"1. Signature words [{label}]", verses, label, books,
                                   n_scope, n_chapters, "section")
    lexicon_section(atlas, report, f"1. Signature words [{label}]", top, books[0], None, "section")
    signature_formulas_section(atlas, report, f"2. Signature formulas [{label}]", verses, books[0], n_scope)
    if len(books) > 1:
        report.sections[-1].note += ("  The 'elsewhere' count leaves out the first book of the section "
                                     "only, so a formula shared by its books may be counted there.")
    echoes_section(atlas, report, f"4. Echoes [{label}] -> other books", books[0], None,
                   scope_name=label, verse_ids=ids, books=books)
    testament = atlas.book_info[books[0]]["testament"]
    far = "Greek Old Testament" if testament == "New" else "New Testament, in Greek"
    for book, chs in parts:
        septuagint_echoes_section(atlas, report, f"4e. Septuagint echoes [{name}: {book} {span_text(chs)}] -> {far}",
                                  book, chs)

    # 7. The division at section scale: every section of it, with its
    # leading words against the rest of the touched books
    words_by = {}                    # (book, chapter) -> words
    verses_by = {}
    for b in touched:
        for r in atlas.db.execute(
                "SELECT chapter, SUM(LENGTH(word_string) - LENGTH(REPLACE(word_string, ' ', '')) - 1), COUNT(*) "
                "FROM verses WHERE book = ? GROUP BY chapter", (b,)):
            words_by[(b, r[0])] = r[1]
            verses_by[(b, r[0])] = r[2]
    weight = {}                      # root -> {(book, chapter): weight}
    marks = ",".join("?" * len(touched))
    for root, b, ch, w in atlas.db.execute(
            f"SELECT root, book, chapter, weight FROM word_chapter WHERE book IN ({marks})", touched):
        weight.setdefault(root, {})[(b, ch)] = w
    total_words = sum(words_by.values())
    sec7 = report.section(
        f"7. Sections [{group}: {division}]",
        ["section", "chapters", "verses", "words",
         f"leading words (count in N of M chapters, keyness against the rest of {rest_name})"],
        note=f"The sections of the division '{division}' across {rest_name}, from CROSS_SECTIONS in "
             f"atlas_sections.py.  Leading words are the words most key to the section against the rest of "
             f"the touched books, up to six, each at keyness {GROUP_KEYNESS_FLOOR} or above, with the "
             f"occurrence floor 1b uses for a text of the section's size.  Double-click a row for the "
             f"section's first chapter.")
    for sname, sparts, srest in secs:
        own = {(b, c) for b, chs in sparts for c in chs}
        n_words = sum(words_by.get(bc, 0) for bc in own)
        rest = total_words - n_words
        floor = occurrence_floor(n_words)
        scored = []
        for root, by_bc in weight.items():
            in_sec = {bc: w for bc, w in by_bc.items() if bc in own}
            a = sum(in_sec.values())
            if a < floor:
                continue
            b = sum(by_bc.values()) - a
            k = log_likelihood(a, b, n_words, rest) if rest > 0 and n_words > 0 else 0
            if k >= GROUP_KEYNESS_FLOOR:
                scored.append((k, root, a, len(in_sec)))
        scored.sort(key=lambda t: (-t[0], t[1]))
        leading = ", ".join(f"{atlas.form(r)} ({a} in {n}/{len(own)}, {k:.0f})" for k, r, a, n in scored[:6])
        sec7.add([sname, parts_text(sparts), sum(verses_by.get(bc, 0) for bc in own), n_words, leading or "-"],
                 link={"book": sparts[0][0], "chapter": sparts[0][1][0]})
    # d. The function words by section, Delta from the rest of the touched books
    function_cross_section_table(atlas, report, f"7d. Function words by section [{group}: {division}]",
                                 touched, secs, rest_name)
    return report


def verses_signature_section(atlas, report, title, verses, label, books, n_scope, n_chapters, what):
    """
    Section 1 for any set of verses (a passage, a cross-book section):
    the text's tokens by root against the rest of the root's testament,
    as a book's are, with the verses holding each root kept for the
    click.  Returns the top roots.  what is the word the note uses for
    the text ("passage", "section").
    """
    ids = [v["verse_id"] for v in verses]
    refs_of = {v["verse_id"]: v["reference"] for v in verses}
    counts, held = Counter(), {}
    marks = ",".join("?" * len(ids))
    for vid, root in atlas.db.execute(
            f"SELECT verse_id, root FROM tokens WHERE verse_id IN ({marks}) AND is_stop = 0", ids):
        counts[root] += 1
        held.setdefault(root, []).append(refs_of[vid])
    scored = []
    for root, a in counts.items():
        if a < 2:
            continue
        w = atlas.word_row(root)
        total = w["weight"] if w else a
        n_compare = atlas.comparison_words(root)
        k = log_likelihood(a, total - a, n_scope, n_compare - n_scope)
        if k > 0:
            scored.append((k, root, a, total, n_compare))
    scored.sort(key=lambda t: (-t[0], t[1]))
    sec = report.section(
        title, ["word", "count", f"{what}/1000", "rest/1000", "chapters", "books", "keyness", "note"],
        note=f"The words far more common in the {what} than in the rest of the testament (or, for an "
             f"English stem, the Bible), ranked by keyness; at least two occurrences.  'chapters' is "
             f"how many of the {what}'s {n_chapters} chapters hold the word.  Click a row for the "
             f"{what}'s verses holding it; double-click for the word's page.")
    top = []
    for k, root, a, total, n_compare in scored[:TOP_N]:
        w = atlas.word_row(root)
        chs = len({r.rsplit(" ", 1)[0] + " " + r.rsplit(" ", 1)[1].split(":")[0] for r in held[root]})
        notes = []
        renderings = atlas.renderings(root)
        if renderings > 1:
            notes.append(f"{renderings} renderings")
        sec.add([atlas.form(root), a, per_thousand(a, n_scope), per_thousand(total, n_compare),
                 f"{chs}/{n_chapters}", f"{w['books_reached']}/{atlas.comparison_books(root)}" if w else "-",
                 round(k, 1), ", ".join(notes)],
                refs=list(dict.fromkeys(held[root])), link={"word": root, "book": books[0]})
        top.append(root)
    return top


def passage_page(atlas, name):
    """
    The page of a named passage from the catalogue (metadata.db): any
    set of verse ranges in any books, which is what the section layer
    cannot hold.  Signature words against the rest of the testament,
    the words behind them, formulas, and the echoes with the partner
    table and who reads whom; when the passage lies in one book, the
    chapter tables of the echoes as well.  A passage of whole chapters
    of one book is better served by a section (atlas_sections.py), which
    also gets the book-against-itself tables; this page is for the
    rest: a verse range, or a study across books.
    """
    verses = atlas.passage_verses(name)
    if not verses:
        known = ", ".join(atlas.passages()) or "(none: no metadata.db beside the scripts, or no passages in it)"
        raise ValueError(f"No passage named '{name}'.  Known passages: {known}.")
    key = next(k for k in atlas.passages() if k.lower() == name.lower())
    desc, ranges = atlas.passages()[key]
    books = []
    for book, *_ in ranges:
        if book not in books:
            books.append(book)
    books.sort(key=atlas.books.index)
    spans = []
    for book, c1, v1, c2, v2 in ranges:
        if v1 == 1 and v2 >= 999:
            spans.append(f"{book} {c1}" if c1 == c2 else f"{book} {c1}-{c2}")
        else:
            end = f"{c2}" if v2 >= 999 else f"{c2}:{v2}"
            spans.append(f"{book} {c1}:{v1}-{end}")
    label = f"Passage: {key}"
    atlas.use_scope(books[0])
    ids = [v["verse_id"] for v in verses]
    refs_of = {v["verse_id"]: v["reference"] for v in verses}
    n_scope = sum(len(v["word_string"].split()) for v in verses)
    chapters = sorted({(v["book"], v["chapter"]) for v in verses}, key=lambda bc: (atlas.books.index(bc[0]), bc[1]))
    report = Report("passage_" + re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_"),
                    f"Passage page [{key}] ({atlas.settings['translation']})")
    report.notes.append(f"{key}: {'; '.join(spans)}.  {len(verses)} verses, {n_scope} words, "
                        f"{len(chapters)} chapter{'s' if len(chapters) != 1 else ''} of "
                        + ", ".join(books) + "." + (f"  {desc}" if desc else ""))
    report.notes.append("A passage is any set of verse ranges in any books, kept in the catalogue "
                        "(metadata.db, atlas_passages.py) and measured here as one text.  Partners are "
                        "the books outside it, and the testament figures are those of the first book's "
                        "testament where the passage spans both.")

    top = verses_signature_section(atlas, report, f"1. Signature words [{label}]", verses, label, books,
                                   n_scope, len(chapters), "passage")
    lexicon_section(atlas, report, f"1. Signature words [{label}]", top, books[0], None, "passage")

    signature_formulas_section(atlas, report, f"2. Signature formulas [{label}]", verses, books[0], n_scope)
    if len(books) > 1:
        report.sections[-1].note += ("  The 'elsewhere' count leaves out the first book of the passage "
                                     "only, so a formula shared by its books may be counted there.")

    echoes_section(atlas, report, f"4. Echoes [{label}] -> other books", books[0], None,
                   scope_name=label, verse_ids=ids, books=books)
    return report


def phrase_places(atlas, verses, column):
    """
    Every phrase of three to five units in a set of verses, ending on a
    content word: key -> {chapter: [references]}, and key -> Counter of
    its English wordings.  column is phrase_string (root units) or
    word_string (English wording, used between the testaments).
    """
    places, wordings = {}, {}
    for v in verses:
        words = v["word_string"].split()
        units = v[column].split() if column != "word_string" else words
        stops = [w in STOPLIST for w in words]
        seen = set()
        for n in FORMULA_LENGTHS:
            if n < 3:
                continue
            for i in range(len(words) - n + 1):
                if stops[i + n - 1]:
                    continue
                key = " ".join(units[i:i + n])
                wordings.setdefault(key, Counter())[" ".join(words[i:i + n])] += 1
                if key in seen:
                    continue
                seen.add(key)
                places.setdefault(key, {}).setdefault(v["chapter"], []).append(v["reference"])
    return places, wordings


def drop_pieces(kept):
    """
    Of phrases keyed to (chapters, display), the shorter ones that sit
    inside a longer one with exactly the same verses: pieces of it, not
    phrases of their own.  Returns the set of keys to leave out.
    """
    groups = {}
    for key, (chapters, display) in sorted(kept.items()):
        vs = frozenset(r for refs in chapters.values() for r in refs)
        groups.setdefault(vs, []).append(key)
    pieces = set()
    for keys in groups.values():
        if len(keys) < 2:
            continue
        by_len = sorted(keys, key=lambda k: -len(k.split()))
        for i, longer in enumerate(by_len):
            lu = longer.split()
            for shorter in by_len[i + 1:]:
                su = shorter.split()
                if len(su) < len(lu) and any(lu[j:j + len(su)] == su for j in range(len(lu) - len(su) + 1)):
                    pieces.add(shorter)
    return pieces


def bridged_places(atlas, verses, book):
    """
    The English bridge inside a testament.  Phrases of three to five
    words of English wording found in verses of two different languages
    among the verses given (Daniel's Aramaic chapters against its Hebrew
    ones, or against Ezekiel): key "en:wording" -> {chapter:
    [references]}, and the wordings Counter the map expects.  Roots
    cannot match across languages, so these are the only phrases the
    two sides can share; a pair of chapters counts such a phrase only
    where the two chapters are in different languages (see the callers),
    and the root match covers the rest.
    """
    places, wordings = phrase_places(atlas, verses, "word_string")
    out, out_wordings = {}, {}
    for key, chapters in places.items():
        languages = {atlas.language_of(ref, book) for refs in chapters.values() for ref in refs}
        if len(languages) < 2:
            continue
        out["en:" + key] = chapters
        out_wordings["en:" + key] = wordings[key]
    return out, out_wordings


def cross_language(atlas, refs_a, refs_b, book_a=None, book_b=None):
    """True when some verse of refs_a and some verse of refs_b are in different languages."""
    la = {atlas.language_of(r, book_a) for r in refs_a}
    lb = {atlas.language_of(r, book_b) for r in refs_b}
    return any(x != y for x in la for y in lb)


def phrase_weight(atlas, key, column):
    """Summed rarity of a phrase's content words."""
    if column != "word_string":
        return sum(atlas.rarity(u) for u in atlas.content_units(key))
    return sum(atlas.rarity(atlas.root_of(w)) for w in key.split() if w not in STOPLIST)


def ref_order(r):
    """Sort key for a reference: chapter, then verse."""
    return (int(r.rsplit(" ", 1)[1].split(":")[0]), int(r.rsplit(":", 1)[1]))


def within_book_section(atlas, report, title, book, chapter_range=None):
    """
    The book against itself: a map of chapters by chapters, each cell
    the weight of the phrases the two chapters share and few other
    verses of the book have (at most WITHIN_MAX_VERSES).  Exodus 25 to 31
    against 35 to 40, the tabernacle prescribed and then built, shows
    as a band off the diagonal; Ezekiel 1 against 10; the Synoptic
    doublets.  Section 4 compares a book with other books; this one
    compares it with itself.
    """
    verses = atlas.verses_of(book)
    if chapter_range is not None:     # a section: only its chapters
        wanted = set(chapter_range)
        verses = [v for v in verses if v["chapter"] in wanted]
    by_roots = atlas.phrase_column != "word_string"
    places = {}                       # key -> {chapter: [refs]}
    wordings = {}                     # key -> English wording -> count
    for v in verses:
        words = v["word_string"].split()
        units = v[atlas.phrase_column].split() if by_roots else words
        stops = [w in STOPLIST for w in words]
        seen = set()
        for n in FORMULA_LENGTHS:
            if n < 3:
                continue
            for i in range(len(words) - n + 1):
                if stops[i + n - 1]:
                    continue
                key = " ".join(units[i:i + n])
                wordings.setdefault(key, Counter())[" ".join(words[i:i + n])] += 1
                if key in seen:
                    continue
                seen.add(key)
                places.setdefault(key, {}).setdefault(v["chapter"], []).append(v["reference"])
    # A book in two languages (Daniel, Ezra) is bridged by English
    # wording between them, as the testaments are: Daniel 7's "the four
    # winds of heaven" (Aramaic) meets 8:8 and 11:4 (Hebrew) that way
    # and no other
    bridged = by_roots and len(atlas.languages_of(book)) > 1
    if bridged:
        en_places, en_wordings = bridged_places(atlas, verses, book)
        places.update(en_places)
        wordings.update(en_wordings)
    # Keep phrases in two or more chapters and few verses, with substance
    kept = {}
    for key, chapters in places.items():
        total = sum(len(r) for r in chapters.values())
        if len(chapters) < 2 or total > WITHIN_MAX_VERSES:
            continue
        display = wordings[key].most_common(1)[0][0]
        if not has_substance(display):
            continue
        if key.startswith("en:"):
            display += " (by English)"
        kept[key] = (chapters, display)
    # A shorter phrase inside a longer one with the same verses is a
    # piece of it.  Only phrases with the same verse set can nest, so
    # they are grouped by verse set first.
    groups = {}
    for key, (chapters, display) in sorted(kept.items()):
        vs = frozenset(r for refs in chapters.values() for r in refs)
        groups.setdefault(vs, []).append(key)
    pieces = set()
    for keys in groups.values():
        if len(keys) < 2:
            continue
        by_len = sorted(keys, key=lambda k: -len(k.split()))
        for i, longer in enumerate(by_len):
            lu = longer.split()
            for shorter in by_len[i + 1:]:
                su = shorter.split()
                if len(su) < len(lu) and any(lu[j:j + len(su)] == su for j in range(len(lu) - len(su) + 1)):
                    pieces.add(shorter)
    chapters_all = sorted({v["chapter"] for v in verses})
    # Refrains: a phrase in REFRAIN_MIN_CHAPTERS or more chapters is the
    # book's own refrain ("weeping and gnashing of teeth", "Peter and
    # James and John"), not a pair; it would inflate many cells at once,
    # so it is listed on its own and kept out of the map
    refrains = {key: (chapters, display) for key, (chapters, display) in kept.items()
                if key not in pieces and len(chapters) >= REFRAIN_MIN_CHAPTERS}
    cell_weight = Counter()
    cell_refs = {}
    cell_best = {}                    # (a, b) -> (weight, display)
    cell_count = Counter()            # (a, b) -> shared phrases
    for key, (chapters, display) in sorted(kept.items()):
        if key in pieces or key in refrains:
            continue
        weight = sum(atlas.rarity(u) for u in atlas.content_units(key)) if by_roots else \
            sum(atlas.rarity(atlas.root_of(w)) for w in key.split() if w not in STOPLIST)
        chs = sorted(chapters)
        for x in range(len(chs)):
            for y in range(x + 1, len(chs)):
                a, b = chs[x], chs[y]
                # An English-bridged phrase counts only between chapters in
                # different languages; within one language the roots count it
                if key.startswith("en:") and not cross_language(atlas, chapters[a], chapters[b], book, book):
                    continue
                cell_weight[(a, b)] += weight
                cell_count[(a, b)] += 1
                cell_refs.setdefault((a, b), []).extend(chapters[a] + chapters[b])
                if weight > cell_best.get((a, b), (0, ""))[0]:
                    cell_best[(a, b)] = (weight, display)
    if not cell_weight:
        return
    if chapter_range is None:
        report.within_cells = cell_weight      # for the section layer (section 7)
    sec = report.section(
        title, ["chapter"] + [str(c) for c in chapters_all],
        note=f"The book against itself: chapters down and across, each cell the summed rarity of the "
             f"phrases (three or more words) the two chapters share and at most {WITHIN_MAX_VERSES} "
             f"verses of the book hold, so the book's own refrains do not fill the map.  A band off the "
             f"diagonal is a passage retold: the tabernacle prescribed in Exodus 25 to 31 and built in "
             f"35 to 40, Ezekiel's chariot in 1 and 10, a Gospel's doublets.  Click a cell for the verses "
             f"in both chapters; tick 'each column on its own scale' for the fainter pairs."
             + ("  This book is in two languages, and a Hebrew root never matches an Aramaic one, so "
                "between its Hebrew and Aramaic verses phrases are matched by English wording instead."
                if bridged else ""),
        kind="heatmap")
    sec.value_label = "shared weight"
    index = {c: i for i, c in enumerate(chapters_all)}
    for i, a in enumerate(chapters_all):
        row = [a]
        for j, b in enumerate(chapters_all):
            if a == b:
                row.append(0)
                continue
            pair = (min(a, b), max(a, b))
            row.append(round(cell_weight.get(pair, 0)))
            refs = cell_refs.get(pair)
            if refs:
                sec.cell_refs[(i, j + 1)] = sorted(set(refs), key=lambda r: (int(r.rsplit(" ", 1)[1].split(":")[0]), int(r.rsplit(":", 1)[1])))
        sec.add(row, link={"book": book, "chapter": a})
    strongest = sorted(cell_weight.items(), key=lambda kv: -kv[1])[:WITHIN_PAIRS_N]
    sec.footer.append("Strongest pairs: " + "; ".join(
        f"{a} and {b} ({round(w)}, {cell_count[(a, b)]} phrases: \"{cell_best[(a, b)][1]}\")"
        for (a, b), w in strongest) + ".")

    # Chapter to chapter: each chapter's strongest partner in the book,
    # so the mirror (Exodus 25 to 37, 26 to 36 ...) and the plague block
    # can be read down a list rather than off a forty-by-forty grid
    pairs = report.section(
        title.split(".")[0] + f"a. Chapter to chapter [{book}]: each chapter's closest partner in the book",
        ["chapter", "partner", "gap", "kind", "weight", "phrases", "strongest shared phrase", "second partner"],
        note="For each chapter, the chapter of the same book it shares the most rare phrasing with "
             "(weight = summed rarity of the shared phrases, phrases = how many they share), the "
             "phrase that weighs most, and the next partner.  'gap' is the distance between the two; "
             f"neighbours share phrasing because the story continues ('adjacent'), a chapter one "
             f"removed may be either ('near'), chapters {DOUBLET_GAP} or more apart because the "
             f"author repeated himself ('doublet?').  "
             "Refrains (phrases in three or more chapters) are set aside and listed below.  Click "
             "a row for the verses on both sides; double-click for the chapter's page.")
    for a in chapters_all:
        partners = sorted(((b, cell_weight[(min(a, b), max(a, b))]) for b in chapters_all
                           if b != a and cell_weight.get((min(a, b), max(a, b)))),
                          key=lambda bw: -bw[1])
        if not partners:
            pairs.add([a, "-", "", "", "", "", "", ""], link={"book": book, "chapter": a})
            continue
        b, w = partners[0]
        key = (min(a, b), max(a, b))
        gap = abs(a - b)
        kind = "doublet?" if gap >= DOUBLET_GAP else ("adjacent" if gap == 1 else "near")
        second = f"{partners[1][0]} ({round(partners[1][1])})" if len(partners) > 1 else "-"
        pairs.add([a, b, gap, kind, round(w), cell_count[key], cell_best[key][1], second],
                  refs=sorted(set(cell_refs[key]), key=ref_order),
                  link={"book": book, "chapter": a})

    # The refrains, on their own
    if refrains:
        # With a section table for the book, a refrain is tested against
        # the seams: "amen and amen" at 41:13, 72:19 and 89:52 closes
        # Books I, II and III of the Psalter
        closing, opening = seam_chapters(book)
        main_secs = sections_of(book, None, atlas.book_info[book]["chapters"])
        has_seams = bool(closing)
        ref_sec = report.section(
            title.split(".")[0] + f"b. Refrains [{book}]: phrases in {REFRAIN_MIN_CHAPTERS} or more chapters",
            ["refrain", "chapters", "verses", "note"] + (["at the seams", "sections"] if has_seams else []),
            note="Phrases of three or more words that recur in three or more chapters of the book, "
                 "rarest first: the book's own refrains, set aside from the map above so they do "
                 "not inflate many cells at once.  Forms that differ only by stop words are one "
                 "refrain, shown in the form with the most verses.  'names' marks a refrain most of "
                 "whose content words are names of people or places (Baruch the son of Neriah), a cast "
                 "list rather than a formula; the names of God do not count, so 'ah Lord GOD' stays a "
                 "formula.  (The Compare page's maps use a "
                 "stricter rule between books, three chapters and four verses, so a refrain here may "
                 "still count there.)  Click for the verses."
                 + ("  'at the seams' counts the refrain's chapters that close or open a section of "
                    "the book (see section 7): a refrain found only there marks the book's divisions.  "
                    "'sections' says whether the refrain stays inside one section ('all in Second "
                    "Isaiah') or spans several: a refrain that never crosses a proposed seam is "
                    "evidence for the seam, and one that does marks a chapter the division must explain."
                    if has_seams else ""))
        # Refrains that differ only by stop words ("james and john", "and
        # james and john"; "an unclean spirit", "the unclean spirits", one
        # root each) are one refrain: the form with the most verses is
        # listed and the rest fold into it.  "Peter and James and John"
        # keeps its own row, since Peter is a further content root
        folded = {}                   # content roots -> key with the most verses
        for key, (chapters, display) in refrains.items():
            content = atlas.content_units(key) if by_roots else \
                tuple(w for w in key.split() if w not in STOPLIST)
            n_verses = sum(len(refs) for refs in chapters.values())
            if content not in folded or n_verses > folded[content][0]:
                folded[content] = (n_verses, key)
        rows = []
        for content, (n_verses, key) in folded.items():
            chapters, display = refrains[key]
            weight = sum(atlas.rarity(u) for u in content)
            refs = [r for c in sorted(chapters) for r in chapters[c]]
            rows.append((weight, display, ", ".join(str(c) for c in sorted(chapters)), len(refs), refs, key))
        rows.sort(key=lambda r: -r[0])
        # The rarest TOP_N refrains, and beyond them any refrain that
        # stays inside one section of the book: those are what the
        # 'sections' column is for, and a frame made of common words
        # ("in those days there was no king in Israel", Judges 17 to 21)
        # would otherwise fall under the cap for its low rarity
        shown = rows[:TOP_N]
        passed_over = 0
        if has_seams:
            for row in rows[TOP_N:]:
                chapters_of = [int(c) for c in row[2].split(", ")]
                in_secs = {sname for c in chapters_of for sname, schs, srest in main_secs if c in schs}
                if len(in_secs) == 1:
                    shown.append(row)
                else:
                    passed_over += 1
        else:
            passed_over = len(rows) - len(shown)
        if passed_over:
            ref_sec.footer.append(
                f"{passed_over} more refrain{'s' if passed_over != 1 else ''} of commoner words not shown"
                + (" (a refrain confined to one section is always shown)." if has_seams else "."))
        for weight, display, chs, n, refs, key in shown:
            content = atlas.content_units(key) if by_roots else \
                tuple(atlas.root_of(w) for w in key.split() if w not in STOPLIST)
            # "names" when more than half the content words are proper names:
            # "baruch the son of neriah" (son is content) is a cast-list entry
            # The divine names are proper nouns to the text but formulas to
            # the reader ("ah Lord GOD", "the LORD God of hosts"), so they
            # do not count toward the cast list
            people = [u for u in content if u not in DIVINE_ROOTS]
            n_names = sum(1 for u in people if atlas.is_name(u))
            mostly_names = bool(people) and n_names * 2 > len(people)
            row = [display, chs, n, "names" if mostly_names else ""]
            if has_seams:
                chapters_of = [int(c) for c in chs.split(", ")]
                closes = [c for c in chapters_of if c in closing]
                opens = [c for c in chapters_of if c in opening]
                at = []
                if closes:
                    at.append(f"{len(closes)} of {len(chapters_of)} close a section")
                if opens:
                    at.append(f"{len(opens)} of {len(chapters_of)} open one")
                row.append("; ".join(at) if at else "")
                # Which sections of the main division the refrain's chapters fall in
                in_secs = []
                for c in chapters_of:
                    for sname, schs, srest in main_secs:
                        if c in schs and sname not in in_secs:
                            in_secs.append(sname)
                if len(in_secs) == 1:
                    row.append(f"all in {in_secs[0]}")
                else:
                    row.append(f"spans {len(in_secs)}: " + ", ".join(in_secs))
            ref_sec.add(row, refs=refs, link={"phrase": display, "key": key})


def kin_within_section(atlas, report, title, book, chapter_range=None):
    """
    The book against itself by rare words in any order: the kin test of
    the Kin page run between the chapters of one book.  The phrase map
    (section 6) catches verbatim repetition, which in Genesis is the
    priestly formulas; a verse reworked in other words shares its rare
    words and not its phrasing, and this is the table that finds it.
    Two verses of different chapters are kin when they share
    KIN_MIN_SHARED rare words; a chapter pair scores the sum of its kin
    verse pairs.  A word set that recurs in REFRAIN_MIN_CHAPTERS or more
    chapter pairs is a kin refrain (the regnal frame of Kings, "rest,
    written, book" with the king's name between) and is set aside and
    named in a footer, as 6b does for phrases, so it does not fill the
    table.  One row per chapter with its closest partner, as in 6a, and
    the strongest pairs in a footer.
    """
    threshold = math.log(2000)
    sql = ("SELECT t.verse_id, v.chapter, v.reference, t.root FROM tokens t JOIN verses v USING (verse_id) "
           "WHERE v.book = ? AND t.is_stop = 0")
    params = [book]
    if chapter_range is not None:
        sql += " AND v.chapter IN (" + ",".join("?" * len(chapter_range)) + ")"
        params += list(chapter_range)
    sql += " ORDER BY t.verse_id, t.position"
    roots_of, order_of, ref_of, chapter_of = {}, {}, {}, {}
    holders = {}
    strongs = atlas.roots_mode == "strongs"
    for verse_id, chapter, reference, root in atlas.db.execute(sql, params):
        if atlas.rarity(root) < threshold or (strongs and not is_strongs(root)):
            continue
        roots_of.setdefault(verse_id, set()).add(root)
        order_of.setdefault(verse_id, []).append(root)
        ref_of[verse_id] = reference
        chapter_of[verse_id] = chapter
        holders.setdefault(root, set()).add(verse_id)
    pairs = {}
    for root, ids in holders.items():
        ids = sorted(ids)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if chapter_of[a] != chapter_of[b]:
                    pairs.setdefault((a, b), set()).add(root)
    kin_pairs = {k: s for k, s in pairs.items() if len(s) >= KIN_MIN_SHARED}

    # Kin refrains: a shared word set standing behind three or more
    # chapter pairs is the book's own frame, not a relation between two
    # chapters; a pair whose words include such a set is set aside
    by_set = {}
    for (a, b), shared in kin_pairs.items():
        by_set.setdefault(frozenset(shared), set()).add((chapter_of[a], chapter_of[b]))
    refrain_sets = [s for s, chs in by_set.items() if len(chs) >= REFRAIN_MIN_CHAPTERS]
    refrain_sets.sort(key=lambda s: (-len(by_set[s]), sorted(s)))
    # keep the smallest sets, so a superset does not count twice
    refrain_sets = [s for s in refrain_sets if not any(t < s for t in refrain_sets)]

    def is_refrain(shared):
        return any(s <= shared for s in refrain_sets)

    def in_order(a, b, shared):
        a = [r for i, r in enumerate(a) if r in shared and r not in a[:i]]
        b = [r for i, r in enumerate(b) if r in shared and r not in b[:i]]
        table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
        for i in range(1, len(a) + 1):
            for j in range(1, len(b) + 1):
                table[i][j] = table[i - 1][j - 1] + 1 if a[i - 1] == b[j - 1] else max(table[i - 1][j], table[i][j - 1])
        return table[len(a)][len(b)]

    cell_score, cell_best, cell_refs, cell_count = Counter(), {}, {}, Counter()
    refrain_pairs = Counter()
    for (a, b), shared in sorted(kin_pairs.items()):
        key = (chapter_of[a], chapter_of[b])
        if is_refrain(shared):
            refrain_pairs[key] += 1
            continue
        order = in_order(order_of[a], order_of[b], shared)
        score = sum(atlas.rarity(r) for r in shared) * (1 + 0.5 * order / len(shared))
        cell_score[key] += score
        cell_count[key] += 1
        cell_refs.setdefault(key, []).extend([ref_of[a], ref_of[b]])
        if score > cell_best.get(key, (0,))[0]:
            cell_best[key] = (score, a, b, shared)
    if not cell_score:
        return
    chapters_all = sorted(set(chapter_of.values()))
    sec = report.section(
        title, ["chapter", "partner", "gap", "score", "kin verses", "strongest pair", "{words shared}", "second partner"],
        note=f"The book against itself by rare words in any order, the Kin test between the chapters "
             f"of one book: two verses of different chapters are kin when they share {KIN_MIN_SHARED} or "
             f"more rare words (1 in 2,000 across the Bible), scored by their summed rarity and raised "
             f"by up to half when the words come in the same order; a chapter pair scores the sum of its "
             f"kin verse pairs.  Section 6 catches the same words in the same order; this catches a verse "
             f"reworked, or a formula with a name in the middle.  A word set behind "
             f"{REFRAIN_MIN_CHAPTERS} or more chapter pairs is a kin refrain, the book's frame rather than "
             f"a relation, and is set aside (footer).  One row per chapter with its closest partner; a "
             f"dash means no kin.  Click a row for the kin verses on both sides; double-click for the "
             f"chapter's page.")
    for c in chapters_all:
        partners = sorted(((o, cell_score[(min(c, o), max(c, o))]) for o in chapters_all
                           if o != c and cell_score.get((min(c, o), max(c, o)))), key=lambda ow: (-ow[1], ow[0]))
        if not partners:
            sec.add([c, "-", "", "", "", "", "", ""], link={"book": book, "chapter": c})
            continue
        o, total = partners[0]
        key = (min(c, o), max(c, o))
        score, a, b, shared = cell_best[key]
        seq = order_of[a]
        words = ", ".join(atlas.form(r) for i, r in enumerate(seq) if r in shared and r not in seq[:i])
        second = f"{partners[1][0]} ({round(partners[1][1])})" if len(partners) > 1 else "-"
        sec.add([c, o, abs(c - o), round(total, 1), cell_count[key], f"{ref_of[a]} / {ref_of[b]}", words, second],
                refs=sorted(set(cell_refs[key]), key=atlas.ref_key), link={"book": book, "chapter": c})
    strongest = sorted(cell_score.items(), key=lambda kv: (-kv[1], kv[0]))[:WITHIN_PAIRS_N]
    sec.footer.append("Strongest pairs: " + "; ".join(
        f"{a} and {b} ({round(w)}, {cell_count[(a, b)]} kin verses: "
        + ", ".join(atlas.form(r) for r in sorted(cell_best[(a, b)][3])[:4]) + ")"
        for (a, b), w in strongest) + ".")
    if refrain_sets:
        shown = []
        for s in refrain_sets[:8]:
            chs = sorted({c for pair in by_set[s] for c in pair})
            shown.append("{" + ", ".join(atlas.form(r) for r in sorted(s)) + "} in chapters "
                         + ", ".join(str(c) for c in chs))
        sec.footer.append(f"Kin refrains set aside ({sum(refrain_pairs.values())} verse pairs): "
                          + "; ".join(shown) + (f"; and {len(refrain_sets) - 8} more" if len(refrain_sets) > 8 else "") + ".")


def shared_vocabulary_section(atlas, report, title, book, chapter_range=None):
    """
    The book against itself by vocabulary: chapter pairs sharing words
    that few chapters of the book use at all, whether or not the same
    verse holds several of them.  The kin test (6c) wants three rare
    words in one verse pair, which a story told at length in two
    chapters may never give (Beersheba named in Genesis 21 and 26: well,
    digged, feast, Abimelech, Phichol, spread over the chapters).  Here
    a word in at most VOCAB_MAX_CHAPTERS chapters of the book, and not
    common in the Bible, scores each pair of those chapters by how few
    chapters hold it; names count, since in narrative they are the
    thread.  What neither table can find is a story retold in common
    words (the wife-sister story of 12, 20 and 26 shares sister, wife
    and took, which every chapter has); that needs a reader.
    """
    sql = ("SELECT v.chapter, t.root FROM tokens t JOIN verses v USING (verse_id) "
           "WHERE v.book = ? AND t.is_stop = 0")
    params = [book]
    if chapter_range is not None:
        sql += " AND v.chapter IN (" + ",".join("?" * len(chapter_range)) + ")"
        params += list(chapter_range)
    holders = {}
    chapters_seen = set()
    for chapter, root in atlas.db.execute(sql, params):
        holders.setdefault(root, set()).add(chapter)
        chapters_seen.add(chapter)
    n_ch = len(chapters_seen)
    if n_ch < 3:
        return
    floor = math.log(VOCAB_MIN_RARITY)
    score, words = Counter(), {}
    strongs = atlas.roots_mode == "strongs"
    for root, chs in holders.items():
        if len(chs) < 2 or len(chs) > VOCAB_MAX_CHAPTERS or atlas.rarity(root) < floor:
            continue
        if strongs and not is_strongs(root):
            continue            # an untagged stem ("wouldest", "except") is grammar, not vocabulary
        w = math.log(n_ch / len(chs))
        chs = sorted(chs)
        for i, x in enumerate(chs):
            for y in chs[i + 1:]:
                score[(x, y)] += w
                words.setdefault((x, y), []).append(root)
    if not score:
        return
    sec = report.section(
        title, ["chapter", "partner", "gap", "score", "words", "{words shared}", "second partner"],
        note=f"Chapter pairs sharing words that at most {VOCAB_MAX_CHAPTERS} chapters of the book use, "
             f"each word weighing the log of (chapters of the book / chapters holding it), words "
             f"commoner than 1 in {VOCAB_MIN_RARITY} across the Bible left out, names kept (in "
             f"narrative they are the thread).  Section 6 wants the same phrase, 6c the same rare "
             f"words in one pair of verses; this asks only that two chapters draw on the same "
             f"uncommon vocabulary, which is how a story told at length in two places shows "
             f"(Beersheba named in Genesis 21 and 26).  A story retold in common words is beyond "
             f"all three.  One row per chapter with its closest partner; the strongest pairs in the "
             f"footer; double-click for the chapter's page.")
    chapters_all = sorted(chapters_seen)
    for c in chapters_all:
        partners = sorted(((o, score[(min(c, o), max(c, o))]) for o in chapters_all
                           if o != c and score.get((min(c, o), max(c, o)))), key=lambda ow: (-ow[1], ow[0]))
        if not partners:
            sec.add([c, "-", "", "", "", "", ""], link={"book": book, "chapter": c})
            continue
        o, total = partners[0]
        key = (min(c, o), max(c, o))
        shared = sorted(words[key], key=lambda r: -math.log(n_ch / len(holders[r])))
        second = f"{partners[1][0]} ({round(partners[1][1])})" if len(partners) > 1 else "-"
        sec.add([c, o, abs(c - o), round(total, 1), len(shared),
                 ", ".join(atlas.form(r) for r in shared[:10]) + (" ..." if len(shared) > 10 else ""), second],
                link={"book": book, "chapter": c})
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:WITHIN_PAIRS_N]
    sec.footer.append("Strongest pairs: " + "; ".join(
        f"{a} and {b} ({round(w)}, {len(words[(a, b)])} words: "
        + ", ".join(atlas.form(r) for r in sorted(words[(a, b)], key=lambda r: -math.log(n_ch / len(holders[r])))[:4]) + ")"
        for (a, b), w in ranked) + ".")


def reach_depth_section(atlas, report, title, book, info):
    """
    The reach-and-depth chart: the book's signature words placed by how
    widely they spread (reach: share of chapters reached) against how
    thickly they pile up in their one deepest chapter (depth: highest
    chapter keyness).  Top right are the leading words of the book,
    wide and deep; bottom right the spread words; top left the local
    piles (cubits in Ezekiel 40, talents in Matthew 25).
    """
    sec = report.section(
        title, ["word", "reach", "depth", "deepest at", "count", "keyness"],
        note=f"The {REACH_DEPTH_N} most key words of {book}, and the {REACH_DEPTH_DEEP_N} deepest, placed by reach (percent of the book's "
             f"{info['chapters']} chapters the word occurs in) against depth (the highest keyness it "
             f"reaches in one chapter, with that chapter).  Wide and deep, top right, are the book's "
             f"leading words; wide and shallow, bottom right, its spread words; narrow and deep, top "
             f"left, its local piles.  Click a point for the word's verses in its deepest chapter; "
             f"double-click for the word's page.",
        kind="scatter")
    sec.x_column, sec.y_column = "reach", "depth"
    # The words chosen by book keyness lean toward reach; the deepest
    # local piles (feed H7462 in Ezekiel 34, merchandise in 27) have
    # modest keyness for the book as a whole, so the top by depth are
    # added to fill the top left of the chart
    by_key = atlas.db.execute(
        "SELECT root, weight, chapters_reached, keyness, depth, depth_chapter FROM word_book "
        "WHERE book = ? AND weight >= 3 ORDER BY keyness DESC LIMIT ?", (book, REACH_DEPTH_N)).fetchall()
    by_depth = atlas.db.execute(
        "SELECT root, weight, chapters_reached, keyness, depth, depth_chapter FROM word_book "
        "WHERE book = ? AND weight >= 3 ORDER BY depth DESC LIMIT ?", (book, REACH_DEPTH_DEEP_N)).fetchall()
    chosen = {r["root"]: r for r in by_key}
    for r in by_depth:
        chosen.setdefault(r["root"], r)
    for r in sorted(chosen.values(), key=lambda r: -r["keyness"]):
        reach = round(100 * r["chapters_reached"] / info["chapters"])
        sec.add([atlas.form(r["root"]), reach, round(r["depth"] or 0, 1),
                 f"{book} {r['depth_chapter']}", r["weight"], round(r["keyness"], 1)],
                link={"word": r["root"], "book": book, "chapter": r["depth_chapter"]})


def chapter_page(atlas, book_name, chapter):
    """The four reports for one chapter."""
    book = atlas.find_book(book_name)
    chapter = int(chapter)
    verses = atlas.verses_of(book, chapter)
    if not verses:
        raise ValueError(f"No such chapter: {book} {chapter}")
    atlas.use_scope(book, chapter)
    n_scope = sum(len(v["word_string"].split()) for v in verses)
    label = f"{book} {chapter}"
    report = Report(f"chapter_{book.lower().replace(' ', '_')}_{chapter}",
                    f"Chapter page [{label}] ({atlas.settings['translation']})")
    report.notes.append(f"{label}: {len(verses)} verses, {n_scope} words.")
    # The chapter's language, when any of its tagged words are Aramaic
    language = atlas.language_note(book, chapter)
    if language:
        report.notes.append(language)
    if atlas.has_depth:
        # The leading words of the passage: the words whose deepest place
        # in the whole book is this chapter
        # Untagged stems ("shalt", "hath", "whether") are left out: with
        # no number behind them they are compared against the whole
        # Bible and lead only where a chapter has few strong words
        leading = [r for r in atlas.db.execute(
            "SELECT root, depth FROM word_book WHERE book = ? AND depth_chapter = ? AND weight >= 3 "
            "AND depth >= ? ORDER BY depth DESC LIMIT 12", (book, chapter, LEADING_MIN_DEPTH))
            if is_strongs(r[0]) or atlas.roots_mode != "strongs"][:6]
        shown = [f"{atlas.form(r[0])} ({r[1]:.0f})" for r in leading]
        # A chapter whose words peak elsewhere (Genesis 12, the call of
        # Abram, has only "haran, well") is filled out with its own top
        # signature words, marked *, so the outline stays readable
        if len(shown) < LEADING_FILL_TO:
            have = {r[0] for r in leading}
            for r in atlas.db.execute(
                    "SELECT root, keyness FROM word_chapter WHERE book = ? AND chapter = ? AND weight >= 3 "
                    "ORDER BY keyness DESC LIMIT 20", (book, chapter)):
                if r[0] in have or not (is_strongs(r[0]) or atlas.roots_mode != "strongs"):
                    continue
                shown.append(f"{atlas.form(r[0])} ({r[1]:.0f})*")
                have.add(r[0])
                if len(shown) == LEADING_FILL_TO:
                    break
        if shown:
            report.notes.append("Leading words (words whose deepest chapter in the book is this one; "
                                "* = a signature word of this chapter that is deeper elsewhere): "
                                + ", ".join(shown) + ".")

    rows = [(r["root"], r["weight"], None, r["keyness"]) for r in atlas.db.execute(
        "SELECT root, weight, keyness FROM word_chapter "
        "WHERE book = ? AND chapter = ? AND weight >= 2 ORDER BY keyness DESC LIMIT ?",
        (book, chapter, TOP_N))]
    top = signature_words_section(atlas, report, f"1. Signature words [{label}]", rows,
                                  n_scope, "chap", book, chapter)

    signature_formulas_section(atlas, report, f"2. Signature formulas [{label}]",
                               verses, book, n_scope)

    testament = atlas.book_info[book]["testament"]
    focus = [atlas.root_of(w, testament) for w in FOCUS_WORDS]
    focus += [r for r in top[:3] if r not in focus]
    for i, root in enumerate(focus):
        neighbors_section(atlas, report, f"3.{i + 1} Neighbors of '{atlas.form(root)}' [{book}] (book scale)",
                        book, root, atlas.forms.get(root, root), book)
    report.sections[-len(focus)].note = ("Neighbors is stored at book and Bible scale; a chapter is "
                                         "too small for stable pull, so the left column is the "
                                         "book this chapter belongs to.  " + report.sections[-len(focus)].note)

    echoes_section(atlas, report, f"4. Echoes [{label}] -> other books", book, chapter)
    far = "Greek Old Testament" if atlas.book_info[book]["testament"] == "New" else "New Testament, in Greek"
    septuagint_echoes_section(atlas, report, f"4e. Septuagint echoes [{label}] -> {far}", book, [chapter])
    synopsis_section(atlas, report, book, chapter, verses)
    kin_section(atlas, report, book, chapter)
    return report


def kin_section(atlas, report, book, chapter):
    """
    The chapter's kin at the foot of its page: the KIN_CHAPTER_N chapters
    elsewhere sharing the most rare words with it in any order, the
    imagery test that echoes (which want the same run of words) miss.
    The full list is the Kin page; this is its head, so a dossier
    carries it.
    """
    try:
        kin = kin_page(atlas, book, chapter)
    except ValueError:
        return
    full = kin.sections[0]
    sec = report.section(
        f"6. Kin [{book} {chapter}]: chapters sharing rare words in any order",
        full.columns,
        note=f"The {KIN_CHAPTER_N} chapters of other books most kin to this one.  " + full.note
             + "  Echoes (section 4) need the same run of words; kin needs only the same rare "
               "words, so it catches imagery retold in other phrasing.  The Kin page has the full list.")
    for i, row in enumerate(full.rows[:KIN_CHAPTER_N]):
        sec.add(row, refs=full.refs[i], link=full.links[i])


def synopsis_section(atlas, report, book, chapter, verses):
    """
    The chapter verse by verse, with the matching verses in the book's
    two chief partners: a synopsis generated from shared runs of words
    rather than compiled by hand.
    """
    partners = chief_partners(atlas, book, 2)
    if not partners:
        return
    matches = {pb: parallels(atlas, book, pb) for pb in partners}
    sec = report.section(
        f"5. Synopsis [{book} {chapter}] with " + " and ".join(partners),
        ["verse"] + partners + ["text"],
        note=f"Each verse of the chapter with its parallels in {' and '.join(partners)}: verses "
             f"sharing at least {PARALLEL_MIN_SHARED} content words in the same order, making up at "
             f"least {PARALLEL_SHARE:.0%} of the shorter verse.  Closest first, at most four.  Blank "
             f"= no parallel.  Click a row for the verse and its parallels in full.")
    for v in verses:
        ref = v["reference"]
        row = [ref.rsplit(" ", 1)[1]]
        refs = [ref]
        for pb in partners:
            # Closest parallels first (most shared runs), at most four shown;
            # a verse of pure idiom can match dozens and would swamp the row
            hits = [h for h, c in matches[pb].get(ref, Counter()).most_common()]
            shown = hits[:4]
            cell = ", ".join(h.rsplit(" ", 1)[1] for h in shown)
            if len(hits) > 4:
                cell += f" +{len(hits) - 4}"
            row.append(cell)
            refs += shown
        text = v["text"]
        row.append(text if len(text) <= 70 else text[:67] + "...")
        sec.add(row, refs=refs, link=None)


def word_page(atlas, word, book_name=None, exact=False):
    """
    The shadow map of one word across the 66 books, and its neighbors.
    With exact=True the word is taken as a root already (the dossier
    passes the roots the book page counted, so an untagged stem such
    as 'sick' opens its own page rather than the commonest number
    behind the English word).
    """
    atlas.use_scope(None)
    # With a book named, an English word is resolved in that book's
    # testament ('day' [Luke] is G2250, not H3117)
    testament = atlas.book_info[atlas.find_book(book_name)]["testament"] if book_name else None
    root = word if exact and atlas.word_row(word) is not None else atlas.root_of(word, testament)
    w = atlas.word_row(root)
    if w is None:
        raise ValueError(f"'{word}' (root '{root}') is not in the atlas, or is on the stoplist.")
    # The title spells the root as the named book does ('straightway
    # G2112' from Mark, not the Bible's 'immediately'); the sections
    # below keep the Bible-wide spelling, since they range over all 66
    if book_name:
        atlas.use_scope(atlas.find_book(book_name))
        title_form = atlas.form(root)
        atlas.use_scope(None)
    else:
        title_form = atlas.form(root)
    report = Report(f"word_{root.lower()}", f"Word page '{title_form}'")
    if is_strongs(root):
        # Phase 5: the original word and gloss, and how the text spells it
        gloss = atlas.gloss(root)
        if gloss:
            report.notes.append(f"{root} {gloss}")
        spelled = ", ".join(f"{sp} {n}" for sp, n in atlas.spellings(root))
        report.notes.append(f"Spelled in the Bible as: {spelled}.")
    else:
        report.notes.append(f"Root '{root}', spelled {atlas.form(root)}"
                            + ("; no Strong's number is attached to this word."
                               if atlas.roots_mode == "strongs" else "."))
    report.notes.append(
        f"Bible scale: weight {w['weight']} ({per_thousand(w['weight'], atlas.comparison_words(root))} "
        f"per 1,000 words of its {'testament' if is_strongs(root) else 'Bible'}), reach "
        f"{w['verses_reached']} verses, {w['chapters_reached']} chapters, "
        f"{w['books_reached']} of {atlas.comparison_books(root)} books, shadow {w['shadow']:.0f} "
        f"(the shadow is the summed pull of every neighbour the word draws more often than chance, "
        f"within {atlas.window} words: its total influence over the words around it).")
    if atlas.has_depth and w["depth_book"]:
        report.notes.append(f"Deepest at: {w['depth_book']} {w['depth_chapter']} (depth {w['depth']:.0f}, "
                            f"the highest keyness the word reaches in any one chapter).")
    # Where the word is most at home: the books that prefer it most, by
    # keyness against the rest of its testament (or the Bible)
    # At least HOME_MIN_WEIGHT occurrences, as the testament page asks,
    # so two occurrences in Jude are not a second home
    home = atlas.db.execute(
        "SELECT book, weight, keyness FROM word_book WHERE root = ? AND keyness > 0 AND weight >= ? "
        "ORDER BY keyness DESC LIMIT 3", (root, HOME_MIN_WEIGHT)).fetchall()
    if home:
        report.notes.append("At home in: " + "; ".join(
            f"{h['book']} ({h['weight']}, keyness {h['keyness']:.0f})" for h in home) + ".")

    # When an English word was typed and several numbers stand behind
    # it, list them first so the reader can turn to the other ones
    if atlas.roots_mode == "strongs" and not STRONGS_IN_TEXT.search(word):
        behind = atlas.roots_behind(word, testament)
        if len(behind) > 1:
            sec = report.section(
                f"0. Roots behind '{word}'",
                ["root", "count", "original word", "KJV glosses"],
                note=f"The text gives '{word}' these roots; this page is the first.  "
                     "Double-click another to turn to its page.")
            for r, n in behind[:12]:
                entry = atlas.lexicon_entry(r) or ("", "", "")
                sec.add([atlas.form(r), n, entry[0], clean_gloss(entry[1] or entry[2])], link={"word": r})

    sec = report.section(
        f"1. Shadow map '{atlas.form(root)}' [each book]",
        ["book", "count", "per 1000", "keyness", "reach", "depth", "deepest", "shadow", "bar"]
        if atlas.has_depth else ["book", "count", "per 1000", "keyness", "reach", "shadow", "bar"],
        note="One row per book in canonical order.  Keyness compares the book with the rest of "
             "its testament (negative = rarer than expected); reach is chapters of the book the "
             "word occurs in; depth is the highest keyness it reaches in one chapter of the book, "
             "and deepest that chapter; shadow is the summed pull of its neighbors inside that book.",
        kind="bars")
    sec.value_column = "per 1000"
    rows = {r["book"]: r for r in atlas.db.execute("SELECT * FROM word_book WHERE root = ?", (root,))}
    max_rate = max((1000 * r["weight"] / atlas.book_info[b]["words"] for b, r in rows.items()), default=1)
    # A Strong's number belongs to one testament; the other's 39 (or 27)
    # zero rows are noise, so only the word's own testament is listed
    shown_books = atlas.books
    if is_strongs(root):
        own = "Old" if root.startswith("H") else "New"
        shown_books = [b for b in atlas.books if atlas.book_info[b]["testament"] == own]
        sec.note += (f"  {root} is a {'Hebrew' if own == 'Old' else 'Greek'} root, so only the "
                     f"{own} Testament is listed; the other testament has none of it.")
    for book in shown_books:
        info = atlas.book_info[book]
        r = rows.get(book)
        # A word with no depth in a book has no deepest chapter: a dash,
        # not Python's None
        depth_cells = ([round(r["depth"] or 0, 1), f"ch {r['depth_chapter']}" if r["depth_chapter"] else "-"]
                       if (r is not None and atlas.has_depth) else (["", ""] if atlas.has_depth else []))
        if r is None:
            sec.add([book, 0, "", "", f"0/{info['chapters']}"] + depth_cells + ["", ""], link=None)
            continue
        rate = 1000 * r["weight"] / info["words"]
        bar = "#" * int(round(30 * rate / max_rate)) if max_rate else ""
        sec.add([book, r["weight"], round(rate, 2), round(r["keyness"], 1),
                 f"{r['chapters_reached']}/{info['chapters']}"] + depth_cells + [round(r["shadow"]), bar],
                refs=None, link={"word": root, "book": book})

    if book_name:
        book = atlas.find_book(book_name)
        neighbors_section(atlas, report, f"2. Neighbors of '{atlas.form(root)}' [{book}]",
                        book, root, word, book)
    else:
        sec = report.section(f"2. Neighbors of '{atlas.form(root)}' [Bible]",
                             ["neighbor", "count", "pull"],
                             note="Name a book to see its neighbors there beside this.")
        for c in atlas.neighbors("Bible", root, COMPANY_N * 2):
            sec.add([atlas.form(c["neighbor"]), c["count"], round(c["pull"], 1)],
                    link={"word": c["neighbor"]})

    sec = report.section(f"3. Formulas holding '{atlas.form(root)}' [Bible]",
                         ["formula", "verses", "books"],
                         note="Formulas of 2 to 5 words containing this word, most widespread first.")
    # Formulas are stored on unit keys (the root itself on a Strong's
    # build, the commonest spelling on an English one)
    if atlas.phrase_column == "word_string":
        needle = atlas.forms.get(root) or (word if word.isupper() else word.lower())
    else:
        needle = root
    display_col = ", display" if atlas.has_display else ""
    for r in atlas.db.execute(
            f"SELECT phrase, verses_total, books_total{display_col} FROM ngrams "
            "WHERE (' ' || phrase || ' ') LIKE ? ORDER BY verses_total DESC LIMIT ?",
            (f"% {needle} %", TOP_N)):
        shown = r["display"] if atlas.has_display else r["phrase"]
        sec.add([shown, r["verses_total"], r["books_total"]], link={"phrase": shown, "key": r["phrase"]})
    sec.merge_duplicates(score_column="verses")
    if not sec.rows:
        sec.note += "  (none stored: the word never ends a formula found in 2+ verses)"
    return report


def testament_page(atlas, testament_name):
    atlas.use_scope(None)
    """
    The testament page (phase 5): the word-level view turned round.
    For each book of a testament, the words most at home in it; a home
    map of books by words, shaded by the share of the word's occurrences
    the book holds; and a table answering, for any Strong's number,
    which book is its home.
    """
    testament = atlas.find_testament(testament_name)
    books = [b for b in atlas.books if atlas.book_info[b]["testament"] == testament]
    n_words = atlas.n_testament[testament]
    label = f"{testament} Testament"
    report = Report(f"testament_{testament.lower()}", f"Testament page [{testament}] ({atlas.settings.get('translation', '')})")
    report.notes.append(f"{label}: {len(books)} books, {n_words} words.  Keyness here compares each book "
                        f"with the rest of the {label}; share is how many of a word's {label} "
                        f"occurrences fall in the book.")
    if atlas.roots_mode != "strongs":
        report.notes.append("This build uses English stems; the page reads best on a Strong's build, "
                            "where a root belongs to one testament.")

    # Every root's keyness and weight per book of the testament, once
    marks = ",".join("?" * len(books))
    per_book = {}                   # book -> [(root, weight, keyness)] best first
    total = Counter()               # root -> weight across the testament
    for r in atlas.db.execute(
            f"SELECT root, book, weight, keyness FROM word_book WHERE book IN ({marks})", books):
        per_book.setdefault(r["book"], []).append((r["root"], r["weight"], r["keyness"]))
        total[r["root"]] += r["weight"]
    for book in per_book:
        per_book[book].sort(key=lambda t: -t[2])

    def home_words(book, n):
        """The n roots most at home in a book: highest keyness, enough weight."""
        out = []
        for root, weight, keyness in per_book.get(book, []):
            if weight >= HOME_MIN_WEIGHT and keyness > 0:
                out.append((root, weight, keyness))
            if len(out) == n:
                break
        return out

    # 1. Home words by book
    sec = report.section(
        f"1. Home words by book [{testament}]", ["book", "words", "home words (count of testament)"],
        note=f"For each book, the six words most at home in it: highest keyness against the rest of "
             f"the {label}, at least {HOME_MIN_WEIGHT} occurrences.  Double-click a row for the book's page.")
    for book in books:
        words = ", ".join(f"{atlas.form(r)} ({w} of {total[r]})" for r, w, k in home_words(book, 6))
        sec.add([book, atlas.book_info[book]["words"], words or "-"], link={"book": book})

    # 2. The home map: books down the side, each book's top home words
    #    across, shaded by the share of the word the book holds
    columns = []
    for book in books:
        for r, w, k in home_words(book, HOME_PER_BOOK):
            if r not in columns:
                columns.append(r)
    heat = report.section(
        f"2. Home map [{testament}]", ["book"] + [atlas.form(r) for r in columns],
        note=f"Books down the side, the {HOME_PER_BOOK} words most at home in each book across (in the "
             f"order of the books), each cell the share of the word's {label} occurrences that "
             f"fall in that book, in percent.  A dark cell in one row is a word that lives in one "
             f"book; a column of pale cells is a word spread through the testament.  Hover for "
             f"the number; click a cell for the word's verses in that book; double-click for the "
             f"book's page.  Tick 'each column on its own scale' to see where the spread words lean.",
        kind="heatmap")
    heat.value_label = "share %"
    weight_in = {}
    for book, rows in per_book.items():
        for root, weight, keyness in rows:
            weight_in[(root, book)] = weight
    for i, book in enumerate(books):
        row = [book]
        for j, root in enumerate(columns):
            w = weight_in.get((root, book), 0)
            row.append(round(100 * w / total[root]) if total[root] else 0)
            if w:
                heat.cell_links[(i, j + 1)] = {"word": root, "book": book}
        heat.add(row, link={"book": book})

    # 3. Whose word is this: every listed root with its home book
    who = report.section(
        f"3. Whose word is this [{testament}]",
        ["word", "home book", "in home", "of testament", "share", "keyness", "second home", "books"],
        note=f"The {HOME_LIST_N} words with the strongest home, best first: the book that prefers the "
             f"word most (keyness), how many of the word's {label} occurrences it holds, and the "
             f"next book.  Double-click a word for its page, where 'At home in' says the same.")
    best = {}                       # root -> (keyness, book, weight)
    second = {}
    for book, rows in per_book.items():
        for root, weight, keyness in rows:
            if weight < HOME_MIN_WEIGHT or keyness <= 0:
                continue
            if root not in best or keyness > best[root][0]:
                if root in best:
                    second[root] = best[root]
                best[root] = (keyness, book, weight)
            elif root not in second or keyness > second[root][0]:
                second[root] = (keyness, book, weight)
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])[:HOME_LIST_N]
    for root, (keyness, book, weight) in ranked:
        w = atlas.word_row(root)
        sec_home = second.get(root)
        who.add([atlas.form(root), book, weight, total[root], f"{100 * weight / total[root]:.0f}%",
                 round(keyness, 1), f"{sec_home[1]} ({sec_home[2]})" if sec_home else "-",
                 f"{w['books_reached']}/{atlas.comparison_books(root)}" if w else ""],
                link={"word": root, "book": book})
    return report


def compare_page(atlas, a_name, b_name):
    """
    Two books, chapter against chapter: the map the within-book map was
    a prototype of.  Chapters of the first book down, chapters of the
    second across, each cell the summed rarity of the phrases (three or
    more words) the two chapters share and few verses of the two books
    hold (at most CROSS_MAX_VERSES).  Then each chapter's closest
    chapter in the other book, both ways, and whether the first follows
    the second's order.  Within a testament the phrases are runs of
    Strong's roots; between the testaments, English wording.
    """
    a_book, b_book = atlas.find_book(a_name), atlas.find_book(b_name)
    if a_book == b_book:
        raise ValueError("Compare needs two different books; a book against itself is section 6 of its page.")
    atlas.use_scope(None)
    same_testament = atlas.book_info[a_book]["testament"] == atlas.book_info[b_book]["testament"]
    column = atlas.phrase_column if same_testament else "word_string"
    # Within a testament, a book in two languages (Daniel, Ezra) is
    # bridged to the other book by English wording where the languages
    # differ, as the testaments are bridged
    bridged = (column != "word_string"
               and len(atlas.languages_of(a_book) | atlas.languages_of(b_book)) > 1)
    report = Report(f"compare_{a_book.lower().replace(' ', '_')}_{b_book.lower().replace(' ', '_')}",
                    f"Compare [{a_book}] x [{b_book}] ({atlas.settings['translation']})")
    a_info, b_info = atlas.book_info[a_book], atlas.book_info[b_book]
    report.notes.append(f"{a_book}: {a_info['chapters']} chapters, {a_info['words']} words.  "
                        f"{b_book}: {b_info['chapters']} chapters, {b_info['words']} words.  "
                        + ("Phrases are matched as runs of Strong's roots."
                           + ("  One of the books is partly Aramaic, and a Hebrew root never matches "
                              "an Aramaic one, so between verses in different languages phrases are "
                              "matched by English wording instead, marked 'by English'."
                              if bridged else "")
                           if column != "word_string" else
                           "The books are in different testaments, so phrases are matched by English "
                           "wording (a Hebrew root and a Greek root never match)."))

    places_a, wordings_a = phrase_places(atlas, atlas.verses_of(a_book), column)
    places_b, wordings_b = phrase_places(atlas, atlas.verses_of(b_book), column)
    if bridged:
        # English wording on both sides, kept only where the two books'
        # verses are in different languages; the roots cover the rest
        en_a, enw_a = phrase_places(atlas, atlas.verses_of(a_book), "word_string")
        en_b, enw_b = phrase_places(atlas, atlas.verses_of(b_book), "word_string")
        for key in set(en_a) & set(en_b):
            refs_a = [r for refs in en_a[key].values() for r in refs]
            refs_b = [r for refs in en_b[key].values() for r in refs]
            if cross_language(atlas, refs_a, refs_b, a_book, b_book):
                places_a["en:" + key], wordings_a["en:" + key] = en_a[key], enw_a[key]
                places_b["en:" + key], wordings_b["en:" + key] = en_b[key], enw_b[key]
    kept = {}
    for key in set(places_a) & set(places_b):
        total = sum(len(r) for r in places_a[key].values()) + sum(len(r) for r in places_b[key].values())
        if total > CROSS_MAX_VERSES:
            continue
        wording = wordings_a[key] + wordings_b[key]
        display = wording.most_common(1)[0][0]
        if not has_substance(display):
            continue
        if key.startswith("en:"):
            display += " (by English)"
        # chapters of A and of B kept apart under negative/positive keys
        chapters = {("a", c): refs for c, refs in places_a[key].items()}
        chapters.update({("b", c): refs for c, refs in places_b[key].items()})
        kept[key] = (chapters, display)
    pieces = drop_pieces(kept)
    # A phrase that is a refrain of either book (REFRAIN_MIN_CHAPTERS or
    # more of its chapters) is set aside, as 6b does within a book: "a
    # voice from heaven saying" is Revelation's own, and with the verse
    # cap counted over both books together it slipped under and made
    # Daniel 4 the closest chapter of four Revelation chapters
    refrains = {}                     # key -> the book it is a refrain of
    for key, (chapters, display) in sorted(kept.items()):
        if key in pieces:
            continue
        # Between books the refrain must also fill CROSS_REFRAIN_MIN_VERSES
        # verses of its book: in a 52-chapter book a phrase in three
        # chapters and three verses ("the flock of my pasture") is a
        # theme, not a refrain, and setting it aside cost Ezekiel 34 its
        # partner Jeremiah 23
        n_a = sum(1 for (side, c) in chapters if side == "a")
        n_b = sum(1 for (side, c) in chapters if side == "b")
        v_a = sum(len(refs) for (side, c), refs in chapters.items() if side == "a")
        v_b = sum(len(refs) for (side, c), refs in chapters.items() if side == "b")
        if n_a >= REFRAIN_MIN_CHAPTERS and v_a >= CROSS_REFRAIN_MIN_VERSES:
            refrains[key] = a_book
        elif n_b >= REFRAIN_MIN_CHAPTERS and v_b >= CROSS_REFRAIN_MIN_VERSES:
            refrains[key] = b_book
    # A phrase that carries a refrain inside it ("a voice from heaven
    # saying" around "voice from heaven") is the refrain grown by a word,
    # and goes with it
    refrain_units = [(k.split(), book) for k, book in refrains.items()]
    for key in sorted(kept):
        if key in pieces or key in refrains:
            continue
        units = key.split()
        for ru, book in refrain_units:
            if len(ru) < len(units) and any(units[i:i + len(ru)] == ru for i in range(len(units) - len(ru) + 1)):
                refrains[key] = book
                break

    cell_weight, cell_count, cell_refs, cell_best = Counter(), Counter(), {}, {}
    for key, (chapters, display) in sorted(kept.items()):
        if key in pieces or key in refrains:
            continue
        weight = phrase_weight(atlas, key, column)
        a_chs = [c for (side, c) in chapters if side == "a"]
        b_chs = [c for (side, c) in chapters if side == "b"]
        for ca in a_chs:
            for cb in b_chs:
                # An English-bridged phrase counts only between chapters in
                # different languages
                if key.startswith("en:") and not cross_language(
                        atlas, chapters[("a", ca)], chapters[("b", cb)], a_book, b_book):
                    continue
                cell_weight[(ca, cb)] += weight
                cell_count[(ca, cb)] += 1
                cell_refs.setdefault((ca, cb), []).extend(chapters[("a", ca)] + chapters[("b", cb)])
                if weight > cell_best.get((ca, cb), (0, ""))[0]:
                    cell_best[(ca, cb)] = (weight, display)
    a_chapters = list(range(1, a_info["chapters"] + 1))
    b_chapters = list(range(1, b_info["chapters"] + 1))
    if not cell_weight:
        report.notes.append(f"No rare phrases are shared between {a_book} and {b_book}.")
        return report

    heat = report.section(
        f"1. Chapter map [{a_book}] x [{b_book}]", [f"{a_book} \\ {b_book}"] + [str(c) for c in b_chapters],
        note=f"Chapters of {a_book} down, chapters of {b_book} across, each cell the summed rarity of "
             f"the phrases of three or more words the two chapters share and at most {CROSS_MAX_VERSES} "
             f"verses of the two books hold together.  A phrase found in {REFRAIN_MIN_CHAPTERS} or more "
             f"chapters and {CROSS_REFRAIN_MIN_VERSES} or more verses of either book is that book's "
             f"refrain and is set aside first.  A "
             f"diagonal band is one book following the other's order; a column is a chapter the "
             f"other book keeps returning to.  Click a cell for the verses on both sides; double-click "
             f"for the {a_book} chapter's page; tick 'each column on its own scale' for the fainter pairs.",
        kind="heatmap")
    heat.value_label = "shared weight"
    for i, ca in enumerate(a_chapters):
        row = [ca]
        for j, cb in enumerate(b_chapters):
            row.append(round(cell_weight.get((ca, cb), 0)))
            refs = cell_refs.get((ca, cb))
            if refs:
                heat.cell_refs[(i, j + 1)] = sorted(set(refs), key=ref_order)
        heat.add(row, link={"book": a_book, "chapter": ca})
    strongest = sorted(cell_weight.items(), key=lambda kv: -kv[1])[:WITHIN_PAIRS_N]
    heat.footer.append("Strongest pairs: " + "; ".join(
        f"{a_book} {ca} and {b_book} {cb} ({round(w)}, {cell_count[(ca, cb)]} phrases: "
        f"\"{cell_best[(ca, cb)][1]}\")" for (ca, cb), w in strongest) + ".")
    # Column and row totals: the chapters of each book the other draws
    # on most, so the reader need not add the columns up (Jeremiah 23
    # and 32 recur as Ezekiel's partners; the totals say so at once)
    col_total, row_total = Counter(), Counter()
    for (ca, cb), w in cell_weight.items():
        col_total[cb] += w
        row_total[ca] += w
    heat.footer.append(f"Chapters of {b_book} most drawn on: " + ", ".join(
        f"{cb} ({round(w)})" for cb, w in col_total.most_common(6)) + ".")
    heat.footer.append(f"Chapters of {a_book} most drawn on: " + ", ".join(
        f"{ca} ({round(w)})" for ca, w in row_total.most_common(6)) + ".")
    if refrains:
        # Equal weights are broken by the phrase itself, so two runs list
        # the same eight: a tie left to dictionary order moved "up for a
        # burnt offering" against "for the burnt offering" on Genesis x
        # Ezekiel between 0.10.53 and 0.10.55 and put a line in every
        # diff of the dossiers for no reason a reader could see
        shown = sorted(refrains.items(), key=lambda kv: (-phrase_weight(atlas, kv[0], column), kv[0]))[:8]
        heat.footer.append("Refrains set aside: " + "; ".join(
            f"\"{kept[key][1]}\" ({book})" for key, book in shown)
            + (f"; and {len(refrains) - 8} more" if len(refrains) > 8 else "") + ".")

    # The floor under the chapter-to-chapter lists: a closest partner
    # resting on one or two shared phrases, or on a weight far below the
    # page's strongest pair, is idiom (2 Samuel 1 to 21 against the
    # Psalms), and prints as a dash rather than as a relationship
    # The weight floor is taken from the third strongest pair, not the
    # first: a twin text (Psalm 18 and 2 Samuel 22, 2728) would otherwise
    # set a floor that drops Psalm 89 and 2 Samuel 7 (53, the covenant)
    top_weight = strongest[min(2, len(strongest) - 1)][1] if strongest else 0
    floor = CROSS_LIST_FLOOR * top_weight

    def partner_table(number, this, other, this_chapters, other_chapters, lookup):
        sec = report.section(
            f"{number}. Chapter to chapter [{this}] -> [{other}]",
            ["chapter", f"closest in {other}", "weight", "phrases", "strongest shared phrase", "second"],
            note=f"For each chapter of {this} with a partner above the floor, the chapter of {other} it "
                 f"shares the most rare phrasing with, the number of shared phrases, the phrase that "
                 f"weighs most, and the next partner that also passes the floor.  The floor: "
                 f"{CROSS_LIST_MIN_PHRASES} shared phrases, or a weight of {CROSS_LIST_MIN_WEIGHT} (two "
                 f"rare phrases, or one very rare one), and in either case a tenth of the page's third "
                 f"strongest pair ({round(floor)}); chapters with nothing above it are counted in the "
                 f"footer rather than listed, since what is below it is shared idiom, not a chapter "
                 f"relationship.  Click a row for the verses on both sides; double-click for the "
                 f"chapter's page.")
        pointed = []
        below = 0
        for c in this_chapters:
            partners = sorted(((o, cell_weight[lookup(c, o)]) for o in other_chapters
                               if cell_weight.get(lookup(c, o))
                               and (cell_count[lookup(c, o)] >= CROSS_LIST_MIN_PHRASES
                                    or cell_weight[lookup(c, o)] >= CROSS_LIST_MIN_WEIGHT)
                               and cell_weight[lookup(c, o)] >= floor), key=lambda ow: -ow[1])
            if not partners:
                below += 1
                continue
            o, w = partners[0]
            key = lookup(c, o)
            second = f"{partners[1][0]} ({round(partners[1][1])})" if len(partners) > 1 else "-"
            sec.add([c, o, round(w), cell_count[key], cell_best[key][1], second],
                    refs=sorted(set(cell_refs[key]), key=ref_order), link={"book": this, "chapter": c})
            # A pointer resting on a couple of phrases says nothing about order
            if cell_count[key] >= CROSS_MIN_PHRASES:
                pointed.append((c, o))
        # Does this book follow the other's order?  The 4b rule: runs of
        # chapters whose closest partners never go backwards, dense
        # enough to mean something
        runs, start = [], 0
        for i in range(1, len(pointed) + 1):
            if i == len(pointed) or pointed[i][1] < pointed[i - 1][1]:
                count = i - start
                if count >= ORDER_RUN_MIN:
                    first, last = pointed[start][0], pointed[i - 1][0]
                    skipped = (last - first + 1) - count
                    gaps = [pointed[k + 1][0] - pointed[k][0] - 1 for k in range(start, i - 1)]
                    dense = count > skipped or (count >= 5 and max(gaps, default=0) <= 2)
                    if dense and (skipped == 0 or count >= ORDER_RUN_GAPPED_MIN):
                        runs.append((first, last, count))
                start = i
        for first, last, count in runs:
            sec.footer.append(f"{this} follows the order of {other} from chapter {first} to {last} "
                              f"({count} chapters whose closest partners come in non-decreasing order).")
        if below:
            sec.footer.append(f"{below} of {len(this_chapters)} chapters of {this} have no partner in "
                              f"{other} above the floor and are not listed.")
        return sec

    partner_table(2, a_book, b_book, a_chapters, b_chapters, lambda c, o: (c, o))
    partner_table(3, b_book, a_book, b_chapters, a_chapters, lambda c, o: (o, c))

    # -- verse level: which verses of each book have a parallel in the other --
    # The book page's 4d and 5 for one pair of books: a chapter pair on
    # the map can be opened to its verses.  The overlap rule (three
    # content roots in the same order, PARALLEL_SHARE of the shorter
    # verse); across the testaments by English stem.
    cross = column == "word_string"
    rule = (f"Two verses are parallel when the content {'stems' if cross else 'roots'} they share "
            f"in the same order number at least {PARALLEL_MIN_SHARED} and make up at least "
            f"{PARALLEL_SHARE:.0%} of the shorter verse; words in more than "
            f"{PARALLEL_COMMON_SHARE:.0%} of the book's verses are set aside first.")

    def shared_table(number, this, other, this_chapters):
        matches = parallels(atlas, this, other)
        sec = report.section(
            f"{number}. Verses of [{this}] with a parallel in [{other}], by chapter",
            ["chapter", "verses", "with a parallel", "share", "points to"],
            note=f"How much of each chapter of {this} has a verse-level parallel in {other}.  {rule}  "
                 f"'points to' is the chapter of {other} the parallels fall in most.  Click a row "
                 f"for the verses on both sides; double-click for the chapter's page.")
        by_chapter = {}
        for ref, hits in matches.items():
            ch = int(ref.rsplit(" ", 1)[1].split(":")[0])
            by_chapter.setdefault(ch, {})[ref] = hits
        n_verses = {r[0]: r[1] for r in atlas.db.execute(
            "SELECT chapter, COUNT(*) FROM verses WHERE book = ? GROUP BY chapter", (this,))}
        total_with = 0
        for c in this_chapters:
            hits = by_chapter.get(c, {})
            n = n_verses.get(c, 0)
            total_with += len(hits)
            target = Counter()
            refs = []
            for ref, partners in hits.items():
                refs.append(ref)
                for pref, score in partners.most_common(2):
                    target[int(pref.rsplit(" ", 1)[1].split(":")[0])] += score
                    refs.append(pref)
            points = ", ".join(f"{other} {pc} ({sc})" for pc, sc in target.most_common(2)) if target else "-"
            sec.add([c, n, len(hits), f"{100 * len(hits) / n:.0f}%" if n else "", points],
                    refs=refs, link={"book": this, "chapter": c})
        n_all = sum(n_verses.values())
        sec.footer.append(f"Whole book: {total_with} of {n_all} verses of {this} have a parallel in "
                          f"{other} ({100 * total_with / n_all:.0f}%).")
        return matches

    matches_a = shared_table(4, a_book, b_book, a_chapters)
    shared_table(5, b_book, a_book, b_chapters)

    # -- the synopsis of the pair: only the verses that have a parallel --
    syn = report.section(
        f"6. Synopsis [{a_book}] x [{b_book}]: the verses with a parallel",
        ["verse", f"in {b_book}", "text"],
        note=f"Every verse of {a_book} that has a parallel in {b_book}, with its parallels "
             f"(closest first, at most four) and its text; verses without one are left out, so "
             f"the table is the two books' common ground read in {a_book}'s order.  Click a row "
             f"for the verse and its parallels in full.")
    for v in atlas.verses_of(a_book):
        ref = v["reference"]
        hits = matches_a.get(ref)
        if not hits:
            continue
        shown = [h for h, c in hits.most_common()][:4]
        cell = ", ".join(h.rsplit(" ", 1)[1] for h in shown)
        if len(hits) > 4:
            cell += f" +{len(hits) - 4}"
        text = v["text"]
        syn.add([ref.rsplit(" ", 1)[1], cell, text if len(text) <= 70 else text[:67] + "..."],
                refs=[ref] + shown, link=None)
    return report


def kin_page(atlas, book_name, chapter):
    atlas.use_scope(None)
    """
    Chapters elsewhere whose verses share clusters of rare words with
    the verses of one chapter or passage.

    Echoes find shared word RUNS, which catches quotation.  Kin finds
    shared rare WORDS in any order, which catches a writer borrowing
    another's imagery in his own phrasing: Ezekiel 47:12 and Revelation
    22:2 share river, tree, fruit, leaves and month, and no formula.

    The test is verse against verse.  A pair of verses is kin when they
    share at least KIN_MIN_SHARED rare words (1 in 2,000 or rarer across
    the Bible); the pair scores the summed rarity of the words shared,
    raised by up to half again when the shared words come in the same
    ORDER in both verses.  "In order" is the longest run of shared words
    with the same order in both verses, anything allowed in between.
    A chapter's score is the sum over its kin verse pairs.
    """
    book = atlas.find_book(book_name)
    v_from = v_to = None
    if ":" in str(chapter):
        chapter, span = str(chapter).split(":", 1)
        v_from, _, v_to = span.partition("-")
        v_from = int(v_from)
        v_to = int(v_to) if v_to else v_from
    chapter = int(chapter)
    label = f"{book} {chapter}" + (f":{v_from}-{v_to}" if v_from else "")
    threshold = math.log(2000)

    sql = ("SELECT t.verse_id, v.reference, t.root FROM tokens t JOIN verses v USING (verse_id) "
           "WHERE v.book = ? AND v.chapter = ? AND t.is_stop = 0")
    params = [book, chapter]
    if v_from:
        sql += " AND v.verse BETWEEN ? AND ?"
        params += [v_from, v_to]
    sql += " ORDER BY t.verse_id, t.position"
    source, source_order, source_ref = {}, {}, {}
    for verse_id, reference, root in atlas.db.execute(sql, params):
        if atlas.rarity(root) >= threshold:
            source.setdefault(verse_id, set()).add(root)
            source_order.setdefault(verse_id, []).append(root)
            source_ref[verse_id] = reference
    if not source:
        raise ValueError(f"No such passage, or no rare words in it: {label}")
    roots = set().union(*source.values())

    def in_order(a, b, shared):
        """Longest common subsequence over the shared words, each counted once."""
        a = [r for i, r in enumerate(a) if r in shared and r not in a[:i]]
        b = [r for i, r in enumerate(b) if r in shared and r not in b[:i]]
        table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
        for i in range(1, len(a) + 1):
            for j in range(1, len(b) + 1):
                if a[i - 1] == b[j - 1]:
                    table[i][j] = table[i - 1][j - 1] + 1
                else:
                    table[i][j] = max(table[i - 1][j], table[i][j - 1])
        return table[len(a)][len(b)]

    holders, meta = {}, {}
    for root in roots:
        ids = set()
        for r in atlas.db.execute(
                "SELECT t.verse_id, v.book, v.chapter, v.reference FROM tokens t "
                "JOIN verses v USING (verse_id) WHERE t.root = ? AND v.book != ?", (root, book)):
            ids.add(r[0])
            meta[r[0]] = (r[1], r[2], r[3])
        holders[root] = ids
    pairs = {}
    for s_id, s_roots in source.items():
        for root in s_roots:
            for t_id in holders[root]:
                pairs.setdefault((s_id, t_id), set()).add(root)

    chapter_score, chapter_best, chapter_refs = Counter(), {}, {}
    found_by = {}                     # (book, chapter) -> "roots" or "English"
    for (s_id, t_id), shared in sorted(pairs.items(), key=lambda kv: (kv[0][0], atlas.ref_key(meta[kv[0][1]][2]))):
        if len(shared) < KIN_MIN_SHARED:
            continue
        target_order = [r[0] for r in atlas.db.execute(
            "SELECT root FROM tokens WHERE verse_id = ? AND is_stop = 0 ORDER BY position", (t_id,))
            if r[0] in shared]
        order = in_order(source_order[s_id], target_order, shared)
        score = sum(atlas.rarity(r) for r in shared) * (1 + 0.5 * order / len(shared))
        b, c, ref = meta[t_id]
        chapter_score[(b, c)] += score
        found_by[(b, c)] = "roots"
        chapter_refs.setdefault((b, c), []).extend([source_ref[s_id], ref])
        if score > chapter_best.get((b, c), (0,))[0]:
            chapter_best[(b, c)] = (score, s_id, ref, shared, order, source_order[s_id])

    # -- the other languages, by English stem ---------------------------------
    # On a Strong's build the pass above never crosses the testaments
    # (H5104 river is not G4215 river), so Ezekiel 47 would never find
    # Revelation 22; nor does it cross from Daniel's Aramaic chapters to
    # the Hebrew books.  The same test is run again with the English
    # stems of the words, against the verses in another language than
    # the source verse's: the source verse's rare stems (1 in 2,000
    # across the Bible, on the English count) against every verse there
    # holding one of them.
    if atlas.roots_mode == "strongs":
        stems, surfaces = atlas.english_stems()
        source_language = {}
        sql = ("SELECT t.verse_id, v.reference, t.surface FROM tokens t JOIN verses v USING (verse_id) "
               "WHERE v.book = ? AND v.chapter = ? AND t.is_stop = 0")
        params = [book, chapter]
        if v_from:
            sql += " AND v.verse BETWEEN ? AND ?"
            params += [v_from, v_to]
        sql += " ORDER BY t.verse_id, t.position"
        en_source, en_order = {}, {}
        for verse_id, reference, surface in atlas.db.execute(sql, params):
            stem = surfaces.get(surface.lower()) or atlas.stemmer.root(surface.lower())
            if atlas.english_rarity(stem) >= threshold:
                en_source.setdefault(verse_id, set()).add(stem)
                en_order.setdefault(verse_id, []).append(stem)
                source_ref[verse_id] = reference
                source_language[verse_id] = atlas.language_of(reference, book)
        en_pairs = {}
        en_meta = {}
        for s_id, s_stems in en_source.items():
            for stem in s_stems:
                for t_id in stems.get(stem, ()):
                    if t_id not in en_meta:
                        row = atlas.db.execute(
                            "SELECT book, chapter, reference FROM verses WHERE verse_id = ?", (t_id,)).fetchone()
                        en_meta[t_id] = (row[0], row[1], row[2], atlas.language_of(row[2], row[0]))
                    if en_meta[t_id][3] == source_language[s_id] or en_meta[t_id][0] == book:
                        continue                  # same language: the root pass covers it; own book: 6c
                    en_pairs.setdefault((s_id, t_id), set()).add(stem)
        for (s_id, t_id), shared in sorted(en_pairs.items(), key=lambda kv: (kv[0][0], atlas.ref_key(en_meta[kv[0][1]][2]))):
            if len(shared) < KIN_MIN_SHARED:
                continue
            target_order = [surfaces.get(r[0].lower()) or atlas.stemmer.root(r[0].lower())
                            for r in atlas.db.execute(
                                "SELECT surface FROM tokens WHERE verse_id = ? AND is_stop = 0 ORDER BY position",
                                (t_id,))]
            target_order = [st for st in target_order if st in shared]
            order = in_order(en_order[s_id], target_order, shared)
            score = sum(atlas.english_rarity(st) for st in shared) * (1 + 0.5 * order / len(shared))
            b, c, ref, _ = en_meta[t_id]
            chapter_score[(b, c)] += score
            found_by[(b, c)] = "English"
            chapter_refs.setdefault((b, c), []).extend([source_ref[s_id], ref])
            if score > chapter_best.get((b, c), (0,))[0]:
                chapter_best[(b, c)] = (score, s_id, ref, shared, order, en_order[s_id])

    name = f"kin_{book.lower().replace(' ', '_')}_{chapter}" + (f"_{v_from}-{v_to}" if v_from else "")
    report = Report(name, f"Kin page [{label}] -> verses elsewhere sharing rare words")
    report.notes.append(f"{label}: {len(source)} verses holding {len(roots)} rare content words "
                        f"(1 in 2,000 or rarer across the Bible).")
    strongs = atlas.roots_mode == "strongs"
    sec = report.section(
        "1. Kin chapters",
        ["chapter", "score", "shared", "in order", "strongest pair", "{words shared}"] + (["found by"] if strongs else []),
        note=f"A verse elsewhere is kin when it shares {KIN_MIN_SHARED} or more rare words with one "
             f"verse here.  The pair scores the summed rarity of the shared words, raised by up to "
             f"half when they come in the same order in both verses; a chapter scores the sum of "
             f"its kin pairs.  The strongest pair is shown, its words in the order of the verse here."
             + ("  Within the testament kin is found by Strong's roots; across it, where a Hebrew "
                "root never matches a Greek one, by the English stems of the words instead ('found "
                "by' says which), so a cross-testament row rests on the translators' wording."
                if strongs else ""))
    ranked = sorted(chapter_score.items(),
                    key=lambda kv: (-kv[1], atlas.books.index(kv[0][0]) if kv[0][0] in atlas.books else 99, kv[0][1]))
    for (b, c), total in ranked[:KIN_N]:
        score, s_id, ref, shared, order, seq = chapter_best[(b, c)]
        by = found_by[(b, c)]
        words = ", ".join((r if by == "English" else atlas.form(r))
                          for i, r in enumerate(seq) if r in shared and r not in seq[:i])
        refs = list(dict.fromkeys(chapter_refs[(b, c)]))
        sec.add([f"{b} {c}", round(total, 1), len(shared), order, f"{source_ref[s_id]} / {ref}", words]
                + ([by] if strongs else []),
                refs=refs, link={"book": b, "chapter": c})
    return report
