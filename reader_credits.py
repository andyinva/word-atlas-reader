#!/usr/bin/env python3
"""
reader_credits.py  -  the credits and licences that travel with the Reader

A Word Atlas dataset is built from other people's work as well as the
King James text: a Strong's dictionary, a set of cross references, a
Greek Old Testament, a tagged Greek New Testament and Hebrew Bible, the
links of a rabbinic library.  Each came with a licence, and most ask
for one thing, that they be named.  This file names them, so that the
notice goes wherever a copy of the Reader goes: Help > Credits and
licences shows it in the window, a zip made to give away carries it as
CREDITS.txt, and

    python3 reader_credits.py [dataset.wadb | results.db]

prints it.  Given a dataset (the window gives the one that is open),
the page begins by saying which of the sources that dataset draws on,
found by looking at its tables: a dataset packed without the Greek
layer does not credit the Septuagint.

Standard library only.  The wording of each credit is the wording the
main program's build scripts record with the data.

Author: Andrew Hopkins (with Claude)
"""

import sqlite3
import sys
import zipfile

# ---------------------------------------------------------------------------
# The sources.  Each: a key, the test that says a dataset draws on it
# (a WHERE clause over the sections table, or None for a source every
# dataset has), its name, and the lines of its credit.
# ---------------------------------------------------------------------------

SOURCES = [
    ("kjv", None, "The King James Version",
     ["The text every count is made from.  Public domain (in the United Kingdom the Crown holds",
      "rights in it by letters patent)."]),
    ("strongs", None, "Strong's numbers and dictionary",
     ["The Hebrew and Greek word behind each English word, by the numbers of James Strong's",
      "concordance (1890), public domain.  The dictionary is from the strongs3 project, MIT licence."]),
    ("listed", "columns LIKE '%listed%'", "Cross references (the 'listed' column and its footers)",
     ["Cross references from OpenBible.info (built on the Treasury of Scripture Knowledge), CC BY.",
      "https://www.openbible.info/labs/cross-references/"]),
    ("septuagint", "number IN ('1e', '1f', '4e', '4f') OR title LIKE '%Septuagint%'",
     "The Septuagint (tables 1e, 1f, 4e, 4f: counts and short Greek phrases)",
     ["LXX Rahlfs 1935 (Eliran Wong, CC BY-NC-SA 4.0; CCAT data).",
      "Non-commercial: a dataset with these tables may be given away with this credit, never sold,",
      "and what is made from it is to be shared on the same terms."]),
    ("stepbible", "number IN ('1c', '1e', '1f', '4e', '4f', '7d') OR note LIKE '%STEPBible%' OR note LIKE '%TAGNT%' "
                  "OR note LIKE '%TAHOT%'",
     "The Greek New Testament and the Hebrew Bible, word by word (tables 1c, 4e, 4f, 7d)",
     ["TAGNT, Translators Amalgamated Greek NT (STEPBible / Tyndale House, CC BY 4.0).",
      "TAHOT, Translators Amalgamated Hebrew OT (STEPBible / Tyndale House, CC BY 4.0).",
      "Verse maps built from TVTMS by STEPBible.org, based on work at Tyndale House, Cambridge; CC BY 4.0.",
      "Credit STEP Bible, www.STEPBible.org; https://github.com/STEPBible/STEPBible-Data"]),
    ("cited", "columns LIKE '%cited%'", "The rabbinic library's citations (the 'cited' column and its footers)",
     ["Counts derived from the links of Sefaria's library, https://www.sefaria.org: how many passages of",
      "the Mishnah, the Talmuds, the Midrash and the commentators cite two verses together.  References",
      "and counts only; none of Sefaria's texts is included.  This project is not affiliated with Sefaria."]),
    ("translations", "columns LIKE '%translations%'",
     "Other English translations (the 'translations' and 'families' columns)",
     ["How many of the older English translations keep an echo the King James finds by wording.  All",
      "were published before 1930 and are out of copyright; only counts and names appear, never their text."]),
]

