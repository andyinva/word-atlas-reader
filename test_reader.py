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
import site
import sys
import tempfile
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

# The tests keep to a home folder of their own, made here and thrown
# away at the end (0.3.10).  Set before reader_data is first imported,
# it sends the Reader's settings, its unpacked datasets and its own
# datasets folder there, so a test run changes nothing of the real
# Reader's: the dataset it opens next time is the one it had open
# before, not the sample the tests used.
import atexit
import shutil
TEST_HOME = tempfile.mkdtemp(prefix="word_atlas_reader_tests_")
os.environ["WORD_ATLAS_READER_HOME"] = TEST_HOME
atexit.register(shutil.rmtree, TEST_HOME, ignore_errors=True)

# The dataset the tests read: the newest in sample/ (the one the
# repository carries), or, in a copy that has no sample folder (a zip
# made to give away), the newest in its datasets folder
import glob
SAMPLE = (sorted(glob.glob(os.path.join(HERE, "sample", "*.wadb")), key=os.path.getmtime) or
          sorted(glob.glob(os.path.join(HERE, "datasets", "*.wadb")), key=os.path.getmtime) or
          [os.path.join(HERE, "sample", "word_atlas_0.10.69_2026-10-05.wadb")])[-1]


def a_root_in(dataset):
    """A Strong's number the dataset holds (H1005 in the Ezra sample; whatever the file has), for the search tests."""
    row = dataset.db.execute("SELECT value FROM cells WHERE value GLOB '[HG][0-9]*' AND value NOT GLOB '*[^HG0-9]*' "
                             "LIMIT 1").fetchone()
    return row[0] if row else "H1005"
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
    term = a_root_in(d)
    hits = d.search(run, term)
    assert hits, f"no hits for {term}"
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
              atlas_results.q_seams, atlas_results.q_declined, atlas_results.q_listed, atlas_results.q_idiom,
              atlas_results.q_cited):
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
    # The window keeps the answer and saves it as text with the queries
    import word_atlas_reader as R
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    w = R.ReaderWindow()
    w.open_path(SAMPLE)
    w.question_edit.setPlainText("How many pages?")
    assert not w.save_answer_button.isEnabled()
    w.answered(answer, queries)
    assert w.save_answer_button.isEnabled()
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "a.txt")
        w._save_text = lambda text, suggested, title: open(out, "w", encoding="utf-8").write(text)
        w.save_answer()
        saved = open(out, encoding="utf-8").read()
    assert "How many pages?" in saved and "There are 101 pages." in saved and "SELECT COUNT(*) FROM pages" in saved
    assert saved.startswith("WORD ATLAS READER")
    w.close()
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
    w.search_edit.setText(a_root_in(w.data))
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
    # The Search button is green while the box holds an unsent search,
    # plain after the search runs or the box is emptied
    w.search_edit.setText("H426")
    assert w.search_button.styleSheet(), "Search button not green with text waiting"
    w.search()
    assert not w.search_button.styleSheet(), "Search button still green after the search"
    w.search_edit.setText("H426 ")
    assert not w.search_button.styleSheet(), "the same search again should not be green"
    w.search_edit.setText("H427")
    assert w.search_button.styleSheet()
    w.search_edit.setText("")
    assert not w.search_button.styleSheet()
    w.search_edit.setText("H426")
    w.search()
    # The Questions dialog lists the whole file of questions, filters, and hands one back
    import reader_questions
    d = R.QuestionsDialog(w)
    rows = [d.list.item(i) for i in range(d.list.count())]
    picks = [r for r in rows if r.data(R.Qt.ItemDataRole.UserRole)]
    assert len(picks) == len(reader_questions.all_questions()) >= 200, len(picks)
    d.filter_edit.setText("Septuagint")
    rows = [d.list.item(i) for i in range(d.list.count())]
    picks = [r for r in rows if r.data(R.Qt.ItemDataRole.UserRole)]
    assert picks and all("septuagint" in p.data(R.Qt.ItemDataRole.UserRole).lower() for p in picks)
    d.pick(picks[0])
    assert d.chosen == picks[0].data(R.Qt.ItemDataRole.UserRole)
    # The Ask button likewise, for the question box
    w.question_edit.setPlainText("Why?")
    assert w.ask_button.styleSheet(), "Ask button not green with a question waiting"
    w.question_edit.setPlainText("")
    assert not w.ask_button.styleSheet()
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


