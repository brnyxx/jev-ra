"""A soak's numbers are its aggregation, and one raised attempt is the finding."""

from pathlib import Path

import pytest

from tests.test_examples import load

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def soak():
    return load(ROOT / "scripts" / "soak.py", "soak")


def result_row(status, reason, elapsed_ms, decisions, passed, why="", raised=None, site_error=False):
    row = {
        "task": "t",
        "family": "f",
        "status": status,
        "reason": reason,
        "elapsed_ms": elapsed_ms,
        "decisions": decisions,
        "cost": 0.0,
        "passed": passed,
        "why": why,
        "site_error": site_error,
    }
    if raised:
        row["raised"] = raised
    return row


def test_the_summary_reports_pass_count_seconds_decisions_and_reasons(soak):
    rows = [
        result_row("done", "goal_achieved", 1000, 3, True),
        result_row("done", "goal_achieved", 2000, 4, True),
        result_row("escalate", "stuck_loop", 5000, 9, False, "escalate:stuck_loop"),
        result_row("raised", "ChromeError", 100, 0, False, "raised:ChromeError", raised="ChromeError"),
    ]
    summary = soak.summarise(rows)
    assert summary["runs"] == 4 and summary["passed"] == 2
    assert summary["median_s"] == 1.5 and summary["p95_s"] == 5.0
    assert summary["decisions_median"] == 4 and summary["decisions_total"] == 16
    assert summary["reasons"] == {"ChromeError": 1, "stuck_loop": 1}
    assert summary["raised"] == 1
    assert summary["site_error"] == 0


def test_the_summary_counts_the_attempts_a_site_answered_with_an_error(soak):
    rows = [
        result_row("done", "goal_achieved", 1000, 3, True),
        result_row("escalate", "blocked_by_site", 900, 0, False, "escalate:blocked_by_site", site_error=True),
        result_row("escalate", "blocked_by_site", 950, 0, False, "escalate:blocked_by_site", site_error=True),
    ]
    summary = soak.summarise(rows)
    assert summary["site_error"] == 2
    assert "site errors: 2" in "\n".join(soak.report(summary, "httpbin_form_submit"))


def test_a_soak_row_keeps_whether_the_site_answered_with_an_error(monkeypatch, soak):
    from jev_ra.agent import Result

    class Agent:
        def __init__(self, **_kwargs):
            pass

        def run(self, *_args, **_kwargs):
            return Result(status="escalate", reason="blocked_by_site", site_error=True, http_status=502)

    monkeypatch.setattr(soak, "Agent", Agent)
    row = soak.run_once(soak.task_named("httpbin_form_submit"), object(), object(), lambda *_: None)
    assert row["site_error"] is True and row["status"] == "escalate"


def test_a_clean_soak_has_no_reasons_and_no_raises(soak):
    summary = soak.summarise([result_row("done", "goal_achieved", 900, 3, True)] * 5)
    assert summary["passed"] == 5
    assert summary["reasons"] == {} and summary["raised"] == 0
    assert summary["median_s"] == 0.9


def test_an_empty_soak_reports_nothing_rather_than_dividing_by_zero(soak):
    assert soak.summarise([]) == {
        "runs": 0,
        "passed": 0,
        "median_s": None,
        "p95_s": None,
        "decisions_median": None,
        "decisions_total": 0,
        "reasons": {},
        "raised": 0,
        "site_error": 0,
        "human": 0,
        "human_wait_ms": 0,
    }


def test_the_report_prints_the_numbers_and_the_reasons(soak):
    rows = [
        result_row("done", "goal_achieved", 1000, 3, True),
        result_row("escalate", "stuck_loop", 3000, 9, False, "escalate:stuck_loop"),
    ]
    lines = soak.report(soak.summarise(rows), "wikipedia_godel")
    text = "\n".join(lines)
    assert "soak wikipedia_godel: 2 run(s) on one session" in text
    assert "passed 1/2" in text
    assert "median 2.0, p95 3.0" in text
    assert "decisions: median 6, total 12" in text
    assert "stuck_loop x1" in text and "raised: 0" in text
    assert "site errors: 0" in text


