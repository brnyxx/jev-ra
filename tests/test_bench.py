import json

import pytest

from jev_ra import bench, cli, config
from tests.conftest import require_browser

pytestmark = []

FLASH_ROW = {
    "task": "wikipedia",
    "model": "google/gemini-3-flash-preview",
    "flash_mode": True,
    "wall_ms": 23058,
    "error": None,
    "steps": 4,
}


def write_rows(directory, name, rows):
    path = directory / name
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def test_the_baseline_loader_parses_the_recorded_rows():
    rows = bench.load_baseline()
    assert set(rows) == {"wikipedia", "flights", "oliveyoung_sort"}
    assert rows["wikipedia"]["flash"]["wall_ms"] == 23058
    assert rows["oliveyoung_sort"]["flash"]["wall_ms"] == 15071
    assert bench.flash_baseline() == {"wikipedia": 23058, "flights": 66414, "oliveyoung_sort": 15071}


def test_failed_and_empty_baseline_rows_are_skipped(tmp_path):
    write_rows(
        tmp_path,
        "results_x.jsonl",
        [
            FLASH_ROW,
            {"task": "flights", "flash_mode": True, "wall_ms": 0, "error": "compiled grammar is too large"},
            {"task": "flights", "flash_mode": True, "wall_ms": None, "error": None},
        ],
    )
    (tmp_path / "results_x.jsonl").write_text((tmp_path / "results_x.jsonl").read_text() + "\nnot json\n")
    rows = bench.load_baseline(tmp_path)
    assert set(rows) == {"wikipedia"}


def test_a_missing_baseline_directory_is_empty_not_an_error(tmp_path):
    assert bench.load_baseline(tmp_path / "nothing") == {}


def summary(task, median_ms, success_rate=1.0, runs=5):
    return {
        "task": task,
        "runs": runs,
        "success_rate": success_rate,
        "median_ms": median_ms,
        "median_decisions": 4,
        "median_cost": 0.001,
    }


def test_the_ratio_table_marks_three_times_faster_as_a_pass():
    summaries = [
        summary("wikipedia", 3800),
        summary("flights", 30000),
        summary("oliveyoung_sort", 3000, success_rate=0.0),
    ]
    rows = bench.ratio_rows(summaries, baseline={"wikipedia": 23058, "flights": 66414, "oliveyoung_sort": 15071})
    assert rows[0]["ratio"] == pytest.approx(6.07, abs=0.01)
    assert rows[0]["passed"] is True
    assert rows[1]["ratio"] == pytest.approx(2.21, abs=0.01)
    assert rows[1]["passed"] is False
    # Fast but never verified is still a failure.
    assert rows[2]["ratio"] == pytest.approx(5.02, abs=0.01)
    assert rows[2]["passed"] is False


def test_a_task_without_a_baseline_row_still_has_to_verify():
    assert bench.ratio_rows([summary("new_task", 1000)], baseline={})[0]["ratio"] is None
    assert bench.ratio_rows([summary("new_task", 1000)], baseline={})[0]["passed"] is True
    assert bench.ratio_rows([summary("new_task", 1000, success_rate=0.5)], baseline={})[0]["passed"] is False


def test_live_bench_refuses_to_run_without_a_key():
    with pytest.raises(RuntimeError, match="needs a Jev key"):
        bench.run_live(config.load({}))


@pytest.mark.browser
def test_offline_bench_runs_every_fixture_task(session):
    measured = bench.run_offline(config.load({}), session=session)
    assert [row["task"] for row in measured] == ["form_fill", "catalog_sort"]
    assert all(row["status"] == "done" for row in measured)
    assert all(row["ok"] for row in measured)
    assert all(row["elapsed_ms"] > 0 for row in measured)
    assert all(row["text_calls"] == 0 for row in measured)
    assert [row["steps"] for row in measured] == [4, 2]


@pytest.mark.browser
def test_the_bench_command_prints_ms_and_steps(capsys, monkeypatch):
    require_browser()
    monkeypatch.delenv("JEV_RA_API_KEY", raising=False)
    assert cli.main(["bench", "--runs", "2"]) == 0
    out = capsys.readouterr().out
    assert "offline (scripted decisions, local fixtures, no network), 2 run(s) each:" in out
    assert "form_fill: 2/2 verified, median" in out
    assert " ms, p90 " in out
    assert "--live" in out