@test("a guest key round-trips, hides itself, ends on its date, and yields to the user's own key")
def _():
    import reader_guest
    import word_atlas_reader as R
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "guest_key.dat")
        until = reader_guest.make("sk-ant-test-0123456789", 15, path=path)
        text = open(path, encoding="utf-8").read()
        assert "sk-ant-test" not in text, "the key is in plain sight in the file"
        key, got_until = reader_guest.load(path)
        assert key == "sk-ant-test-0123456789" and got_until == until
        assert reader_guest.days_left(until) == 15
        # Past its date it is not handed out
        import json
        record = json.load(open(path, encoding="utf-8"))
        record["until"] = "2000-01-01"
        json.dump(record, open(path, "w", encoding="utf-8"))
        assert reader_guest.load(path) == (None, "2000-01-01")
        # A damaged file yields nothing rather than an error
        open(path, "w").write("not json")
        assert reader_guest.load(path) == (None, None)
        # In the window, the user's own key wins over the guest key, and the
        # settings dialog never shows the guest key
        real_load = reader_guest.load
        reader_guest.load = lambda path=None: ("sk-ant-guest", "2099-01-01")
        try:
            w = R.ReaderWindow()
            dialog = R.SettingsDialog({"api_key": "sk-ant-mine"}, w)
            assert dialog.key_edit.text() == "sk-ant-mine"
            assert dialog.guest_key == "sk-ant-guest"
            labels = [c.text() for c in dialog.findChildren(R.QLabel)]
            assert not any("sk-ant-guest" in t for t in labels), "the guest key is shown"
            assert any("guest key good until 2099-01-01" in t for t in labels)
            w.close()
        finally:
            reader_guest.load = real_load


# --- the Reader's own datasets ----------------------------------------------------------------
@test("a dataset opened is copied into the Reader's own folder; the sample is never opened at start")
def _():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import reader_data
    import word_atlas_reader as R
    # The tests' own home folder is in force, so nothing here reaches the real Reader's
    assert reader_data.ISOLATED and reader_data.SETTINGS_PATH.startswith(TEST_HOME), reader_data.SETTINGS_PATH
    library = reader_data.library_dir()
    assert library.startswith(TEST_HOME), library
    for path, _ in reader_data.kept_datasets():
        reader_data.forget_dataset(path)
    with tempfile.TemporaryDirectory() as tmp:
        # A dataset that arrives from somewhere else (a download, a drive)
        given = os.path.join(tmp, "word_atlas_given.wadb")
        shutil.copy2(SAMPLE, given)
        w = R.ReaderWindow()
        assert w.open_chosen(given)
        kept = os.path.join(library, "word_atlas_given.wadb")
        assert os.path.exists(kept), "the dataset was not copied into the Reader's folder"
        assert os.path.abspath(w.data.source_path) == os.path.abspath(kept), w.data.source_path
        assert w.settings["last_file"] == kept and w.settings["last_open_dir"] == tmp
        w.close()
        # Given again unchanged: nothing copied.  The file it came from can go: the Reader has its own
        assert reader_data.keep_dataset(given) == (kept, False)
        os.remove(given)
        # A bare results.db is opened where it stands, not copied
        assert reader_data.keep_dataset(reader_data.Dataset._unpack(kept)[0])[1] is False
        # A file that is no dataset is not left behind in the folder
        junk = os.path.join(tmp, "junk.wadb")
        import zipfile
        with zipfile.ZipFile(junk, "w") as z:
            z.writestr("readme.txt", "not a dataset")
        w = R.ReaderWindow()
        real_warning = R.QMessageBox.warning
        R.QMessageBox.warning = lambda *a, **k: None          # the refusal's message box, not shown in a test
        try:
            assert not w.open_chosen(junk)
        finally:
            R.QMessageBox.warning = real_warning
        assert not os.path.exists(os.path.join(library, "junk.wadb")), "a refused file was kept"
        # At start: the last file was the sample (as an earlier test run
        # could leave it), and the Reader opens its own dataset instead
        w.settings["last_file"] = SAMPLE
        w.open_at_start()
        assert w.data is not None and os.path.abspath(w.data.source_path) == os.path.abspath(kept), "opened the sample"
        w.close()
        # A last file outside the Reader's folder (one opened before the
        # Reader kept copies) is brought in at start, and the copy opened
        outside = os.path.join(tmp, "word_atlas_outside.wadb")
        shutil.copy2(SAMPLE, outside)
        w = R.ReaderWindow()
        w.settings["last_file"] = outside
        w.open_at_start()
        brought = os.path.join(library, "word_atlas_outside.wadb")
        assert os.path.exists(brought), "a last file outside the Reader's folder was not brought in at start"
        assert os.path.abspath(w.data.source_path) == os.path.abspath(brought) and w.settings["last_file"] == brought
        w.close()
        reader_data.forget_dataset(brought)
        # With no dataset of its own it opens nothing, rather than the sample
        reader_data.forget_dataset(kept)
        assert not os.path.exists(kept) and not reader_data.kept_datasets()
        assert not os.path.exists(os.path.join(reader_data.DATASET_DIR, "word_atlas_given")), "unpacked copy left"
        w = R.ReaderWindow()
        w.settings["last_file"] = SAMPLE
        w.open_at_start()
        assert w.data is None, "the sample was opened at start"
        w.close()


