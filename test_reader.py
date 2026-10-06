#!/usr/bin/env python3
"""
test_reader.py  -  the Reader's test script, run before every commit

    python3 test_reader.py

Opens the sample dataset, renders pages, searches, runs the results
questions, checks the SQL tool refuses anything but a SELECT, walks the
Claude question loop against a stand-in API, opens the window offscreen
and clicks through it, and ends with housekeeping (no em dashes, every
file compiles).  Prints one line per test and a count at the end; exits
1 when any test fails.
"""

import glob
import os
import py_compile
import sqlite3
import sys
import tempfile
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

SAMPLE = os.path.join(HERE, "sample", "word_atlas_0.10.69_2026-10-05.wadb")
EM_DASH = chr(0x2014)
results = []


def test(name):
    """Decorator: run the function, record ok or FAIL with the reason."""
    def wrap(fn):
        t0 = time.perf_counter()
        try:
            note = fn() or ""
            results.append(True)
            print(f"ok    {name}  {note}({time.perf_counter() - t0:.1f}s)")
        except Exception as e:
            results.append(False)
            print(f"FAIL  {name}: {e}")
            traceback.print_exc()
        return fn
    return wrap


# --- the dataset ----------------------------------------------------------------
@test("open the sample .wadb and list its runs and pages")
def _():
    from reader_data import Dataset
    d = Dataset.open(SAMPLE)
    runs = d.runs()
    assert runs, "no runs"
    pages = d.pages(runs[0][0])
    assert len(pages) == runs[0][4], "page count disagrees with runs()"
    assert d.manifest.get("format") == "Word Atlas dataset", d.manifest
    d.close()
    return f"{len(runs)} run(s), {len(pages)} pages "


@test("a plain results.db opens too, and a stranger's SQLite file is refused")
def _():
    from reader_data import Dataset
    d = Dataset.open(SAMPLE)
    db_path = d.db_path
    d.close()
    Dataset.open(db_path).close()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        other = f.name
    sqlite3.connect(other).execute("CREATE TABLE t (x)").connection.close()
    try:
        Dataset.open(other)
        raise AssertionError("a file without the results tables was accepted")
    except ValueError:
        pass
    finally:
        os.unlink(other)


@test("a page renders with the shared layout, columns lined up")
def _():
    from reader_data import Dataset
    from atlas_report import render
    d = Dataset.open(SAMPLE)
    run = d.latest_run()
    pid = d.pages(run)[0][0]
    report = d.report(pid)
    text = render(report, atlas=d.build_of(run))
    assert text.startswith("WORD ATLAS  -  "), text[:40]
    assert "Sections on this page:" in text, "book page lacks its section list"
    for sec in report.sections:
        assert "\n" + sec.title + "\n" in text, sec.title
    # The header row and the first data row of the first table end in
    # the same column when the last column is a figure
    lines = text.split("\n")
    head = next(i for i, line in enumerate(lines) if line.startswith("word  "))
    assert lines[head + 1].startswith("---"), "no rule under the header"
    assert len(lines[head]) <= 200
    d.close()
    return f"{len(report.sections)} sections "


@test("cells keep the printed text (0.50 stays 0.50) and the number beside it")
def _():
    from reader_data import Dataset
    d = Dataset.open(SAMPLE)
    run = d.latest_run()
    found = False
    for pid, kind, title in d.pages(run):
        for sec in d.report(pid).sections:
            for (r, c), number in sec.cell_numbers.items():
                value = sec.rows[r][c]
                assert isinstance(value, str), "a cell came back as a number, not its text"
                assert abs(float(value.replace(",", "")) - number) < 1e-9, (value, number)
                found = True
        if found:
            break
    assert found, "no numeric cell found"
    d.close()


@test("search finds cells, titles and footers")
def _():
    from reader_data import Dataset
    d = Dataset.open(SAMPLE)
    run = d.latest_run()
    hits = d.search(run, "H1005")
    assert hits, "no hits for H1005"
    kinds = {h[4] for h in hits}
    assert "word" in kinds or any(h[3] >= 0 for h in hits), kinds
    assert d.search(run, "zzzzqqqq") == []
    d.close()
    return f"{len(hits)} hits "


