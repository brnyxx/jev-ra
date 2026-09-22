import json
from datetime import date
from pathlib import Path
from typing import ClassVar

import pytest

from jev_ra import cli, corpus
from jev_ra.agent import Result
from jev_ra.errors import JevRaError

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FAMILIES = {
    "ecommerce": 5,
    "search_read": 5,
    "booking": 5,
    "forms": 18,
    "news": 5,
    "docs_spa": 15,
    "portal": 5,
    "auth": 5,
    "ja": 10,
    "zh_cn": 10,
}


def page(url="https://example.com/x", text="hello", elements=None):
    return {"url": url, "text": text, "elements": elements or []}


class FakeSession:
    instances: ClassVar[list] = []

    def __init__(self, _config=None):
        self.closed = False
        FakeSession.instances.append(self)

    def close(self):
        self.closed = True


def fake_agent(result):
    class FakeAgent:
        def __init__(self, session=None, config=None, decide=None):
            self.session = session

        def run(self, goal, values=None, max_steps=20, url=None):
            if isinstance(result, Exception):
                raise result
            return result

    return FakeAgent


@pytest.fixture
def stub(monkeypatch):
    def install(result):
        FakeSession.instances = []
        monkeypatch.setattr(corpus, "Session", FakeSession)
        monkeypatch.setattr(corpus, "Agent", fake_agent(result))

    return install


def task(**kwargs):
    base = {"name": "t", "family": "f", "url": "https://example.com", "goal": "do it"}
    return corpus.Task(**{**base, **kwargs})


def test_the_corpus_file_declares_its_tasks_in_ten_families():
    tasks = corpus.load_tasks()
    assert len(tasks) == 83
    assert corpus.families(tasks) == list(EXPECTED_FAMILIES)
    counted = {name: len([t for t in tasks if t.family == name]) for name in EXPECTED_FAMILIES}
    assert counted == EXPECTED_FAMILIES


def test_every_httpbin_form_task_has_a_twin_on_a_second_host():
    tasks = {task.name: task for task in corpus.load_tasks()}
    twins = 0
    for name, base in tasks.items():
        if not name.startswith("httpbin_form_") or name.endswith("_bingo"):
            continue
        twin = tasks[f"{name}_bingo"]
        assert twin.family == base.family
        assert twin.goal == base.goal
        assert twin.values == base.values
        assert twin.expect == base.expect
        assert twin.verify == base.verify
        assert twin.max_steps == base.max_steps
        assert "httpbingo.org" in twin.url
        twins += 1
    assert twins == 3


def test_every_declared_task_is_well_formed():
    names = set()
    for entry in corpus.load_tasks():
        assert entry.name not in names
        names.add(entry.name)
        assert entry.url.startswith("https://")
        assert entry.goal.endswith(".")
        assert entry.expect == "done" or entry.expect.startswith("escalate:")
        if entry.expect == "done":
            assert entry.verify, f"{entry.name} says done but proves nothing"
        else:
            assert not entry.verify, f"{entry.name} escalates, so there is no page to verify"


def test_a_capability_outside_v0_1_expects_a_clean_blocked_and_says_so_in_the_readme():
    walls = [t for t in corpus.load_tasks() if t.expect == "escalate:blocked"]
    assert {t.name for t in walls} == {"file_upload_picker", "canvas_drawing"}
    limits = (ROOT / "README.md").read_text()
    section = limits[limits.index("## What it will not do") : limits.index("## FAQ")]
    for row in ("Canvas drawing", "File upload"):
        assert row in section and "`blocked`" in section


def test_an_auth_wall_must_escalate_for_a_missing_value_never_guess():
    walls = [t for t in corpus.load_tasks() if t.family == "auth"]
    assert walls
    assert all(t.expect == "escalate:needs_value" for t in walls)
    assert all(not t.values for t in walls)


def test_url_and_text_predicates():
    row = page(url="https://en.wikipedia.org/wiki/Zebra", text="Zebras are African horses")
    assert corpus.check({"url_contains": ["wikipedia.org"]}, row) == (True, "")
    assert corpus.check({"url_contains": ["ko.wikipedia"]}, row)[0] is False
    assert corpus.check({"url_not_contains": ["Main_Page"]}, row) == (True, "")
    assert corpus.check({"url_not_contains": ["Zebra"]}, row)[0] is False
    assert corpus.check({"text_contains": ["African"]}, row) == (True, "")
    assert corpus.check({"text_any": ["얼룩말", "Zebras"]}, row) == (True, "")
    assert corpus.check({"text_any": ["얼룩말"]}, row)[0] is False
    assert corpus.check({"min_text": 5}, row) == (True, "")
    ok, why = corpus.check({"min_text": 500}, row)
    assert ok is False and "under 500" in why