# --- the credits page -----------------------------------------------------------------------
@test("the credits page names the sources a dataset draws on, and only those")
def _():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import reader_credits
    import word_atlas_reader as R
    # With no dataset every source is named
    every = reader_credits.credits_text()
    for word in ("King James", "OpenBible.info", "Rahlfs", "STEPBible", "Sefaria", "MIT licence", "PyQt6"):
        assert word in every, f"{word} missing from the credits"
    # A dataset is credited with what its tables show: one with the listed
    # and cited columns and no Greek tables names the cross references and
    # Sefaria, and not the Septuagint
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE sections (number TEXT, title TEXT, note TEXT, columns TEXT)")
    db.execute("INSERT INTO sections VALUES ('4', 'Echoes [Joel] -> other books', '', 'echo\tverses\tlisted\tcited')")
    assert reader_credits.sources_in(db) == ["kjv", "strongs", "listed", "cited"], reader_credits.sources_in(db)
    text = reader_credits.credits_text(db, "joel.wadb")
    assert "The dataset joel.wadb draws on:" in text and "sefaria.org" in text and "OpenBible.info" in text
    assert "LXX Rahlfs 1935" not in text and "It holds nothing from: The Septuagint" in text, text[:600]
    # A table numbered 4e brings in the Septuagint and STEPBible credits
    db.execute("INSERT INTO sections VALUES ('4e', 'Septuagint echoes', '', 'echo')")
    assert {"septuagint", "stepbible"} <= set(reader_credits.sources_in(db))
    # The sample's own credits open from a .wadb, and the window offers the page on its Help menu
    sample = reader_credits.open_dataset(SAMPLE)
    assert sample is not None and "kjv" in reader_credits.sources_in(sample)
    sample.close()
    assert reader_credits.open_dataset(__file__) is None, "a file that is no dataset was taken for one"
    w = R.ReaderWindow()
    labels = [a.text().replace("&", "") for m in w.menuBar().actions() for a in m.menu().actions()]
    assert "Credits and licences" in labels, labels
    w.close()


# --- the Tools tab and the USB drive ---------------------------------------------------------
@test("the Tools tab reports the dataset, runs a reading query in columns, refuses a writing one")
def _():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QPoint
    app = QApplication.instance() or QApplication(sys.argv)
    import word_atlas_reader as R
    import reader_tools
    w = R.ReaderWindow()
    w.open_path(SAMPLE)
    app.processEvents()
    # The tab is the last one, so the tabs before it keep their numbers
    assert w.tabs.tabText(w.tabs.count() - 1) == "Tools" and w.tabs.tabText(4) == "Ask Claude"
    t = w.tools_tab
    t.dataset_details()
    text = t.output.toPlainText()
    assert "Runs (a run is one pass" in text and "The file reads back sound." in text, text[-300:]
    t.output.clear()
    t.sql_edit.setText("SELECT kind, COUNT(*) AS pages FROM pages GROUP BY kind ORDER BY kind")
    t.run_query()
    lines = t.output.toPlainText().splitlines()
    head = next(i for i, l in enumerate(lines) if l.startswith("kind"))
    assert set(lines[head + 1]) <= {"-", " "}, "no rule under the column headings"
    assert lines[head + 2].split()[0] == "Book" and lines[head + 2].split()[1].isdigit(), lines[head + 2]
    t.sql_edit.setText("DELETE FROM pages")
    t.run_query()
    assert "Refused" in t.output.toPlainText()
    assert w.data.db.execute("SELECT COUNT(*) FROM pages").fetchone()[0] > 0
    t.check_copy()
    assert f"Word Atlas Reader {R.VERSION}" in t.output.toPlainText()
    assert "MISSING" not in t.output.toPlainText(), "a program file is missing from this copy"
    assert "SELECT" in w.help_mode.text_for(t.sql_edit, QPoint(0, 0))
    # The zip to give away: the program, the open dataset, a note on starting
    import zipfile
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "reader.zip")
        reader_tools.make_reader_zip(HERE, t.open_wadb(), out)
        names = zipfile.ZipFile(out).namelist()
        for need in ("word_atlas_reader/word_atlas_reader.py", "word_atlas_reader/reader_tools.py",
                     "word_atlas_reader/reader_credits.py", "word_atlas_reader/CREDITS.txt",
                     "word_atlas_reader/datasets/" + os.path.basename(SAMPLE), "word_atlas_reader/START.txt"):
            assert need in names, f"{need} not in the zip"
        assert "credits and licences" in zipfile.ZipFile(out).read("word_atlas_reader/CREDITS.txt").decode("utf-8")
        assert "word_atlas_reader/guest_key.dat" not in names, "the guest key went along unasked"
    w.close()


