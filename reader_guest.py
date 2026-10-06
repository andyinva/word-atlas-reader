#!/usr/bin/env python3
"""
reader_guest.py  -  a guest key built into a copy of the Reader

A copy of the Reader given away can carry a guest API key, so the
person receiving it can ask Claude questions for a while without a key
of their own.  The key is kept in guest_key.dat beside the program,
scrambled and tied to an end date; the Reader uses it until that date
and never shows it on screen, and a key the user enters themselves
takes its place.

To make one:

    python3 reader_guest.py make sk-ant-...  15

writes guest_key.dat good for 15 days from today (the dat file, not
the key, is what goes in the copy).  `python3 reader_guest.py show`
says whether a guest key is present and when it ends.

What this does and does not protect.  The scrambling stops the key
being read off the screen or out of the settings file, and the end
date stops the Reader using it afterwards.  It does not make the key
unrecoverable: the program must unscramble it to send it, so a
determined reader with the file and the source can get it out, and
any program's network traffic can be watched.  The real protections
are on the Anthropic side, and the guest key should be made that way:

  1. In console.anthropic.com make a separate workspace for guests and
     give it a monthly spending limit (a few dollars is plenty: a
     question costs cents).
  2. Make the key in that workspace, not in your own.
  3. On the end date, delete the key in the console.  The date in the
     dat file is a courtesy the Reader keeps; the deletion is the one
     nobody can get around.

Treat the guest key as a small prepaid card, not as a secret.
"""

import base64
import datetime
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GUEST_PATH = os.path.join(HERE, "guest_key.dat")

# The scrambling pad is derived from a fixed phrase: enough to keep the
# key out of plain sight, no more (see the note above)
PAD_PHRASE = b"word atlas reader guest key"


def _pad(length):
    """A byte pad of the wanted length, from the phrase hashed and rehashed."""
    out = b""
    block = PAD_PHRASE
    while len(out) < length:
        block = hashlib.sha256(block).digest()
        out += block
    return out[:length]


def _scramble(text):
    raw = text.encode("utf-8")
    pad = _pad(len(raw))
    return base64.b64encode(bytes(a ^ b for a, b in zip(raw, pad))).decode("ascii")


def _unscramble(blob):
    raw = base64.b64decode(blob.encode("ascii"))
    pad = _pad(len(raw))
    return bytes(a ^ b for a, b in zip(raw, pad)).decode("utf-8")


def make(key, days, path=GUEST_PATH, note=""):
    """Write a guest key file good for the given number of days from today."""
    key = key.strip()
    if not key.startswith("sk-ant-"):
        sys.exit("That does not look like an Anthropic API key (they begin sk-ant-)")
    until = (datetime.date.today() + datetime.timedelta(days=int(days))).isoformat()
    record = {"format": "Word Atlas Reader guest key", "until": until, "note": note,
              "key": _scramble(key), "check": hashlib.sha256(key.encode()).hexdigest()[:12]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return until


def load(path=GUEST_PATH):
    """
    The guest key and its end date as (key, until), or (None, until)
    when the file is missing, damaged or past its date; until is None
    when there is no file at all.
    """
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        until = record["until"]
        key = _unscramble(record["key"])
        if hashlib.sha256(key.encode()).hexdigest()[:12] != record.get("check"):
            return None, until
    except (OSError, ValueError, KeyError):
        return None, None
    if datetime.date.today().isoformat() > until:
        return None, until
    return key, until


def days_left(until):
    """Whole days from today to the end date (0 on the last day)."""
    end = datetime.date.fromisoformat(until)
    return (end - datetime.date.today()).days


def main(argv):
    if len(argv) >= 4 and argv[1] == "make":
        until = make(argv[2], argv[3], note=" ".join(argv[4:]))
        print(f"Wrote {GUEST_PATH}, good until {until}.  Remember to delete the key in the console on that day.")
    elif len(argv) == 2 and argv[1] == "show":
        key, until = load()
        if until is None:
            print("No guest key file.")
        elif key is None:
            print(f"A guest key file is present but ended on {until} (or is damaged).")
        else:
            print(f"A guest key is present, good until {until} ({days_left(until)} days left).")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