PROGRAMS = [
    "Word Atlas and the Word Atlas Reader are by Andrew Hopkins, written with Claude (Anthropic), and are",
    "released under the MIT licence: https://github.com/andyinva/word-atlas and .../word-atlas-reader",
    "",
    "They run on Python (Python Software Foundation licence), on Qt 6 (The Qt Company; LGPL v3 or GPL) and",
    "on PyQt6 (Riverbank Computing; GPL v3).  A copy that carries PyQt6 with it, as a USB drive made by",
    "the Reader does, is passed on under the GPL's terms: free of charge or not, the programs' source",
    "must stay available, as it is at the addresses above (PyQt6's own is at riverbankcomputing.com).",
    "",
    "Ask Claude sends your question, and the rows it asks for, to Anthropic's API under your own key (or a",
    "guest key the copy carries); nothing is sent unless you press the button.",
]

PASSING_ON = [
    "You may give a copy of the Reader and of this dataset to anyone, free of charge, with this page.",
    "Do not sell a dataset that holds the Septuagint tables: that source is licensed for non-commercial",
    "use only.  If you publish figures from the dataset, name the sources above that they rest on.",
]


# ---------------------------------------------------------------------------
# Which sources a dataset draws on
# ---------------------------------------------------------------------------

def open_dataset(path):
    """A read-only connection to a results database, given the .db itself or a .wadb that holds it; None if neither."""
    if zipfile.is_zipfile(path):
        # Unpacked by the Reader already when it has been opened; this is
        # for the command line, which reads the database out into memory
        import os
        import tempfile
        folder = tempfile.mkdtemp(prefix="word_atlas_credits_")
        with zipfile.ZipFile(path) as z:
            if "results.db" not in z.namelist():
                return None
            path = z.extract("results.db", folder)
    try:
        db = sqlite3.connect("file:" + path.replace("\\", "/") + "?mode=ro", uri=True)
        db.execute("SELECT 1 FROM sections LIMIT 1")
        return db
    except sqlite3.Error:
        return None


def sources_in(db):
    """
    The keys of the sources a dataset draws on, in the order of the
    list above.  A source with no test is in every dataset; the others
    are found by a look at the sections table (a column called listed,
    a table numbered 4e), so the answer is right for the file in hand
    whatever version packed it.
    """
    found = []
    for key, test, _, _ in SOURCES:
        if test is None:
            found.append(key)
            continue
        try:
            if db.execute(f"SELECT 1 FROM sections WHERE {test} LIMIT 1").fetchone():
                found.append(key)
        except sqlite3.Error:
            pass                        # an older layout without that column: the source is not there
    return found


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def credits_text(db=None, dataset_name=""):
    """
    The credits page as plain text.  With a dataset's connection the
    page says first which sources that dataset draws on and lists
    those in full, the rest briefly; without one it lists them all.
    """
    lines = ["WORD ATLAS  -  credits and licences", "=" * 35, ""]
    used = sources_in(db) if db is not None else [key for key, _, _, _ in SOURCES]
    if db is not None:
        lines.append(f"The dataset {dataset_name} draws on:" if dataset_name else "This dataset draws on:")
        for key, _, name, _ in SOURCES:
            if key in used:
                lines.append(f"    {name}")
        unused = [name for key, _, name, _ in SOURCES if key not in used]
        if unused:
            lines.append("It holds nothing from: " + "; ".join(n.split(" (")[0] for n in unused) + ".")
        lines.append("")
    lines += ["The sources", "-----------"]
    for key, _, name, credit in SOURCES:
        if key not in used:
            continue
        lines.append(name)
        lines += ["    " + c for c in credit]
        lines.append("")
    lines += ["The programs", "------------"] + PROGRAMS + [""]
    lines += ["Passing it on", "-------------"] + PASSING_ON + [""]
    return "\n".join(lines)


def main(argv):
    if len(argv) > 1 and argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    db = None
    name = ""
    if len(argv) > 1:
        import os
        db = open_dataset(argv[1])
        name = os.path.basename(argv[1])
        if db is None:
            print(f"{argv[1]} is not a Word Atlas dataset; the credits for every source follow.\n")
    print(credits_text(db, name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
