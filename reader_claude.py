#!/usr/bin/env python3
"""
reader_claude.py  -  asking Claude questions of a dataset

The Reader can send a question to Claude with one tool in hand: a
read-only SQL query against the open results database.  Claude reads
the schema in its instructions, writes the query, reads the rows back,
and answers in words, naming the page and table the figures came from.
The dataset itself is never sent whole; only the rows Claude asks for
travel, which keeps a question to a few cents.

The call goes straight to the Anthropic Messages API over HTTPS with
the standard library (urllib), so the Reader needs no extra package
installed.  The user supplies their own API key, which the Reader
keeps in its settings file in the home folder and nowhere else.

The question runs on a worker thread so the window stays alive while
Claude thinks; the panel in word_atlas_reader.py wires the signals.
"""

import json
import re
import sqlite3
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, QThread, pyqtSignal

API_URL = "https://api.anthropic.com/v1/messages"
MODELS_URL = "https://api.anthropic.com/v1/models"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-5"   # the settings dialog can fetch the current list and change this
MAX_TOOL_CALLS = 8                    # how many queries one question may run
ROW_LIMIT = 200                       # rows a query returns to Claude at most
TEXT_LIMIT = 24000                    # characters of query result at most

# Only a reading statement may run.  The connection is read-only as
# well (mode=ro in reader_data), so this check is the second lock on
# the same door.
READ_ONLY = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

SYSTEM_PROMPT = """You are answering questions about a Word Atlas results dataset: a SQLite
database holding the tables of report pages that the Word Atlas program
wrote about the King James Bible (keyness of words, function-word
profiles, phrase echoes, Septuagint leanings, and so on).

You have one tool, run_sql, which runs a read-only SQL query (SQLite
dialect) against the database and returns the rows.  Use it as often as
you need, then answer in plain prose.  Say which page and table (section
number and title) each figure comes from, so the reader can open it.
When a question cannot be answered from the data, say so rather than
guessing.  Do not use em dashes.

The schema:

{schema}

Notes on the data:
- runs: one row per run of the program (a version, a build line, a start
  time).  Pages belong to a run.  The newest run is usually wanted; its
  run_id is {run_id}.
- pages.kind is Book, Chapter, Section, Passage, Word, Kin, Testament or
  Compare; pages.title is what the page is called, with the subject in
  square brackets, like 'Book page [Isaiah] (KJV)'.
- sections: one table on a page.  number is the table's number on the
  page ('1', '1a', '4e', '7d'); columns holds the column names separated
  by tab characters; note is the paragraph under the title.
- cells: one cell per row and column.  value is the text as printed;
  number is the same as a number when the cell is numeric, else NULL.
  Filter by column name (cells.column) and compare cells.number for
  arithmetic.
- footers: the lines printed under a table (findings in words).
- refs: the verse references behind a row.

The tables most questions want, by sections.number (titles vary by book):
- Book page: 1 signature words (keyness against the rest of the testament),
  1b against the book's kind, 1c function-word profile, 1d vocabulary
  richness, 1e/1f Septuagint vocabulary and leanings (New Testament books),
  2 signature formulas, 3.1 to 3.5 neighbors of the leading words,
  4 echoes with other books, 4a echo partners, 4a2 who reads whom,
  4b echoes by chapter, 4e Septuagint echoes in Greek, 4f English echoes
  not confirmed in Greek, 5 reach and depth, 6 echoes within the book,
  6b refrains, 6c kin chapters, 6d shared vocabulary, 7 sections
  (parts of the book), 7b section against section, 7c reach and depth by
  section, 7d function words by section (Burrows' Delta of each part
  from the rest; the footers give the yardsticks and pairwise distances).
- Chapter page: leading words, signature words, formulas, parallels.
- Compare page: two books against each other, shared formulas and refrains.
- Section page: one part of a book (or a cross-book group) with the same
  numbering as a book page.
Start from the section number when the question names a measure, and from
sections.title LIKE '%word%' only when it does not.

When the reader asks what the dataset holds or what can be asked, query
the pages table for the books and kinds present and suggest questions
that those pages can answer.  When the reader asks what a section or a
measure is, explain it from the guide above and from the section's own
note (sections.note), which says what the table measures and how to
read it, in plain words a newcomer can follow.

Keep each query small: filter by run_id, page kind, section number and
column, and use LIMIT.  At most {row_limit} rows come back from a query.
"""

# Questions offered in the Past questions box before the reader has asked
# any, so the box is never empty and the first one explains the rest
STARTER_QUESTIONS = [
    "What can I ask about this dataset?",
    "What are the sections on a book page, and what does each one measure?",
    "Which books and kinds of page does this file hold?",
    "Which part of Revelation stands furthest from the rest of the book in its function words?",
    "What are the top five signature words of Ezra, and what makes a word a signature word?",
    "Which chapters of 1 Kings echo other books most, and which books?",
    "Which New Testament book in this file leans most on the Septuagint's vocabulary?",
    "Which tables declined to measure something, and why?",
]

RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": "Run a read-only SQL query (SQLite) against the Word Atlas results database and get the rows back.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "One SELECT (or WITH ... SELECT) statement."}
        },
        "required": ["sql"],
    },
}


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------