@test("a USB drive is made, brought up to date, and installs the Reader with its dataset")
def _():
    import json
    import subprocess
    import atlas_usb
    with tempfile.TemporaryDirectory() as tmp:
        drive, dest, home = (os.path.join(tmp, d) for d in ("drive", "installed", "home"))
        for d in (drive, home):
            os.makedirs(d)
        # The Reader alone, with the sample dataset, and no PyQt6 fetched
        # (sync off: there is no drive to pull out, and flushing every disk can take a minute)
        options = atlas_usb.default_options(None, HERE)
        options.update({"atlas": False, "dataset": SAMPLE, "wheels": False, "sync": False})
        lines = []
        manifest = atlas_usb.build(drive, options, None, HERE, log=lines.append)
        root = atlas_usb.drive_root(drive)
        for need in ("install.py", "Install-Windows.bat", "install-linux.sh", "README.txt",
                     "programs/word_atlas_reader/word_atlas_reader.py", "data/reader/" + os.path.basename(SAMPLE)):
            assert os.path.exists(os.path.join(root, *need.split("/"))), f"{need} not on the drive"
        import word_atlas_reader as R
        assert manifest["reader"]["version"] == R.VERSION and not manifest.get("atlas")
        assert not any("guest_key" in rel for rel in manifest["files"]), "the guest key went along unasked"
        # Made again: nothing to copy
        items, groups = atlas_usb.gather(options, None, HERE)
        plan = atlas_usb.make_plan(root, items, groups, options)
        assert not plan.copy and not plan.remove, plan.summary()
        # A file whose date alone differs (touched, or checked out again) is not copied again ...
        held = atlas_usb.read_manifest(root)
        held["files"]["programs/word_atlas_reader/README.md"]["mtime"] = "1"
        plan = atlas_usb.make_plan(root, items, groups, options, held)
        assert not plan.copy, [i.rel for i in plan.copy]
        # ... and a file whose contents differ is, that file and no other
        held["files"]["programs/word_atlas_reader/README.md"]["sha256"] = "0" * 64
        plan = atlas_usb.make_plan(root, items, groups, options, held)
        assert [i.rel for i in plan.copy] == ["programs/word_atlas_reader/README.md"], [i.rel for i in plan.copy]
        # A newer dataset takes the older one's place on the drive
        newer = os.path.join(tmp, "word_atlas_9.9.9_2099-01-01.wadb")
        with open(SAMPLE, "rb") as fin, open(newer, "wb") as fout:
            fout.write(fin.read())
        options["dataset"] = newer
        atlas_usb.build(drive, options, None, HERE, log=lines.append)
        on_drive = sorted(os.listdir(os.path.join(root, "data", "reader")))
        assert on_drive == [os.path.basename(newer)], on_drive
        assert not atlas_usb.check_drive(drive, log=lines.append), "the drive does not read back sound"
        # The drive's installer, as a new user would run it, with a home folder of its own
        # (--no-pyqt: a test never fetches PyQt6 from the internet)
        env = dict(os.environ, HOME=home, USERPROFILE=home, QT_QPA_PLATFORM="offscreen",
                   # A PyQt6 installed with pip --user lives under the real
                   # home folder; keep it findable when HOME is a stand-in
                   PYTHONUSERBASE=site.getuserbase())
        env.pop("WORD_ATLAS_READER_HOME", None)
        command = [sys.executable, os.path.join(root, "install.py"), "--app", "reader", "--dest", dest,
                   "--yes", "--no-shortcuts", "--no-pyqt"]
        out = subprocess.run(command, capture_output=True, text=True, env=env, timeout=300)
        assert out.returncode == 0, out.stdout[-400:] + out.stderr[-400:]
        # The dataset lands in the installed Reader's own datasets folder
        for need in ("word_atlas_reader/word_atlas_reader.py", "word_atlas_reader/datasets/" + os.path.basename(newer),
                     "start_word_atlas_reader.pyw", "installed.json"):
            assert os.path.exists(os.path.join(dest, *need.split("/"))), f"{need} not installed"
        # The Reader will open the installed dataset on its first start
        with open(os.path.join(home, ".word_atlas_reader", "settings.json"), encoding="utf-8") as f:
            assert json.load(f)["last_file"].endswith(os.path.basename(newer))
        # The installed copy opens the installed dataset
        check = ("import sys; sys.path.insert(0, sys.argv[1]); from reader_data import Dataset; "
                 "d = Dataset.open(sys.argv[2]); print(len(d.runs()))")
        got = subprocess.run([sys.executable, "-c", check, os.path.join(dest, "word_atlas_reader"),
                              os.path.join(dest, "word_atlas_reader", "datasets", os.path.basename(newer))],
                             capture_output=True, text=True, env=env, timeout=120)
        assert got.stdout.strip() == "1", got.stdout + got.stderr
        # Installed again: nothing copied
        out = subprocess.run(command, capture_output=True, text=True, env=env, timeout=300)
        assert "0 file(s) copied" in out.stdout, out.stdout[-300:]
    return f"{len(manifest['files'])} files "


