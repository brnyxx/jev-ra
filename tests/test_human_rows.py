"""A run that needed a person is counted apart: never a product pass, never a product failure."""

import json
from pathlib import Path

import pytest

from jev_ra import bench, cli, corpus
from jev_ra.agent import Result
from tests.test_corpus import FakeSession, fake_agent, task
from tests.test_examples import load

ROOT = Path(__file__).resolve().parents[1]
KEYED = type("Config", (), {"api_key": "k"})()


@pytest.fixture
def ended(monkeypatch):
    def install(result):
        monkeypatch.setattr(corpus, "Session", FakeSession)
        monkeypatch.setattr(corpus, "Agent", fake_agent(result))

    return install


def corpus_row(task_name="t", passed=True, why="", elapsed_ms=100, human_wait_ms=0, needs_human=False):
    return {
        "task": task_name,
        "family": "f",
        "passed": passed,
        "why": why,
        "elapsed_ms": elapsed_ms,
        "decisions": 2,
        "cost": 0.001,
        "status": "escalate" if needs_human else "done",
        "reason": "needs_human" if needs_human else "",
        "human_wait_ms": human_wait_ms,
        "needs_human": needs_human,
    }


def test_a_corpus_row_records_the_wait_and_whether_it_stopped_for_a_person(ended):
    ended(Result(status="escalate", reason="needs_human", human_wait_ms=120_000))
    row = corpus.run([task(verify={"text_contains": ["hello"]})], config=KEYED, decide=lambda *_: None)[0]
    assert (row["human_wait_ms"], row["needs_human"]) == (120_000, True)
    assert row["passed"] is None


def test_a_corpus_run_a_person_helped_through_is_set_aside_even_when_it_finished(ended):
    ended(Result(status="done", reason="goal_achieved", human_wait_ms=8_000, final_page={"text": "hello"}))
    row = corpus.run([task(verify={"text_contains": ["hello"]})], config=KEYED, decide=lambda *_: None)[0]
    assert (row["human_wait_ms"], row["needs_human"]) == (8_000, False)
    assert row["passed"] is None


def test_the_corpus_summary_counts_people_apart_from_passes_and_failures():
    rows = [
        corpus_row(),
        corpus_row(passed=False, why="escalate:stale"),
        corpus_row(passed=None, why="needs_human", human_wait_ms=120_000, needs_human=True),
        corpus_row(passed=None, why="a person cleared a check", elapsed_ms=9_000, human_wait_ms=8_000),
    ]
    (row,) = corpus.summarise(rows)
    assert (row["runs"], row["passed"], row["human"]) == (2, 1, 2)
    assert row["pass_rate"] == 0.5
    assert row["median_ms"] == 100
    assert row["why"] == ["escalate:stale"]
    assert corpus.pass_rate(rows) == 0.5
    assert corpus.reasons(rows) == {"escalate": 1}


def test_a_task_that_only_ever_needed_a_person_has_no_rate_at_all():
    (row,) = corpus.summarise([corpus_row(passed=None, why="needs_human", needs_human=True)])
    assert (row["runs"], row["passed"], row["human"], row["pass_rate"]) == (0, 0, 1, None)
    assert corpus.pass_rate([corpus_row(passed=None, why="needs_human", needs_human=True)]) == 0.0


def test_the_corpus_command_prints_the_people_column(monkeypatch, tmp_path, capsys):
    rows = [corpus_row(), corpus_row(passed=None, why="needs_human", human_wait_ms=120_000, needs_human=True)]
    monkeypatch.setattr(corpus, "run", lambda **_kwargs: rows)
    monkeypatch.setattr(corpus, "RESULTS", tmp_path)
    monkeypatch.setattr(cli, "load", lambda: object())
    assert cli.main(["corpus", "run", "--runs", "1"]) == 0
    out = capsys.readouterr().out
    assert "| human |" in out
    assert "1 set aside for a person" in out
    assert "1 attempt(s) needed a person" in out
    written = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert [line["needs_human"] for line in written] == [False, True]


def bench_row(ok=True, human_wait_ms=0, needs_human=False, elapsed_ms=1_000):
    return {
        "task": "wikipedia",
        "status": "escalate" if needs_human else "done",
        "reason": "needs_human" if needs_human else "",
        "elapsed_ms": elapsed_ms,
        "steps": 3,
        "decisions": 3,
        "text_calls": 0,
        "cost": 0.001,
        "human_wait_ms": human_wait_ms,
        "needs_human": needs_human,
        "ok": ok,
    }


def test_a_bench_run_that_needed_a_person_is_not_verified_and_not_failed():
    row = bench.verified(bench_row(ok=None, human_wait_ms=5_000), lambda _row: True)
    assert row["ok"] is None
    stopped = bench.verified(bench_row(ok=None, needs_human=True), lambda _row: False)
    assert stopped["ok"] is None


def test_the_bench_summary_keeps_people_out_of_the_rate_and_the_medians():
    rows = [
        bench_row(elapsed_ms=1_000),
        bench_row(elapsed_ms=3_000),
        bench_row(ok=None, human_wait_ms=60_000, elapsed_ms=62_000),
        bench_row(ok=None, needs_human=True, elapsed_ms=121_000),
    ]
    (row,) = bench.summarise(rows)
    assert (row["runs"], row["successes"], row["human"]) == (2, 2, 2)
    assert row["success_rate"] == 1.0
    assert row["median_ms"] == 2_000
    assert row["failures"] == []
    assert "2 set aside for a person" in cli.summary_line(row)


def test_a_bench_row_records_the_wait(monkeypatch):
    class Agent:
        def run(self, *_args, **_kwargs):
            return Result(status="escalate", reason="needs_human", human_wait_ms=120_000)

    task_ = bench.LIVE_TASKS[0]
    row = bench.measure(Agent(), task_, task_.url, task_.values, task_.max_steps)
    assert (row["human_wait_ms"], row["needs_human"], row["ok"]) == (120_000, True, None)


@pytest.fixture
def soak():
    return load(ROOT / "scripts" / "soak.py", "soak")


def test_a_soak_row_records_the_wait(monkeypatch, soak):
    class Agent:
        def __init__(self, **_kwargs):
            pass

        def run(self, *_args, **_kwargs):
            return Result(status="done", reason="goal_achieved", human_wait_ms=4_000)

    monkeypatch.setattr(soak, "Agent", Agent)
    row = soak.run_once(soak.task_named("httpbin_form_submit"), object(), object(), lambda *_: None)
    assert (row["human_wait_ms"], row["needs_human"], row["passed"]) == (4_000, False, None)


def test_the_soak_counts_people_apart_and_keeps_their_time_out_of_its_seconds(soak):
    rows = [
        {**corpus_row(elapsed_ms=1_000), "status": "done", "reason": "goal_achieved"},
        corpus_row(passed=None, why="needs_human", elapsed_ms=121_000, human_wait_ms=120_000, needs_human=True),
    ]
    summary = soak.summarise(rows)
    assert (summary["passed"], summary["human"], summary["human_wait_ms"]) == (1, 1, 120_000)
    assert summary["median_s"] == 1.0
    assert summary["reasons"] == {}
    assert "needed a person: 1 (120.0 s waiting)" in "\n".join(soak.report(summary, "t"))