def test_label_and_active_predicates():
    row = page(elements=[{"label": "신상품순", "selected": "true"}, {"label": "인기순"}])
    assert corpus.check({"label_any": ["신상품순"]}, row) == (True, "")
    assert corpus.check({"label_any": ["최저가순"]}, row)[0] is False
    assert corpus.check({"active_label": ["신상품순"]}, row) == (True, "")
    ok, why = corpus.check({"active_label": ["인기순"]}, row)
    assert ok is False and "not marked active" in why


def test_a_missing_text_needle_is_reported():
    ok, why = corpus.check({"text_contains": ["zebra"]}, page(text="horses are mammals"))
    assert ok is False and "zebra" in why


def test_a_done_task_passes_only_when_the_page_proves_it():
    spec = task(verify={"url_contains": ["prdSort=02"]})
    assert corpus.classify(spec, {"status": "done", "url": "x?prdSort=02"}) == (True, "")
    passed, why = corpus.classify(spec, {"status": "done", "url": "x?prdSort=01"})
    assert passed is False and "prdSort=02" in why
    assert corpus.classify(spec, {"status": "escalate", "reason": "needs_value"}) == (False, "escalate:needs_value")


def test_an_escalating_task_passes_only_on_its_own_reason():
    spec = task(expect="escalate:needs_value")
    assert spec.expected_reason == "needs_value"
    assert corpus.classify(spec, {"status": "escalate", "reason": "needs_value"}) == (True, "")
    assert corpus.classify(spec, {"status": "escalate", "reason": "stuck_loop"})[0] is False
    passed, why = corpus.classify(spec, {"status": "done", "reason": ""})
    assert passed is False and why == "expected escalate:needs_value, got done"


def test_a_run_records_what_the_page_showed_and_closes_the_session(stub):
    stub(
        Result(
            status="done",
            url="https://example.com/x?sort=new",
            decisions=3,
            cost=0.002,
            final_page=page(url="https://example.com/x?sort=new", text="newest first"),
        )
    )
    row = corpus.run_task(task(verify={"url_contains": ["sort=new"]}), config=None, decide=lambda *_: {})
    assert row["passed"] is True
    assert row["decisions"] == 3 and row["cost"] == 0.002
    assert row["elapsed_ms"] >= 0
    assert FakeSession.instances[0].closed is True


def test_a_run_records_the_status_and_whether_the_site_answered_with_an_error(stub):
    stub(Result(status="done", http_status=502, site_error=True, final_page=page()))
    row = corpus.run_task(task(verify={"text_contains": ["hello"]}), config=None, decide=lambda *_: {})
    assert row["http_status"] == 502 and row["site_error"] is True
    stub(Result(status="done", http_status=200, final_page=page()))
    row = corpus.run_task(task(verify={"text_contains": ["hello"]}), config=None, decide=lambda *_: {})
    assert row["http_status"] == 200 and row["site_error"] is False


def test_a_failed_engine_records_no_status_and_no_site_error(stub):
    stub(JevRaError("Chrome is not reachable."))
    row = corpus.run_task(task(), config=None, decide=lambda *_: {})
    assert row["http_status"] is None and row["site_error"] is False


def test_a_run_records_what_it_typed_so_the_results_file_can_be_checked(stub):
    stub(
        Result(
            status="done",
            steps=[
                {"operation": "TYPE_TEXT", "target": "e2", "target_label": "Search", "text": "1040"},
                {"operation": "CLICK", "target": "e3", "target_label": "Search", "text": None},
            ],
            final_page=page(),
        )
    )
    row = corpus.run_task(task(verify={"text_contains": ["hello"]}), config=None, decide=lambda *_: {})
    assert row["trace"] == [
        {"operation": "TYPE_TEXT", "target": "e2", "label": "Search", "text": "1040"},
        {"operation": "CLICK", "target": "e3", "label": "Search", "text": None},
    ]


def test_a_failing_engine_is_a_failed_row_not_a_crashed_corpus(stub):
    stub(JevRaError("Chrome is not reachable."))
    row = corpus.run_task(task(), config=None, decide=lambda *_: {})
    assert row["status"] == "error" and row["reason"] == "JevRaError"
    assert row["passed"] is False
    assert FakeSession.instances[0].closed is True


def test_the_page_text_kept_per_row_is_capped(stub):
    stub(Result(status="done", final_page=page(text="x" * (corpus.TEXT_CHARS * 2))))
    row = corpus.run_task(task(verify={"min_text": 10}), config=None, decide=lambda *_: {})
    assert len(row["text"]) == corpus.TEXT_CHARS