def run_sql(db, sql):
    """
    Run one reading statement and return its rows as text for Claude:
    a header line of column names, then one tab-separated line per row,
    cut off at ROW_LIMIT rows and TEXT_LIMIT characters.  Any error
    comes back as text too, so Claude can mend the query and try again.
    """
    if not READ_ONLY.match(sql or ""):
        return "Refused: only a SELECT or WITH statement may run; the dataset is read-only."
    if ";" in sql.rstrip().rstrip(";"):
        return "Refused: one statement at a time."
    try:
        cur = db.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(ROW_LIMIT + 1)
    except sqlite3.Error as e:
        return f"SQL error: {e}"
    lines = ["\t".join(columns)]
    for row in rows[:ROW_LIMIT]:
        lines.append("\t".join("" if v is None else str(v) for v in row))
    if len(rows) > ROW_LIMIT:
        lines.append(f"... (cut at {ROW_LIMIT} rows; add a WHERE or a LIMIT)")
    text = "\n".join(lines)
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT] + "\n... (cut: the result was too long)"
    return text


# ---------------------------------------------------------------------------
# The API call
# ---------------------------------------------------------------------------

def post_json(url, payload, api_key, timeout=120):
    """POST a JSON body to the API and return the parsed reply; errors become ApiError."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            message = json.loads(body).get("error", {}).get("message", body)
        except ValueError:
            message = body
        raise ApiError(f"HTTP {e.code}: {message}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"Could not reach the API: {e.reason}") from None


def list_models(api_key, timeout=30):
    """The model ids the key can use, newest first, for the settings dialog."""
    req = urllib.request.Request(MODELS_URL, headers={"x-api-key": api_key, "anthropic-version": API_VERSION})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            reply = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ApiError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"Could not reach the API: {e.reason}") from None
    return [m["id"] for m in reply.get("data", [])]


class ApiError(Exception):
    """Anything that stops a question being answered, in one sentence."""


def ask(db, question, api_key, model, run_id, schema, progress=None):
    """
    Put one question to Claude and return (answer text, list of queries
    run).  progress, when given, is called with a line of text each time
    Claude runs a query, so the panel can show the work as it happens.
    """
    system = SYSTEM_PROMPT.format(schema=schema, run_id=run_id, row_limit=ROW_LIMIT)
    messages = [{"role": "user", "content": question}]
    queries = []
    for _ in range(MAX_TOOL_CALLS + 1):
        reply = post_json(API_URL, {
            "model": model,
            "max_tokens": 2000,
            "system": system,
            "tools": [RUN_SQL_TOOL],
            "messages": messages,
        }, api_key)
        content = reply.get("content", [])
        messages.append({"role": "assistant", "content": content})
        if reply.get("stop_reason") != "tool_use":
            # The answer: the text blocks, joined
            answer = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            return answer or "(no answer came back)", queries
        # Run every tool call in the turn and hand the results back
        results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue
            sql = block.get("input", {}).get("sql", "")
            queries.append(sql)
            if progress:
                progress(sql)
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": run_sql(db, sql)})
        messages.append({"role": "user", "content": results})
    return "Claude ran more queries than the Reader allows for one question; try a narrower question.", queries


def clipboard_prompt(question, schema, page_text=None):
    """
    For a user without an API key: a prompt to paste into claude.ai
    (or any assistant) that carries the schema and, when a page is open,
    its text, so the question can still be asked by hand.
    """
    parts = ["I have a question about a Word Atlas results dataset (tables of report pages "
             "about the King James Bible).  Its SQLite schema is:\n\n" + schema]
    if page_text:
        parts.append("The page I am looking at reads:\n\n" + page_text)
    parts.append("My question: " + question)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# The worker: one question on its own thread
# ---------------------------------------------------------------------------

class AskWorker(QObject):
    """Runs ask() off the GUI thread and reports back through signals."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(str, list)     # answer, queries
    failed = pyqtSignal(str)

    def __init__(self, db_path, question, api_key, model, run_id, schema):
        super().__init__()
        # The worker opens its own read-only connection: a sqlite3
        # connection should stay on the thread that made it
        self.db_path = db_path
        self.question = question
        self.api_key = api_key
        self.model = model
        self.run_id = run_id
        self.schema = schema

    def run(self):
        db = None
        try:
            uri = "file:" + self.db_path.replace("\\", "/") + "?mode=ro"
            db = sqlite3.connect(uri, uri=True)
            answer, queries = ask(db, self.question, self.api_key, self.model, self.run_id, self.schema,
                                  progress=self.progress.emit)
            self.finished.emit(answer, queries)
        except ApiError as e:
            self.failed.emit(str(e))
        except Exception as e:     # anything else, so the thread never dies silently
            self.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            if db is not None:
                db.close()


def start_worker(parent, db_path, question, api_key, model, run_id, schema):
    """Make a thread and a worker, start them, and return both (the caller keeps them alive)."""
    thread = QThread(parent)
    worker = AskWorker(db_path, question, api_key, model, run_id, schema)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.start()
    return thread, worker