# --- housekeeping --------------------------------------------------------------------------
# --- the Heat tab (0.3.12) ----------------------------------------------------------
def make_heat_dataset(path):
    """
    A small results file of the 0.10.101 kind: one page, two strips of
    one book with their windows and spots, a named passage, and two
    chapters of King James text with their tags.  The real pack is too
    large for the repository; this has every table the Heat tab reads.
    """
    import atlas_report
    db = sqlite3.connect(path)
    atlas_report.ensure_results_schema(db)
    db.executescript(atlas_report.PACK_SCHEMA)
    db.execute("INSERT INTO runs VALUES (1, '0.10.101', 'test build', '2026-10-20 08:00:00', 'test')")
    db.execute("INSERT INTO pages VALUES (1, 1, 'book_ruth', 'Book page [Ruth] (KJV)', 'Book', '')")
    db.execute("INSERT INTO kjv_books VALUES (8, 'Ruth', 'Rth', 'Old')")
    vid = 0
    for ch in (1, 2):
        for v in range(1, 13):
            vid += 1
            db.execute("INSERT INTO kjv_verses VALUES (?, 8, ?, ?, ?)", (vid, ch, v, f"Ruth {ch}:{v} text"))
            db.execute("INSERT INTO kjv_tags VALUES (?, 1, 'H7327', NULL, 'Ruth')", (vid,))
    db.execute("INSERT INTO passages VALUES (1, 'Test passage', 'two ranges', '')")
    db.execute("INSERT INTO passage_ranges VALUES (1, 8, 1, 1, 1, 3)")
    db.execute("INSERT INTO passage_ranges VALUES (1, 8, 2, 4, 2, 5)")
    for strip, kind, roots in (("density", "measure", ""), ("rest", "word list", "H4496 rest\nH5117 rest")):
        db.execute("INSERT INTO heat_strips VALUES (?, 'Old', ?, ?, ?, '2026-10-20')",
                   (strip, kind, f"what {strip} measures", roots))
        for pos in range(15):
            z = 2.5 if (strip == "rest" and 3 <= pos <= 6) else -0.2
            c1, v1 = divmod(pos, 12)
            c2, v2 = divmod(pos + 9, 12)
            db.execute("INSERT INTO heat_windows VALUES ('Ruth', 'z', 'bible', 10, ?, ?, ?, ?, ?, ?, ?)",
                       (strip, pos, c1 + 1, v1 + 1, c2 + 1, v2 + 1, z))
    db.execute("INSERT INTO heat_spots VALUES ('Ruth', 'z', 'bible', 10, 'rest', 'spot', 2.0, 1, 'Ruth 1:4-2:4', "
               "1, 4, 2, 4, 2.5, 'z +2.50', '1:9', \"'rest' 3\")")
    db.commit()
    db.close()


@test("the heat lookups answer from a 0.10.101 file, and an older file answers empty")
def _():
    from reader_data import Dataset
    path = os.path.join(TEST_HOME, "heat_results.db")
    make_heat_dataset(path)
    d = Dataset.open(path)
    assert d.has_heat() and d.has_passages() and d.has_kjv()
    assert d.heat_books() == ["Ruth"], d.heat_books()
    view = d.heat_views("Ruth")[0]
    assert view == ("z", "bible", 10), view
    strips = d.heat_strips("Ruth", view)
    assert [s[0] for s in strips] == ["density", "rest"], strips
    assert strips[1][1] == "word list" and "H5117 rest" in strips[1][3]
    assert len(d.heat_windows("Ruth", view, "rest")) == 15
    spots = d.heat_spots("Ruth", view, "rest")
    assert len(spots) == 1 and spots[0]["words"] == "'rest' 3", spots
    assert d.passage_ranges(1) == [("Ruth", 1, 1, 1, 3), ("Ruth", 2, 4, 2, 5)]
    assert d.book_number("rth") == 8 and d.book_number("ruth") == 8 and d.book_number("Exodus") is None
    verses = d.kjv_range(8, 1, 11, 2, 2, tags=True)
    assert [(c, v) for c, v, t, w in verses] == [(1, 11), (1, 12), (2, 1), (2, 2)], verses
    assert verses[0][3] == [("Ruth", "H7327", None)]
    d.close()
    old = Dataset.open(SAMPLE)
    assert not old.has_heat() and old.heat_books() == [] and old.passages() == [] and old.kjv_range(1, 1, 1, 1, 2) == []
    assert "no heat strips" in old.describe()
    old.close()


@test("references are read as the Heat tab's box takes them")
def _():
    from reader_data import Dataset
    from reader_heat import parse_reference, verse_span
    d = Dataset.open(os.path.join(TEST_HOME, "heat_results.db"))
    assert parse_reference("Ruth 1:4-9", d) == ("Ruth", 1, 4, 1, 9)
    assert parse_reference("ruth 1:4-2:2", d) == ("Ruth", 1, 4, 2, 2)
    assert parse_reference("Ruth 2", d) == ("Ruth", 2, 1, 2, 999)
    assert parse_reference("Ruth 1:3", d) == ("Ruth", 1, 3, 1, 3)
    assert parse_reference("Nowhere 3:1", d) is None and parse_reference("Ruth", d) is None
    assert verse_span(2, 1, 2, 999) == "2" and verse_span(1, 4, 2, 2) == "1:4-2:2" and verse_span(1, 3, 1, 3) == "1:3"
    d.close()