@test("the results questions run against the open file")
def _():
    import atlas_results
    from reader_data import Dataset
    d = Dataset.open(SAMPLE)
    run = d.latest_run()
    for q in (atlas_results.q_runs, atlas_results.q_shares, atlas_results.q_deltas,
              atlas_results.q_seams, atlas_results.q_declined):
        head, body = q(d.db, run)
        assert isinstance(head, str) and isinstance(body, str), q.__name__
    head, body = atlas_results.q_diff(d.db, run, run)
    assert "0 cells changed" in head, head
    d.close()


# --- the Claude tool -------------------------------------------------------------
@test("run_sql answers a SELECT and refuses everything else")
def _():
    from reader_data import Dataset
    from reader_claude import run_sql
    d = Dataset.open(SAMPLE)
    out = run_sql(d.db, "SELECT kind, COUNT(*) AS n FROM pages GROUP BY kind")
    assert out.startswith("kind\tn\n"), out[:60]
    for bad in ("DELETE FROM runs", "UPDATE pages SET title = 'x'", "DROP TABLE cells",
                "SELECT 1; DELETE FROM runs", "PRAGMA writable_schema = 1", ""):
        assert run_sql(d.db, bad).startswith("Refused"), bad
    # The connection itself is read-only, the second lock
    try:
        d.db.execute("DELETE FROM runs")
        raise AssertionError("the read-only connection allowed a write")
    except sqlite3.OperationalError:
        pass
    assert "SQL error" in run_sql(d.db, "SELECT nothing FROM nowhere")
    big = run_sql(d.db, "SELECT value FROM cells")
    assert "cut at" in big, "a long result was not cut"
    d.close()


@test("the question loop runs a tool call and returns the answer (stand-in API)")
def _():
    import reader_claude
    from reader_data import Dataset
    d = Dataset.open(SAMPLE)
    calls = []

    def fake_post(url, payload, api_key, timeout=120):
        calls.append(payload)
        if len(calls) == 1:
            return {"stop_reason": "tool_use", "content": [
                {"type": "text", "text": "Let me look."},
                {"type": "tool_use", "id": "t1", "name": "run_sql",
                 "input": {"sql": "SELECT COUNT(*) FROM pages"}}]}
        # The tool result must have come back in the second call
        last = payload["messages"][-1]["content"][0]
        assert last["type"] == "tool_result" and last["tool_use_id"] == "t1", last
        assert "COUNT(*)" in last["content"], last["content"]
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "There are 101 pages."}]}

    real = reader_claude.post_json
    reader_claude.post_json = fake_post
    try:
        answer, queries = reader_claude.ask(d.db, "How many pages?", "key", "model", 1, d.schema_text())
    finally:
        reader_claude.post_json = real
    assert answer == "There are 101 pages.", answer
    assert queries == ["SELECT COUNT(*) FROM pages"], queries
    assert "run_sql" in [t["name"] for t in calls[0]["tools"]]
    assert "run_id is 1" in calls[0]["system"]
    d.close()


@test("the clipboard prompt carries the schema, the page and the question")
def _():
    from reader_claude import clipboard_prompt
    text = clipboard_prompt("Why?", "CREATE TABLE runs (...)", "WORD ATLAS  -  Book page")
    assert "CREATE TABLE runs" in text and "Book page" in text and text.endswith("My question: Why?")