def test_selection_by_family_and_by_name(stub, monkeypatch):
    stub(Result(status="done", final_page=page()))
    tasks = [
        task(name="a", family="one", verify={"text_contains": ["hello"]}),
        task(name="b", family="two", verify={"text_contains": ["hello"]}),
    ]
    rows = corpus.run(tasks, config=object(), runs=2, family="two", decide=lambda *_: {})
    assert [row["task"] for row in rows] == ["b", "b"]
    rows = corpus.run(tasks, config=object(), name="a", decide=lambda *_: {})
    assert [row["task"] for row in rows] == ["a"]
    with pytest.raises(JevRaError):
        corpus.run(tasks, config=object(), family="nothing", decide=lambda *_: {})


def test_the_live_corpus_refuses_to_start_without_a_key():
    with pytest.raises(JevRaError, match="needs a Jev key"):
        corpus.run([task()], config=type("C", (), {"api_key": ""})())


def test_the_corpus_owns_and_closes_a_decision_client_when_none_is_given(stub, monkeypatch):
    stub(Result(status="done", final_page=page()))
    clients = []

    class Client:
        def __init__(self, _config):
            clients.append(self)
            self.closed = False

        def decide(self, _state, _questions):
            raise AssertionError("the fake agent never decides")

        def close(self):
            self.closed = True

    monkeypatch.setattr(corpus, "DecisionClient", Client)
    rows = corpus.run([task(verify={"text_contains": ["hello"]})], config=type("C", (), {"api_key": "k"})(), runs=1)
    assert rows[0]["passed"] is True
    assert clients[0].closed is True


def test_the_summary_reports_pass_rate_median_and_the_reasons():
    rows = [
        {
            "task": "a",
            "family": "f",
            "passed": True,
            "why": "",
            "elapsed_ms": 100,
            "decisions": 2,
            "cost": 0.001,
            "status": "done",
            "reason": "",
        },
        {
            "task": "a",
            "family": "f",
            "passed": True,
            "why": "",
            "elapsed_ms": 300,
            "decisions": 4,
            "cost": 0.003,
            "status": "done",
            "reason": "",
        },
        {
            "task": "b",
            "family": "g",
            "passed": False,
            "why": "escalate:stale",
            "elapsed_ms": 50,
            "decisions": 1,
            "cost": 0.0,
            "status": "escalate",
            "reason": "stale",
        },
    ]
    table = corpus.summarise(rows)
    first = next(row for row in table if row["task"] == "a")
    assert first["pass_rate"] == 1.0 and first["median_ms"] == 200 and first["decisions"] == 3
    second = next(row for row in table if row["task"] == "b")
    assert second["median_ms"] is None and second["why"] == ["escalate:stale"]
    assert corpus.pass_rate(rows) == round(2 / 3, 4)
    assert corpus.reasons(rows) == {"escalate": 1}
    assert corpus.pass_rate([]) == 0.0


def test_the_summary_counts_the_attempts_the_site_answered_with_an_error():
    rows = [
        {
            "task": "a",
            "family": "f",
            "passed": True,
            "why": "",
            "elapsed_ms": 100,
            "decisions": 2,
            "cost": 0.001,
            "status": "done",
            "reason": "",
            "site_error": True,
        },
        {
            "task": "a",
            "family": "f",
            "passed": False,
            "why": "escalate:blocked_by_site",
            "elapsed_ms": 200,
            "decisions": 0,
            "cost": 0.0,
            "status": "escalate",
            "reason": "blocked_by_site",
            "site_error": True,
        },
        {
            "task": "b",
            "family": "f",
            "passed": True,
            "why": "",
            "elapsed_ms": 300,
            "decisions": 3,
            "cost": 0.002,
            "status": "done",
            "reason": "",
            "site_error": False,
        },
    ]
    table = corpus.summarise(rows)
    first = next(row for row in table if row["task"] == "a")
    second = next(row for row in table if row["task"] == "b")
    assert first["site"] == 2 and second["site"] == 0


def test_the_results_file_keeps_the_site_columns(tmp_path):
    rows = [{"task": "a", "status": "done", "http_status": 503, "site_error": True}]
    first = json.loads(corpus.write_results(rows, tmp_path).read_text().strip())
    assert first["http_status"] == 503 and first["site_error"] is True


def test_results_are_appended_without_the_bulky_page(tmp_path):
    rows = [{"task": "a", "passed": True, "text": "x" * 100, "elements": [{"label": "b"}], "status": "done"}]
    path = corpus.write_results(rows, tmp_path)
    corpus.write_results(rows, tmp_path)
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert "text" not in first and "elements" not in first
    assert first["task"] == "a"