def test_a_calls_soak_with_no_growth_and_no_new_tab_does_not_leak(soak):
    summary = soak.calls_summary(100, 200_000_000, 201_500_000, 1, 1)
    assert summary["rss_growth_mb"] == 1.5
    assert summary["leaked"] is False


def test_rss_growth_over_the_limit_leaks(soak):
    summary = soak.calls_summary(100, 200_000_000, 260_000_000, 1, 1)
    assert summary["rss_growth_mb"] == 60.0
    assert summary["leaked"] is True


def test_a_new_page_target_leaks_even_with_no_rss_growth(soak):
    summary = soak.calls_summary(100, 200_000_000, 200_000_000, 1, 2)
    assert summary["rss_growth_mb"] == 0.0
    assert summary["leaked"] is True


def test_an_unmeasurable_rss_falls_back_to_the_tab_check(soak):
    quiet = soak.calls_summary(100, None, None, 1, 1)
    assert quiet["rss_growth_mb"] is None and quiet["leaked"] is False
    assert soak.calls_summary(100, None, None, 1, 2)["leaked"] is True


def test_the_calls_report_prints_the_numbers_and_the_limit(soak):
    text = "\n".join(soak.calls_report(soak.calls_summary(100, 200_000_000, 201_000_000, 1, 1)))
    assert "100 tool call(s) on one session" in text
    assert "rss growth: 1.0 MB (limit 50.0 MB)" in text
    assert "tabs: 1 before, 1 after" in text


def test_an_unknown_task_is_named_back(soak):
    with pytest.raises(SystemExit, match="unknown corpus task"):
        soak.task_named("wikipedia_lookup")
    assert soak.task_named("wikipedia_godel").family == "search_read"


class Closer:
    def __init__(self, _config=None):
        self.closed = False

    def close(self):
        self.closed = True


class Client(Closer):
    def __init__(self, _config=None):
        super().__init__()
        self.decide = lambda *_args: None


def test_a_raised_attempt_is_an_exit_one(monkeypatch, capsys, soak):
    rows = iter(
        [
            result_row("raised", "ChromeError", 100, 0, False, "raised:ChromeError", raised="ChromeError"),
            result_row("done", "goal_achieved", 1000, 3, True),
        ]
    )
    monkeypatch.setattr(soak, "load", lambda: type("C", (), {"api_key": "k"})())
    monkeypatch.setattr(soak, "Session", Closer)
    monkeypatch.setattr(soak, "DecisionClient", Client)
    monkeypatch.setattr(soak, "run_once", lambda *_args: next(rows))
    assert soak.main(["--task", "wikipedia_godel", "--runs", "2"]) == 1
    out = capsys.readouterr().out
    assert "soak wikipedia_godel: 2 run(s) on one session" in out
    assert "raised: 1" in out


def test_a_clean_soak_is_an_exit_zero(monkeypatch, soak):
    monkeypatch.setattr(soak, "load", lambda: type("C", (), {"api_key": "k"})())
    monkeypatch.setattr(soak, "Session", Closer)
    monkeypatch.setattr(soak, "DecisionClient", Client)
    monkeypatch.setattr(soak, "run_once", lambda *_args: result_row("done", "goal_achieved", 1000, 3, True))
    assert soak.main(["--task", "wikipedia_godel", "--runs", "3"]) == 0


def test_a_calls_soak_that_leaks_is_an_exit_one(monkeypatch, capsys, soak):
    monkeypatch.setattr(soak, "Session", Closer)
    monkeypatch.setattr(
        soak, "soak_calls", lambda _session, calls: soak.calls_summary(calls, 200_000_000, 260_000_000, 1, 1)
    )
    assert soak.main(["--calls", "10"]) == 1
    out = capsys.readouterr().out
    assert "10 tool call(s) on one session" in out and "rss growth: 60.0 MB" in out


def test_no_mode_at_all_is_refused(soak):
    with pytest.raises(SystemExit) as caught:
        soak.main([])
    assert caught.value.code == 2
