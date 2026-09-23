"""The corpus and the live bench ask each host for a budget of attempts a day, spaced, and rest a host that refused."""

import json
import threading
from datetime import datetime
from typing import ClassVar

import pytest

from jev_ra import bench, cli, config, corpus, traffic
from jev_ra.agent import Result
from jev_ra.traffic import Ledger
from jev_ra.traffic import ledger as machine_ledger

NOON = datetime(2026, 9, 23, 12, 0).timestamp()
LATE = datetime(2026, 9, 23, 23, 59).timestamp()
NEXT_MORNING = datetime(2026, 9, 24, 0, 1).timestamp()
KEYED = config.load({"TYPESAFE_API_KEY": "k"})


class Clock:
    """A wall clock that only moves when something sleeps on it or a test moves it."""

    def __init__(self, now=NOON):
        self.now = now
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


class Opened:
    instances: ClassVar[list] = []

    def __init__(self, _config=None):
        Opened.instances.append(self)

    def close(self):
        pass


def returning(result):
    class Agent:
        def __init__(self, **_kwargs):
            pass

        def run(self, *_args, **_kwargs):
            return result

    return Agent


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make(tmp_path, clock):
    def build(**options):
        options = {"budget": 40, "gap_s": 10.0, "rest_s": 86400.0, **options}
        return Ledger(tmp_path / "traffic", clock=clock, sleep=clock.sleep, **options)

    return build


@pytest.fixture
def ends(monkeypatch):
    def install(result):
        Opened.instances = []
        monkeypatch.setattr(corpus, "Session", Opened)
        monkeypatch.setattr(corpus, "Agent", returning(result))

    return install


def task(name="t", url="https://shop.test/list", **kwargs):
    return corpus.Task(name=name, family="f", url=url, goal="do it", **kwargs)


def lines(ledger, day="2026-09-23"):
    return [json.loads(line) for line in ledger.path(day).read_text().splitlines()]


def counts(ledger):
    return {row["host"]: row["attempts"] for row in ledger.today()["hosts"]}


def test_two_ledgers_on_one_directory_see_each_others_attempts(make, clock):
    first, second = make(gap_s=0.0), make(gap_s=0.0)
    first.claim("https://shop.test/a", "a")
    second.claim("https://shop.test/b", "b")
    second.claim("https://news.test/", "c")
    assert counts(first) == counts(second) == {"shop.test": 2, "news.test": 1}
    assert [line["task"] for line in lines(first)] == ["a", "b", "c"]
    assert {key for line in lines(first) for key in line} == {"id", "host", "at", "task", "outcome"}