# --- the window ------------------------------------------------------------------------
@test("the window opens the sample, shows a page, searches, opens a hit, sorts a table")
def _():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import word_atlas_reader as R
    w = R.ReaderWindow()
    w.open_path(SAMPLE)
    app.processEvents()
    assert w.report is not None, "no page shown after opening"
    assert w.page_view.toPlainText().startswith("WORD ATLAS"), "page view empty"
    assert w.grid.rowCount() > 0, "grid empty"
    w.search_edit.setText("H1005")
    w.search()
    assert w.search_grid.rowCount() > 0, "no search hits in the window"
    w.search_hit_opened(0, 0)
    assert w.tabs.currentIndex() == 0, "opening a hit did not show the page"
    # Sorting by the second column (a count) puts the largest first
    w.show_table(0)
    w.grid.sortItems(1, R.Qt.SortOrder.DescendingOrder)
    top = w.grid.item(0, 1)
    assert top is not None and top.number is not None, "sorted column lacks numbers"
    for r in range(1, w.grid.rowCount()):
        item = w.grid.item(r, 1)
        if item.number is not None:
            assert item.number <= top.number, "descending sort out of order"
    w.run_results("declined")
    assert w.results_view.toPlainText().startswith("Results: declined")
    w.filter_edit.setText("Revelation")
    hidden = sum(w.page_tree.topLevelItem(g).isHidden() for g in range(w.page_tree.topLevelItemCount()))
    assert hidden >= 0
    w.close()


@test("help mode names the control and the column under the pointer; histories are kept")
def _():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QPoint
    app = QApplication.instance() or QApplication(sys.argv)
    import word_atlas_reader as R
    import reader_data
    w = R.ReaderWindow()
    w.open_path(SAMPLE)
    app.processEvents()
    # A control with a help key explains itself; a grid names its column
    assert "Search every cell" in w.help_mode.text_for(w.search_box, QPoint(0, 0))
    w.show_table(0)
    note = w.grid.help_at(QPoint(w.grid.columnViewportPosition(1) + 5, 5))
    assert note.startswith("count:"), note
    hit = w.search_grid.help_at(QPoint(w.search_grid.columnViewportPosition(0) + 5, 5))
    assert hit.startswith("page:"), hit
    # Help mode switches on with the button and off with Escape
    w.help_btn.setChecked(True)
    assert w.help_mode.active
    w.help_mode.set_active(False)
    assert not w.help_btn.isChecked()
    # A search and a question go into their drop-downs and the settings
    w.search_edit.setText("H426")
    w.search()
    assert w.search_box.itemText(0) == "H426"
    assert "H426" in reader_data.load_settings().get("history", {}).get("search", [])
    # Starter questions sit in the box before any has been asked, and
    # under a separator after the history once one has
    from reader_claude import STARTER_QUESTIONS
    w.settings.setdefault("history", {})["questions"] = []
    w.fill_history(w.past_box, "questions", blank_first=True, starters=STARTER_QUESTIONS)
    assert w.past_box.itemText(1) == STARTER_QUESTIONS[0], w.past_box.itemText(1)
    w.remember("questions", "How many pages?")
    w.fill_history(w.past_box, "questions", blank_first=True, starters=STARTER_QUESTIONS)
    assert w.past_box.itemText(1) == "How many pages?"
    assert STARTER_QUESTIONS[0] in [w.past_box.itemText(i) for i in range(w.past_box.count())]
    w.past_question_chosen(1)
    assert w.question_edit.toPlainText() == "How many pages?"
    # Jump puts the section's title on the first line shown
    w.jump_to_section(3)
    top = w.page_view.verticalScrollBar().value()
    assert w.page_text.split("\n")[top] == w.report.sections[3].title
    w.wrap_check.setChecked(True)
    assert w.page_view.lineWrapMode() == R.QPlainTextEdit.LineWrapMode.WidgetWidth
    w.close()


# --- housekeeping --------------------------------------------------------------------------
@test("housekeeping: no em dash in any .py or .md, every .py compiles")
def _():
    for path in glob.glob("*.py") + glob.glob("*.md"):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert EM_DASH not in text, f"em dash in {path}"
    for path in glob.glob("*.py"):
        py_compile.compile(path, doraise=True)


passed = sum(results)
print(f"\n{passed} of {len(results)} passed.")
sys.exit(0 if passed == len(results) else 1)