@test("the Heat tab draws the strips, lists a strip's spots, reads verses, and says why an old file is bare")
def _():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import word_atlas_reader
    w = word_atlas_reader.ReaderWindow()
    try:
        assert w.open_path(os.path.join(TEST_HOME, "heat_results.db"))
        h = w.heat_tab
        assert w.tabs.tabText(w.tabs.indexOf(h)) == "Heat" and w.tabs.tabText(w.tabs.count() - 1) == "Tools"
        assert h.book_box.currentText() == "Ruth" and [s[0] for s in h.strips] == ["density", "rest"]
        # Click the rest strip in a hot window: its spot is listed and the window's verses shown
        h.chart.resize(900, 200)
        h.chart.selected = 1
        h.chart_clicked(1, 4)
        assert h.spot_grid.rowCount() == 1 and h.spot_grid.item(0, 4).text() == "'rest' 3"
        assert "Ruth 1:5 text" in h.text_view.toPlainText(), h.text_view.toPlainText()[:200]
        h.spot_chosen(0, 0)
        assert h.chart.marked is not None and "hot spot Ruth 1:4-2:4" in h.text_view.toPlainText()
        h.tags_check.setChecked(True)
        assert "Ruth H7327" in h.text_view.toPlainText()
        h.passage_chosen(h.passage_box.findText("Test passage"))
        assert "Ruth 2:4 text" in h.text_view.toPlainText()
        h.verse_edit.setText("Ruth 2:11-12; Nowhere 1:1")
        h.verses_asked()
        text = h.text_view.toPlainText()
        assert "Ruth 2:12 text" in text and "not read: Nowhere 1:1" in text, text[:200]
        # Only the word lists
        h.kind_box.setCurrentIndex(h.kind_box.findText("word list"))
        assert [s[0] for s in h.strips] == ["rest"]
        # The chart's tooltip text names the strip and its words (hit test on a label)
        row, pos = h.chart.hit(h.chart.rect().topLeft() + type(h.chart.rect().topLeft())(10, h.chart.TOP + 4))
        assert (row, pos) == (0, -1), (row, pos)
        # An older file: the tab says why it is bare
        assert w.open_path(SAMPLE)
        assert "made before Word Atlas 0.10.101" in h.note.text() and h.book_box.count() == 0
        assert h.spot_grid.rowCount() == 0 and not h.verse_edit.isEnabled()
    finally:
        w.close()


@test("the About box and the credits page show the sources table a 0.10.103 dataset carries")
def _():
    from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QTableWidget
    import atlas_report
    import reader_credits
    app = QApplication.instance() or QApplication(sys.argv)
    path = os.path.join(TEST_HOME, "sources_results.db")
    make_heat_dataset(path)
    md = os.path.join(TEST_HOME, "ATTRIBUTION.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# Attribution\n\n## The sources table\n\n| Name | Supplies | License | Credit | Adapted |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| OpenBible.info cross references | The listed column | CC BY | Cross references from OpenBible.info, CC BY. "
                "| yes: counts of votes |\n"
                "| King James Version (1769) | The text | Public domain | King James Version, public domain. | no: quoted |\n"
                "\n## How to credit\n")
    db = sqlite3.connect(path)
    assert atlas_report.write_sources(db, md) == 2
    db.close()
    import word_atlas_reader
    real_exec = QDialog.exec
    QDialog.exec = lambda self: 0          # the box is looked at, not waited on
    w = word_atlas_reader.ReaderWindow()
    try:
        assert w.open_path(path)
        assert [r["name"] for r in w.data.sources()] == ["OpenBible.info cross references", "King James Version (1769)"]
        w.about()
        table = w.about_dialog.findChild(QTableWidget, "about_sources")
        assert table.rowCount() == 2 and table.item(0, 2).text() == "CC BY" and table.item(0, 4).text().startswith("yes")
        text = reader_credits.credits_text(w.data.db, "sources_results.db")
        assert "As this dataset records them" in text and "Credit:   Cross references from OpenBible.info, CC BY." in text
        # An older dataset: no table, and the box says so
        assert w.open_path(SAMPLE)
        w.about()
        table = w.about_dialog.findChild(QTableWidget, "about_sources")
        assert table.rowCount() == 0 and not table.isVisibleTo(w.about_dialog)
        labels = " ".join(label.text() for label in w.about_dialog.findChildren(QLabel))
        assert "packed before Word Atlas 0.10.103" in labels, labels
        assert "As this dataset records them" not in reader_credits.credits_text(w.data.db, "sample")
    finally:
        QDialog.exec = real_exec
        w.close()


# --- updates from GitHub, the install report, a built copy's drive (0.3.13) -----------------------
def fake_reader_zip(path, version):
    """A zip shaped like GitHub's branch zip of the Reader: one top folder, program files, a subfolder."""
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word-atlas-reader-main/word_atlas_reader.py", f'VERSION = "{version}"\n')
        z.writestr("word-atlas-reader-main/reader_data.py", "# data\n")
        z.writestr("word-atlas-reader-main/README.md", "# readme\n")
        z.writestr("word-atlas-reader-main/guest_key.dat", "never")
        z.writestr("word-atlas-reader-main/sample/x.wadb", "not a program file")
        z.writestr("word-atlas-reader-main/.gitignore", "datasets/\n")