def test_claims_from_many_threads_are_all_kept(make):
    ledgers = [make(gap_s=0.0), make(gap_s=0.0)]

    def attempts(ledger, host):
        for _ in range(5):
            claim = ledger.claim(f"https://{host}/", host)
            ledger.settle(claim, {"status": "done"})

    threads = [threading.Thread(target=attempts, args=(ledgers[index % 2], f"host{index}.test")) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    written = lines(ledgers[0])
    assert len(written) == 40
    assert all(line["outcome"] == "done" for line in written)


def test_a_host_that_has_had_its_attempts_is_skipped_without_opening_a_page(make, ends):
    ledger = make(budget=2, gap_s=0.0)
    ends(Result(status="done", final_page={"text": "hello"}))
    ran = [corpus.run_task(task(verify={"text_contains": ["hello"]}), KEYED, None, ledger) for _ in range(2)]
    assert [row["passed"] for row in ran] == [True, True]
    assert len(Opened.instances) == 2
    row = corpus.run_task(task(verify={"text_contains": ["hello"]}), KEYED, None, ledger)
    assert (row["status"], row["reason"], row["passed"]) == ("skipped", "host_budget", None)
    assert "shop.test has had its 2 live attempts" in row["text"]
    assert len(Opened.instances) == 2
    assert counts(ledger) == {"shop.test": 2}


def test_the_corpus_run_passes_its_ledger_to_every_attempt(make, ends):
    ends(Result(status="done", final_page={"text": "hello"}))
    ledger = make(budget=2, gap_s=0.0)
    rows = corpus.run([task(verify={"text_contains": ["hello"]})], config=KEYED, runs=3, decide=object(), ledger=ledger)
    assert [row["status"] for row in rows] == ["done", "done", "skipped"]


def test_the_next_attempt_on_a_host_waits_exactly_what_is_left_of_the_gap(make, clock):
    ledger = make(gap_s=10.0)
    assert ledger.claim("https://shop.test/a").held == 0
    clock.now += 3
    claim = ledger.claim("https://shop.test/b")
    assert claim.held == pytest.approx(7.0)
    assert clock.slept == [7.0]
    assert lines(ledger)[1]["at"] == pytest.approx(NOON + 10)
    assert ledger.claim("https://news.test/").held == 0
    assert clock.slept == [7.0]


def test_a_second_process_waits_its_gap_after_one_still_running(make, clock):
    running, arriving = make(gap_s=10.0), make(gap_s=10.0)
    running.claim("https://shop.test/a", "a")
    clock.now += 1
    arriving.claim("https://shop.test/b", "b")
    assert clock.slept == [9.0]


REFUSALS = [
    (Result(status="done", http_status=429, final_page={"text": "hello"}), "http 429"),
    (Result(status="escalate", reason="blocked_by_site", http_status=403), "http 403"),
    (Result(status="done", http_status=200, site_error=True, final_page={"text": "hello"}), "site_error"),
    (Result(status="escalate", reason="needs_human", human_wait_ms=120_000), "needs_human"),
    (Result(status="done", human_wait_ms=8_000, final_page={"text": "hello"}), "check"),
    (Result(status="escalate", reason="blocked_by_site", http_status=200), "blocked_by_site"),
    (Result(status="blocked", reason="blocked"), "blocked"),
]


@pytest.mark.parametrize(("result", "why"), REFUSALS, ids=[why for _result, why in REFUSALS])
def test_a_host_that_pushed_back_rests_while_another_host_still_runs(make, ends, clock, result, why):
    ledger = make()
    ends(result)
    corpus.run_task(task(verify={"text_contains": ["hello"]}), KEYED, None, ledger)
    assert lines(ledger)[0]["outcome"] == "refused" and lines(ledger)[0]["why"] == why
    clock.now += 3600
    ends(Result(status="done", final_page={"text": "hello"}))
    row = corpus.run_task(task(name="again", verify={"text_contains": ["hello"]}), KEYED, None, ledger)
    assert (row["status"], row["reason"], row["passed"]) == ("skipped", "host_resting", None)
    assert f"({why})" in row["text"] and "the end of the day" in row["text"]
    assert Opened.instances == []
    other = corpus.run_task(
        task(name="other", url="https://news.test/", verify={"text_contains": ["hello"]}), KEYED, None, ledger
    )
    assert other["status"] == "done" and len(Opened.instances) == 1


def test_a_blocked_run_its_task_expected_is_not_a_refusal(make, ends, clock):
    ledger = make()
    ends(Result(status="blocked", reason="blocked"))
    first = corpus.run_task(task(expect="escalate:blocked"), KEYED, None, ledger)
    assert first["passed"] is True
    clock.now += 60
    second = corpus.run_task(task(expect="escalate:blocked"), KEYED, None, ledger)
    assert second["status"] == "blocked"
    assert [line["outcome"] for line in lines(ledger)] == ["blocked", "blocked"]


def test_an_attempt_that_went_fine_does_not_rest_its_host(make, ends, clock):
    ledger = make()
    ends(Result(status="escalate", reason="needs_value"))
    corpus.run_task(task(expect="escalate:needs_value"), KEYED, None, ledger)
    clock.now += 60
    assert corpus.run_task(task(expect="escalate:needs_value"), KEYED, None, ledger)["status"] == "escalate"


def test_a_shortened_rest_ends_and_the_host_is_asked_again(make, ends, clock):
    ledger = make(rest_s=600.0)
    ends(Result(status="done", http_status=429))
    corpus.run_task(task(), KEYED, None, ledger)
    clock.now += 300
    assert corpus.run_task(task(), KEYED, None, ledger)["reason"] == "host_resting"
    clock.now += 301
    assert corpus.run_task(task(), KEYED, None, ledger)["status"] == "done"


def test_a_refusal_recorded_while_a_claim_waited_takes_the_claim_back(make, clock):
    running, waiting = make(), make()
    first = running.claim("https://shop.test/a", "a")
    refused_meanwhile = clock.sleep

    def sleep(seconds):
        refused_meanwhile(seconds)
        running.settle(first, {"status": "escalate", "reason": "blocked_by_site", "http_status": 403})

    waiting.sleep = sleep
    claim = waiting.claim("https://shop.test/b", "b")
    assert claim.skipped == "host_resting" and not claim.id
    assert [line["task"] for line in lines(running)] == ["a"]


def test_the_bench_pages_on_loopback_are_never_counted_or_held(make, clock):
    ledger = make(budget=1)
    with bench.serve() as base:
        for _ in range(3):
            claim = ledger.claim(f"{base}/checkout.html", "form_fill")
            assert (claim.id, claim.held, claim.skipped) == ("", 0.0, "")
            ledger.settle(claim, {"status": "blocked", "http_status": 429})
    assert ledger.claim("http://localhost:8000/", "x").id == ""
    assert ledger.claim("about:blank").id == ""
    assert clock.slept == []
    assert ledger.today()["hosts"] == []
    assert not ledger.path("2026-09-23").exists()


def test_the_live_bench_runs_its_local_page_without_touching_the_ledger(make, monkeypatch):
    class Client:
        def __init__(self, _config):
            self.decide = None

        def close(self):
            pass

    ledger = make(budget=1)
    monkeypatch.setattr(bench, "DecisionClient", Client)
    monkeypatch.setattr(bench, "Session", Opened)
    monkeypatch.setattr(bench, "Agent", returning(Result(status="done", url="http://127.0.0.1/checkout.html")))
    local = bench.LiveTask(key="local", page="checkout.html", goal="g", verify=lambda row: True)
    rows = bench.run_live(config=KEYED, tasks=(local,), runs=3, ledger=ledger)
    assert [row["ok"] for row in rows] == [True, True, True]
    assert ledger.today()["hosts"] == []


def test_the_live_bench_skips_a_page_task_whose_host_rests_without_opening_it(make, monkeypatch, clock):
    ledger = make()
    Opened.instances = []
    monkeypatch.setattr(bench, "Session", Opened)
    monkeypatch.setattr(bench, "Agent", returning(Result(status="escalate", reason="needs_human")))
    live = bench.LiveTask(key="shop", url="https://shop.test/", goal="g", verify=lambda row: True)
    first = bench.measure_page(live, live.url, KEYED, None, ledger)
    assert first["ok"] is None
    clock.now += 60
    second = bench.measure_page(live, live.url, KEYED, None, ledger)
    assert (second["status"], second["reason"], second["ok"]) == ("skipped", "host_resting", None)
    assert len(Opened.instances) == 1


def test_the_search_task_asks_its_engine_through_the_ledger(make, monkeypatch):
    ledger = make(budget=1, gap_s=0.0)
    Opened.instances = []
    monkeypatch.setattr(bench, "Session", Opened)
    found = {"results": [{"url": "https://docs.python.org/3/", "text": "released on October 2, 2023"}]}
    monkeypatch.setattr("jev_ra.search.search", lambda *_a, **_k: {**found, "decisions": 4, "cost": 0.0, "engine": ""})
    search_task = next(item for item in bench.LIVE_TASKS if item.kind == "search")
    first = bench.measure_search(search_task, KEYED, None, ledger)
    second = bench.measure_search(search_task, KEYED, None, ledger)
    assert first["ok"] is True
    assert (second["status"], second["reason"]) == ("skipped", "host_budget")
    assert second["url"].startswith("https://html.duckduckgo.com/")
    assert len(Opened.instances) == 1
    assert counts(ledger) == {"html.duckduckgo.com": 1}


def skipped_row(name="t", reason="host_resting", url="https://shop.test/"):
    return {
        "task": name,
        "family": "f",
        "status": "skipped",
        "reason": reason,
        "passed": None,
        "why": reason,
        "elapsed_ms": 0,
        "decisions": 0,
        "cost": 0.0,
        "url": url,
    }


def done_row(name="t", passed=True, elapsed_ms=100):
    return {
        "task": name,
        "family": "f",
        "status": "done",
        "reason": "",
        "passed": passed,
        "why": "" if passed else "page text does not contain 'x'",
        "elapsed_ms": elapsed_ms,
        "decisions": 2,
        "cost": 0.001,
        "url": "https://shop.test/",
    }


def test_the_corpus_summary_counts_skipped_attempts_apart():
    rows = [done_row(), done_row(passed=False), skipped_row(), skipped_row(reason="host_budget")]
    (row,) = corpus.summarise(rows)
    assert (row["runs"], row["passed"], row["skipped"], row["human"]) == (2, 1, 2, 0)
    assert row["pass_rate"] == 0.5 and row["median_ms"] == 100
    assert row["why"] == ["page text does not contain 'x'"]
    assert corpus.pass_rate(rows) == 0.5
    assert corpus.reasons(rows) == {"page text does not contain 'x'": 1}
    assert corpus.pass_rate([skipped_row()]) == 0.0
    assert traffic.skips(rows) == {
        "host_resting": {"attempts": 1, "hosts": ["shop.test"]},
        "host_budget": {"attempts": 1, "hosts": ["shop.test"]},
    }


def test_the_corpus_command_says_what_was_skipped_and_never_calls_it_a_pass(monkeypatch, tmp_path, capsys):
    rows = [done_row(), skipped_row(name="u"), skipped_row(name="v", reason="host_budget", url="https://news.test/")]
    monkeypatch.setattr(corpus, "run", lambda **_kwargs: rows)
    monkeypatch.setattr(corpus, "RESULTS", tmp_path)
    monkeypatch.setattr(cli, "load", lambda: object())
    assert cli.main(["corpus", "run", "--runs", "1"]) == 1
    out = capsys.readouterr().out
    assert "pass rate 100%" in out
    assert (
        "2 attempt(s) skipped, never sent and counted as neither a pass nor a failure:"
        " host_resting x1 (shop.test); host_budget x1 (news.test)." in out
    )
    assert "INCOMPLETE: 2 attempt(s) were skipped" in out
    assert "PASS" not in out
    assert "| skipped |" in out
    written = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert [line["status"] for line in written] == ["done", "skipped", "skipped"]


def bench_row(ok=True, elapsed_ms=1_000, status="done", reason=""):
    return {
        "task": "flights",
        "status": status,
        "reason": reason,
        "elapsed_ms": elapsed_ms,
        "steps": 3,
        "decisions": 3,
        "text_calls": 0,
        "cost": 0.001,
        "url": "https://www.google.com/travel/flights",
        "human_wait_ms": 0,
        "needs_human": False,
        "ok": ok,
    }


def test_a_bench_task_short_of_its_runs_makes_no_speed_claim():
    rows = [bench_row(elapsed_ms=1_000), bench_row(elapsed_ms=3_000), bench_row(None, 0, "skipped", "host_resting")]
    (row,) = bench.summarise(rows, requested=3)
    assert (row["runs"], row["requested"], row["skipped"], row["short"]) == (2, 3, 1, True)
    assert row["success_rate"] == 1.0
    assert (row["median_ms"], row["p90_ms"], row["median_decisions"], row["median_cost"]) == (None, None, None, None)
    (ratio,) = bench.ratio_rows([row], baseline={"flights": 66_414})
    assert (ratio["ratio"], ratio["passed"]) == (None, False)
    assert "2 of 3 runs measured, no speed claim" in cli.summary_line(row)
    assert "1 skipped" in cli.summary_line(row)
    assert "2 of 3 runs measured" in cli.ratio_line(ratio) and "FAIL" in cli.ratio_line(ratio)
    (full,) = bench.summarise(rows[:2], requested=2)
    assert (full["short"], full["median_ms"]) == (False, 2_000)
    (unasked,) = bench.summarise(rows)
    assert (unasked["short"], unasked["median_ms"]) == (False, 2_000)


def test_a_bench_task_a_person_helped_is_short_of_its_runs_too():
    helped = [bench_row(elapsed_ms=1_000), {**bench_row(None, 60_000), "human_wait_ms": 5_000}]
    (row,) = bench.summarise(helped, requested=2)
    assert (row["runs"], row["human"], row["short"], row["median_ms"]) == (1, 1, True, None)
    (ratio,) = bench.ratio_rows([row], baseline={"flights": 66_414})
    assert ratio["passed"] is False


def test_the_live_bench_command_says_what_was_skipped_and_is_incomplete(monkeypatch, capsys):
    live = [bench_row(), bench_row(None, 0, "skipped", "host_resting")]
    offline = [{**bench_row(), "task": "form_fill", "url": "http://127.0.0.1/checkout.html"}]
    monkeypatch.setattr(bench, "run_offline", lambda *_a, **_k: offline)
    monkeypatch.setattr(bench, "run_live", lambda *_a, **_k: live)
    monkeypatch.setattr(bench, "flash_baseline", lambda: {"flights": 66_414})
    monkeypatch.setattr(cli, "load", lambda: KEYED)
    assert cli.main(["bench", "--live", "--runs", "2"]) == 1
    out = capsys.readouterr().out
    assert "form_fill: 1/1 verified; 1 of 2 runs measured, no speed claim" in out
    assert "flights: 1/1 verified, 1 skipped; 1 of 2 runs measured, no speed claim" in out
    assert "1 attempt(s) skipped, never sent and counted as neither a pass nor a failure: host_resting x1" in out
    assert "INCOMPLETE: 1 attempt(s) were skipped" in out
    assert cli.main(["bench", "--live", "--runs", "2", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert payload["skipped"] == {"host_resting": {"attempts": 1, "hosts": ["www.google.com"]}}


def test_yesterdays_attempts_do_not_count_toward_today(make, clock, ends):
    ledger = make(budget=1)
    clock.now = LATE
    ends(Result(status="done", http_status=429))
    corpus.run_task(task(), KEYED, None, ledger)
    assert corpus.run_task(task(), KEYED, None, ledger)["reason"] == "host_resting"
    clock.now = NEXT_MORNING
    ends(Result(status="done", final_page={"text": "hello"}))
    assert corpus.run_task(task(verify={"text_contains": ["hello"]}), KEYED, None, ledger)["passed"] is True
    assert counts(ledger) == {"shop.test": 1}
    assert len(lines(ledger, "2026-09-23")) == 1 and len(lines(ledger, "2026-09-24")) == 1


def test_an_attempt_that_ends_after_midnight_is_settled_on_the_day_it_started(make, clock):
    ledger = make()
    clock.now = LATE
    claim = ledger.claim("https://shop.test/")
    clock.now = NEXT_MORNING
    ledger.settle(claim, {"status": "done"})
    assert lines(ledger, "2026-09-23")[0]["outcome"] == "done"
    assert not ledger.path("2026-09-24").exists()


def test_a_settled_attempt_whose_line_went_missing_is_written_again(make):
    ledger = make()
    claim = ledger.claim("https://shop.test/", "t")
    ledger.path("2026-09-23").write_text("not json\n")
    assert ledger.settle(claim, {"status": "done", "http_status": 429}) == "http 429"
    (line,) = lines(ledger)
    assert (line["task"], line["outcome"], line["why"]) == ("t", "refused", "http 429")


def test_the_machine_ledger_lives_beside_the_session_state_and_follows_the_config(tmp_path):
    env = {"XDG_STATE_HOME": str(tmp_path), "JEV_RA_HOST_DAILY_BUDGET": "5", "JEV_RA_HOST_GAP_S": "2.5"}
    ledger = machine_ledger(config.load(env), env)
    assert ledger.directory == tmp_path / "jev-ra" / "traffic"
    assert (ledger.budget, ledger.gap_s, ledger.rest_s) == (5, 2.5, 86400.0)


def test_the_budget_gap_and_rest_are_configurable(tmp_path):
    defaults = config.load({})
    assert (defaults.host_daily_budget, defaults.host_gap_s, defaults.host_rest_s) == (40, 10.0, 86400.0)
    chosen = config.load({"JEV_RA_HOST_DAILY_BUDGET": "12", "JEV_RA_HOST_GAP_S": "0", "JEV_RA_HOST_REST_S": "600"})
    assert (chosen.host_daily_budget, chosen.host_gap_s, chosen.host_rest_s) == (12, 0.0, 600.0)
    invalid = config.load({"JEV_RA_HOST_DAILY_BUDGET": "0", "JEV_RA_HOST_GAP_S": "-1", "JEV_RA_HOST_REST_S": "soon"})
    assert (invalid.host_daily_budget, invalid.host_gap_s, invalid.host_rest_s) == (40, 10.0, 86400.0)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"host_daily_budget": 7, "host_gap_s": 30, "host_rest_s": 3600}))
    stored = config.load({}, path=path)
    assert (stored.host_daily_budget, stored.host_gap_s, stored.host_rest_s) == (7, 30.0, 3600.0)
    assert config.load({"JEV_RA_HOST_DAILY_BUDGET": "9"}, path=path).host_daily_budget == 9
