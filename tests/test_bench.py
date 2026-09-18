import json

import pytest

from jev_ra import bench, cli, config

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


def test_the_ratio_table_marks_three_times_faster_as_a_pass():
    measured = [
        {"task": "wikipedia", "elapsed_ms": 3800, "status": "done", "steps": 6, "decisions": 7, "cost": 0.002},
        {"task": "flights", "elapsed_ms": 30000, "status": "done", "steps": 12, "decisions": 13, "cost": 0.01},
        {"task": "oliveyoung_sort", "elapsed_ms": 3000, "status": "escalate", "steps": 2, "decisions": 3},
    ]
    rows = bench.ratio_rows(measured, baseline={"wikipedia": 23058, "flights": 66414, "oliveyoung_sort": 15071})
    assert rows[0]["ratio"] == pytest.approx(6.07, abs=0.01)
    assert rows[0]["passed"] is True
    assert rows[1]["ratio"] == pytest.approx(2.21, abs=0.01)
    assert rows[1]["passed"] is False
    # Fast but unfinished is still a failure.
    assert rows[2]["ratio"] == pytest.approx(5.02, abs=0.01)
    assert rows[2]["passed"] is False


def test_a_task_without_a_baseline_row_reports_no_ratio():
    rows = bench.ratio_rows([{"task": "new_task", "elapsed_ms": 1000, "status": "done"}], baseline={})
    assert rows[0]["ratio"] is None
    assert rows[0]["passed"] is False


def test_live_bench_refuses_to_run_without_a_key():
    with pytest.raises(RuntimeError, match="needs a Jev key"):
        bench.run_live(config.load({}))


@pytest.mark.browser
def test_offline_bench_runs_every_fixture_task(session):
    measured = bench.run_offline(config.load({}), session=session)
    assert [row["task"] for row in measured] == ["form_fill", "catalog_sort"]
    assert all(row["status"] == "done" for row in measured)
    assert all(row["elapsed_ms"] > 0 for row in measured)
    assert all(row["text_calls"] == 0 for row in measured)
    assert [row["steps"] for row in measured] == [4, 2]


@pytest.mark.browser
def test_the_bench_command_prints_ms_and_steps(capsys, monkeypatch):
    monkeypatch.delenv("JEV_RA_API_KEY", raising=False)
    assert cli.main(["bench"]) == 0
    out = capsys.readouterr().out
    assert "offline (scripted decisions, local fixtures, no network):" in out
    assert "form_fill: done in" in out
    assert "4 steps" in out
    assert "--live" in out


@pytest.mark.browser
def test_the_bench_command_json_carries_the_recorded_baseline(capsys):
    assert cli.main(["bench", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline_flash_ms"]["wikipedia"] == 23058
    assert [row["task"] for row in payload["offline"]] == ["form_fill", "catalog_sort"]


def test_live_bench_is_gated_on_a_key_in_the_command(capsys, monkeypatch, tmp_path):
    for name in ("JEV_RA_API_KEY", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(bench, "run_offline", lambda *_a, **_k: [])
    assert cli.main(["bench", "--live"]) == 1
    assert "needs a Jev key" in capsys.readouterr().err