def test_a_results_row_keeps_the_steps_it_typed(tmp_path):
    rows = [
        {
            "task": "a",
            "status": "done",
            "trace": [{"operation": "TYPE_TEXT", "target": "e1", "label": "Search", "text": "1040"}],
        }
    ]
    first = json.loads(corpus.write_results(rows, tmp_path).read_text().strip())
    assert first["trace"] == [{"operation": "TYPE_TEXT", "target": "e1", "label": "Search", "text": "1040"}]


def test_the_cli_lists_the_corpus_without_touching_the_network(capsys):
    assert cli.main(["corpus", "run", "--list"]) == 0
    out = capsys.readouterr().out
    assert "oliveyoung_sort_newest" in out
    assert "github_login_wall" in out


def test_the_cli_reports_the_run_and_fails_under_the_bar(monkeypatch, tmp_path, capsys):
    rows = [
        {"task": "a", "family": "f", "passed": True, "why": "", "elapsed_ms": 100, "decisions": 2, "cost": 0.001},
        {
            "task": "b",
            "family": "f",
            "passed": False,
            "why": "url does not contain 'x'",
            "elapsed_ms": 90,
            "decisions": 1,
            "cost": 0.0,
            "status": "done",
        },
    ]
    monkeypatch.setattr(corpus, "run", lambda **_kwargs: rows)
    monkeypatch.setattr(corpus, "RESULTS", tmp_path)
    monkeypatch.setattr(cli, "load", lambda: object())
    code = cli.main(["corpus", "run", "--runs", "1"])
    out = capsys.readouterr().out
    assert code == 1
    assert "pass rate 50%" in out
    assert "FAIL" in out
    assert "| task | family |" in out and "| site |" in out


def test_the_cli_passes_when_the_corpus_clears_the_bar(monkeypatch, tmp_path, capsys):
    rows = [{"task": "a", "family": "f", "passed": True, "why": "", "elapsed_ms": 100, "decisions": 2, "cost": 0.001}]
    monkeypatch.setattr(corpus, "run", lambda **_kwargs: rows)
    monkeypatch.setattr(corpus, "RESULTS", tmp_path)
    monkeypatch.setattr(cli, "load", lambda: object())
    assert cli.main(["corpus", "run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pass_rate"] == 1.0 and payload["passed"] is True
    assert payload["tasks"][0]["task"] == "a"


def test_a_url_check_reads_the_address_not_its_casing():
    row = page(url="https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API")
    assert corpus.check({"url_contains": ["fetch"]}, row) == (True, "")
    assert corpus.check({"url_not_contains": ["fetch"]}, row)[0] is False
    assert corpus.check({"url_contains": ["xhr"]}, row)[0] is False


def test_a_text_check_reads_typographic_punctuation_as_what_it_stands_for():
    row = page(text="What\u2019s New In Python 3.14 \u2014 the \u201cnew\u201d release")
    assert corpus.check({"text_any": ["What's New"]}, row) == (True, "")
    assert corpus.check({"text_contains": ['the "new" release']}, row) == (True, "")
    assert corpus.check({"text_contains": ["3.14 - the"]}, row) == (True, "")
    assert corpus.check({"text_any": ["What's Old"]}, row)[0] is False


def test_a_spec_date_written_as_today_plus_days_is_the_day_the_run_happens_on(tmp_path):
    path = tmp_path / "sites.toml"
    path.write_text(
        """[[task]]
name = "trip"
family = "booking"
url = "https://example.com"
goal = "Fly out on {today+30}, back {today}."
values = { departure_date = "{today+30}", note = "fixed" }
"""
    )
    (task,) = corpus.load_tasks(path, today=date(2026, 9, 22))
    assert task.goal == "Fly out on 2026-10-22, back 2026-09-22."
    assert task.values == {"departure_date": "2026-10-22", "note": "fixed"}


def test_the_flights_task_always_asks_for_a_departure_a_month_ahead():
    task = next(t for t in corpus.load_tasks(today=date(2026, 9, 22)) if t.name == "flights_zrh_lon_oneway")
    assert task.values["departure_date"] == "2026-10-22"
    assert "2026-10-22" in task.goal


def test_the_flights_spec_reads_the_results_page_as_google_spells_zurich():
    task = next(t for t in corpus.load_tasks(today=date(2026, 9, 23)) if t.name == "flights_zrh_lon_oneway")
    row = {
        "url": "https://www.google.com/travel/flights/search?tfs=CBwQAhooEgoyMDI2LTEwLTIz",
        "text": "Search results\n22 results returned.\nTrack prices from Zürich to London departing 2026-10-23",
        "elements": [],
    }
    assert corpus.check(task.verify, row) == (True, "")