@pytest.mark.browser
def test_the_bench_command_json_carries_the_recorded_baseline(capsys):
    require_browser()
    assert cli.main(["bench", "--json", "--runs", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline_flash_ms"]["wikipedia"] == 23058
    assert payload["runs"] == 1
    assert [row["task"] for row in payload["offline"]] == ["form_fill", "catalog_sort"]


def test_live_bench_is_gated_on_a_key_in_the_command(capsys, monkeypatch, tmp_path):
    for name in ("JEV_RA_API_KEY", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(bench, "run_offline", lambda *_a, **_k: [])
    assert cli.main(["bench", "--live"]) == 1
    assert "needs a Jev key" in capsys.readouterr().err


def offline_rows():
    return [
        {
            "task": "form_fill",
            "ok": True,
            "elapsed_ms": 100,
            "steps": 2,
            "decisions": 4,
            "cost": 0.0004,
            "text_calls": 0,
            "status": "done",
            "reason": "",
            "profile": [],
        }
    ]


def summary_rows():
    return [
        {
            "task": "form_fill",
            "runs": 1,
            "successes": 1,
            "success_rate": 1.0,
            "median_ms": 100,
            "p90_ms": 100,
            "median_steps": 2,
            "median_decisions": 4,
            "median_cost": 0.0004,
            "text_calls": 0,
            "failures": [],
        }
    ]


def ratio_table():
    return [
        {
            "task": "form_fill",
            "jev_ra_ms": 100,
            "flash_mode_ms": 1000,
            "ratio": 10.0,
            "success_rate": 1.0,
            "runs": 1,
            "decisions": 4,
            "cost": 0.0004,
            "passed": True,
        }
    ]


def test_summary_line_reports_a_task_with_no_successful_run():
    line = cli.summary_line(
        {
            "task": "flights",
            "runs": 5,
            "successes": 0,
            "median_ms": None,
            "median_decisions": None,
            "text_calls": 0,
            "failures": ["stale", "stuck_loop"],
        }
    )
    assert line == "  flights: 0/5 verified; stale, stuck_loop"


def test_summary_line_reports_the_medians():
    line = cli.summary_line(
        {
            "task": "form_fill",
            "runs": 5,
            "successes": 5,
            "median_ms": 916,
            "p90_ms": 1037,
            "median_decisions": 4,
            "text_calls": 0,
            "failures": [],
        }
    )
    assert "5/5 verified, median 916 ms, p90 1037 ms, 4 decisions, 0 text calls" in line


def test_ratio_line_renders_missing_values_as_text():
    line = cli.ratio_line(
        {
            "task": "form_fill",
            "jev_ra_ms": None,
            "flash_mode_ms": None,
            "ratio": None,
            "success_rate": 0.5,
            "runs": 2,
            "passed": False,
        }
    )
    assert "never verified" in line
    assert "no baseline row" in line
    assert "n/a" in line
    assert "FAIL" in line


def test_the_bench_command_prints_the_offline_profile(monkeypatch, capsys):
    monkeypatch.setattr(bench, "run_offline", lambda *_a, **_k: offline_rows())
    monkeypatch.setattr(bench, "summarise", lambda _runs: summary_rows())
    monkeypatch.setattr(bench, "profile_rows", lambda _runs: [{"category": "wait", "ms": 12, "share": 0.5}])
    monkeypatch.setattr(bench, "profile_table", lambda _runs: "| category | ms | share |")
    assert cli.main(["bench", "--profile", "--runs", "1"]) == 0
    assert "where the time goes (offline):" in capsys.readouterr().out


def test_the_bench_command_can_re_run_the_recorded_browser_use_script(monkeypatch, capsys):
    monkeypatch.setattr(bench, "run_offline", lambda *_a, **_k: offline_rows())
    monkeypatch.setattr(bench, "summarise", lambda _runs: summary_rows())
    monkeypatch.setattr(bench, "run_baseline", lambda _runs: [{"returncode": 0, "stdout": "", "stderr": ""}])
    assert cli.main(["bench", "--baseline", "--runs", "1"]) == 0
    assert "browser-use baseline re-run 1 time(s)" in capsys.readouterr().out


def test_the_live_bench_command_prints_the_ratio_table(monkeypatch, capsys):
    monkeypatch.setattr(bench, "run_offline", lambda *_a, **_k: offline_rows())
    monkeypatch.setattr(bench, "run_live", lambda *_a, **_k: offline_rows())
    monkeypatch.setattr(bench, "summarise", lambda _runs: summary_rows())
    monkeypatch.setattr(bench, "ratio_rows", lambda _live: ratio_table())
    monkeypatch.setattr(bench, "profile_rows", lambda _runs: [{"category": "wait", "ms": 12, "share": 0.5}])
    monkeypatch.setattr(bench, "profile_table", lambda _runs: "| category | ms | share |")
    assert cli.main(["bench", "--live", "--profile", "--runs", "1"]) == 0
    out = capsys.readouterr().out
    assert "where the time goes:" in out
    assert "PASS: every task clears the bar" in out
    assert cli.main(["bench", "--live", "--runs", "1"]) == 0