@test("a newer Reader is found on GitHub and put in place, the old files kept and the datasets left alone")
def _():
    import json
    import reader_update
    calls = []

    def fake_fetch(url, timeout=30):
        calls.append(url)
        return b'VERSION = "9.9.9"\n'
    real_fetch = reader_update.fetch
    reader_update.fetch = fake_fetch
    try:
        latest = reader_update.latest_program({"update_repo": "someone/elsewhere"})
    finally:
        reader_update.fetch = real_fetch
    assert latest["version"] == "9.9.9" and "someone/elsewhere" in calls[0], (latest, calls)
    assert reader_update.is_newer("0.3.13", "0.3.12") and not reader_update.is_newer("0.3.9", "0.3.12")
    with tempfile.TemporaryDirectory() as tmp:
        # An installed copy: the install folder, the Reader's folder, a dataset, a guest key
        dest = os.path.join(tmp, "WordAtlas")
        app = os.path.join(dest, "word_atlas_reader")
        os.makedirs(os.path.join(app, "datasets"))
        for name, text in (("word_atlas_reader.py", 'VERSION = "0.3.12"\n'), ("reader_data.py", "# old\n"),
                           ("guest_key.dat", "mine"), ("datasets/kept.wadb", "data")):
            with open(os.path.join(app, *name.split("/")), "w") as f:
                f.write(text)
        with open(os.path.join(dest, "installed.json"), "w") as f:
            json.dump({"reader": {"version": "0.3.12"}}, f)
        with open(os.path.join(dest, "installed_files.json"), "w") as f:
            json.dump({"reader": {"word_atlas_reader/reader_data.py": {"size": 6, "sha256": "x"}}}, f)
        zip_path = os.path.join(tmp, "main.zip")
        fake_reader_zip(zip_path, "9.9.9")
        written, backup = reader_update.install_program(zip_path, app, os.path.join(tmp, "backups"), "0.3.12")
        assert sorted(written) == ["README.md", "reader_data.py", "word_atlas_reader.py"], written
        assert open(os.path.join(app, "word_atlas_reader.py")).read().startswith('VERSION = "9.9.9"')
        assert open(os.path.join(app, "guest_key.dat")).read() == "mine", "the guest key was replaced"
        assert open(os.path.join(app, "datasets", "kept.wadb")).read() == "data"
        assert not os.path.exists(os.path.join(app, "sample")), "a subfolder of the zip was written"
        assert open(os.path.join(backup, "reader_data.py")).read() == "# old\n", "the old file was not kept"
        # The install's own records follow the update, so its report does not call the new files damaged
        record = json.load(open(os.path.join(dest, "installed.json")))
        files = json.load(open(os.path.join(dest, "installed_files.json")))["reader"]
        assert record["reader"]["version"] == "9.9.9", record
        assert files["word_atlas_reader/reader_data.py"]["sha256"] == reader_update.file_sha256(
            os.path.join(app, "reader_data.py"))
        # A zip without the Reader in it is refused, and nothing is written
        bad = os.path.join(tmp, "bad.zip")
        import zipfile
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("other-main/README.md", "x")
        try:
            reader_update.install_program(bad, app)
            raise AssertionError("a zip without the Reader was installed")
        except reader_update.UpdateError:
            pass


@test("the newest dataset of the GitHub releases is found, downloaded and the older ones listed")
def _():
    import json
    import zipfile
    import reader_update
    releases = [
        {"draft": False, "tag_name": "dataset-old", "published_at": "2026-10-01T00:00:00Z",
         "assets": [{"name": "word_atlas_0.10.87.wadb", "size": 10, "browser_download_url": "u1",
                     "updated_at": "2026-10-01T00:00:00Z"}]},
        {"draft": False, "tag_name": "dataset-new", "name": "Dataset 2026-10-20", "published_at": "2026-10-20T00:00:00Z",
         "assets": [{"name": "word_atlas_0.10.101.wadb", "size": 0, "browser_download_url": "u2",
                     "updated_at": "2026-10-20T00:00:00Z"}, {"name": "notes.txt", "browser_download_url": "u3"}]},
        {"draft": True, "tag_name": "draft", "assets": [{"name": "word_atlas_9.wadb", "browser_download_url": "u4",
                                                          "updated_at": "2099-01-01T00:00:00Z"}]},
    ]
    real_fetch, real_download = reader_update.fetch, reader_update.download
    reader_update.fetch = lambda url, timeout=30: json.dumps(releases).encode()
    got = []

    def fake_download(url, path, progress=None, cancelled=None):
        got.append(url)
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("results.db", "x")
        if progress:
            progress(1, 1)
    reader_update.download = fake_download
    try:
        asset = reader_update.latest_dataset()
        assert asset["name"] == "word_atlas_0.10.101.wadb" and asset["release"] == "Dataset 2026-10-20", asset
        reader_update.fetch = lambda url, timeout=30: b"[]"
        assert reader_update.latest_dataset() is None
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "word_atlas_0.10.87.wadb"), "wb") as f:
                f.write(b"old")
            assert not reader_update.have_dataset(asset, tmp)
            path = reader_update.fetch_dataset(asset, tmp)
            assert got == ["u2"] and reader_update.have_dataset(asset, tmp)
            assert reader_update.older_datasets(tmp, path) == [os.path.join(tmp, "word_atlas_0.10.87.wadb")]
    finally:
        reader_update.fetch, reader_update.download = real_fetch, real_download


@test("a refused zip address falls back to the files one by one, in a zip of the same shape")
def _():
    import json
    import reader_update
    real_fetch, real_download = reader_update.fetch, reader_update.download
    tried = []

    def refuse(url, path, progress=None, cancelled=None):
        # Both zip addresses refused, as a firewall might
        tried.append(url)
        raise reader_update.UpdateError("the download failed (Forbidden)")

    listing = [{"name": n, "type": "file"} for n in ("word_atlas_reader.py", "reader_data.py", "README.md",
                                                     "settings.json", ".gitignore")] + [{"name": "sample", "type": "dir"}]

    def fake_fetch(url, timeout=30):
        if "contents" in url:
            return json.dumps(listing).encode()
        return f'VERSION = "9.9.9"\n# {url.rsplit("/", 1)[-1]}\n'.encode()
    reader_update.download, reader_update.fetch = refuse, fake_fetch
    try:
        latest = {"version": "9.9.9", "zip_url": "https://codeload.example/zip", "repo": "someone/reader"}
        notes = []
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "r.zip")
            way = reader_update.download_program(latest, zip_path, notes.append)
            assert "file by file" in way and len(tried) == 2 and len(notes) == 2, (way, tried, notes)
            members = reader_update.program_members(zip_path)
            assert sorted(members) == ["README.md", "reader_data.py", "word_atlas_reader.py"], members
            written, _ = reader_update.install_program(zip_path, os.path.join(tmp, "app"))
            assert len(written) == 3
        # Nothing reachable at all: one error naming each way
        reader_update.fetch = lambda url, timeout=30: (_ for _ in ()).throw(reader_update.UpdateError("offline"))
        try:
            reader_update.download_program(latest, os.path.join(tempfile.gettempdir(), "never.zip"))
            raise AssertionError("no error when nothing could be reached")
        except reader_update.UpdateError as e:
            assert "file by file: offline" in str(e), e
    finally:
        reader_update.fetch, reader_update.download = real_fetch, real_download


@test("the installer writes an install report, and --check finds a missing and a changed file")
def _():
    import subprocess
    import atlas_usb
    with tempfile.TemporaryDirectory() as tmp:
        drive, dest, home = (os.path.join(tmp, d) for d in ("drive", "installed", "home"))
        for d in (drive, home):
            os.makedirs(d)
        options = atlas_usb.default_options(None, HERE)
        options.update({"atlas": False, "dataset": SAMPLE, "wheels": False, "sync": False})
        atlas_usb.build(drive, options, None, HERE, log=lambda *a: None)
        root = atlas_usb.drive_root(drive)
        env = dict(os.environ, HOME=home, USERPROFILE=home, QT_QPA_PLATFORM="offscreen",
                   # A PyQt6 installed with pip --user lives under the real
                   # home folder; keep it findable when HOME is a stand-in
                   PYTHONUSERBASE=site.getuserbase())
        env.pop("WORD_ATLAS_READER_HOME", None)
        out = subprocess.run([sys.executable, os.path.join(root, "install.py"), "--app", "reader", "--dest", dest,
                              "--yes", "--no-shortcuts", "--no-pyqt"], capture_output=True, text=True, env=env,
                             timeout=300)
        assert out.returncode == 0, out.stdout[-600:]
        report = open(os.path.join(dest, "install_report.txt"), encoding="utf-8").read()
        assert "NO PROBLEMS FOUND" in report and "reads back whole" in report and "Loads       yes" in report, report
        app = os.path.join(dest, "word_atlas_reader")
        os.remove(os.path.join(app, "README.md"))
        with open(os.path.join(app, "reader_data.py"), "a") as f:
            f.write("# changed here\n")
        # From the installed copy, without the drive
        out = subprocess.run([sys.executable, os.path.join(app, "usb_install.py"), "--check"], capture_output=True,
                             text=True, env=env, timeout=300)
        assert out.returncode == 1, out.stdout[-600:]
        assert "missing:   word_atlas_reader/README.md" in out.stdout and \
            "different: word_atlas_reader/reader_data.py" in out.stdout and "PROBLEMS FOUND: 2" in out.stdout, \
            out.stdout[-900:]
        assert "PROBLEMS FOUND: 2" in open(os.path.join(dest, "install_report.txt"), encoding="utf-8").read()


@test("a built copy finds its source folder for the drive, and its own datasets stay off the drive")
def _():
    import atlas_usb
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "word_atlas_reader")
        build = os.path.join(src, "dist", "WordAtlasReader")
        os.makedirs(os.path.join(build, "datasets"))
        os.makedirs(os.path.join(build, "_internal"))
        for name in ("word_atlas_reader.py", "reader_data.py"):
            with open(os.path.join(src, name), "w") as f:
                f.write('VERSION = "0.3.13"\n')
        for rel in ("WordAtlasReader", "_internal/lib.so", "datasets/big.wadb"):
            with open(os.path.join(build, *rel.split("/")), "w") as f:
                f.write("x")
        frozen, executable = getattr(sys, "frozen", None), sys.executable
        sys.frozen, sys.executable = True, os.path.join(build, "WordAtlasReader")
        try:
            assert atlas_usb.source_of_build() == src, atlas_usb.source_of_build()
            assert atlas_usb.find_reader_dir() == src
        finally:
            sys.executable = executable
            if frozen is None:
                del sys.frozen
            else:
                sys.frozen = frozen
        assert atlas_usb.source_of_build() is None
        items, groups = atlas_usb.gather({"reader": True}, None, src)
        rels = sorted(i.rel for i in items)
        assert "builds/linux/WordAtlasReader/_internal/lib.so" in rels or \
            "builds/windows/WordAtlasReader/_internal/lib.so" in rels, rels
        assert not any("datasets" in r for r in rels), rels


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
