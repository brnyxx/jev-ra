"""Every run leaves a file behind, and `jev-ra trace` renders it as a table or a page."""

import json
import os
import re
from pathlib import Path

import pytest

from jev_ra import cli, runs, trace
from jev_ra.agent import Result
from jev_ra.profile import CATEGORIES
from tests.test_agent import CLICK_SUBMIT, DONE, FakeSession, agent_with, decider

DEMO = Path(__file__).resolve().parents[1] / "docs" / "assets-site" / "demo-run.json"


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("JEV_RA_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    return tmp_path / "jev-ra" / "runs"


def a_run():
    return agent_with(decider([CLICK_SUBMIT, DONE]), session=FakeSession()).run("submit the form")


def test_the_runs_directory_sits_beside_the_session_state():
    assert runs.runs_dir({"XDG_STATE_HOME": "/s"}) == Path("/s/jev-ra/runs")


def test_a_run_carries_an_id_and_leaves_its_result_behind(state):
    result = a_run()
    assert len(result.run_id) == 12
    stored = json.loads((state / f"{result.run_id}.json").read_text())
    assert stored["run_id"] == result.run_id
    assert stored["status"] == "done"
    assert stored["steps"] == result.steps


def test_two_runs_never_share_an_id(state):
    assert a_run().run_id != a_run().run_id


def test_a_run_id_supplied_by_the_caller_is_used_once(state):
    agent = agent_with(decider([CLICK_SUBMIT, DONE]), session=FakeSession())
    agent.run_id = "abcdef012345"
    assert agent.run("submit the form").run_id == "abcdef012345"
    assert agent.run("submit the form").run_id != "abcdef012345"


def test_only_the_newest_two_hundred_runs_are_kept(state):
    state.mkdir(parents=True)
    for index in range(runs.CAP + 5):
        path = state / f"run{index:04d}.json"
        path.write_text("{}")
        # Written in order, and the cap is about which ones are oldest, so date them in order too.
        os.utime(path, (index, index))
    runs.prune(state)
    kept = sorted(path.stem for path in state.glob("*.json"))
    assert len(kept) == runs.CAP
    assert kept[0] == "run0005"
    assert kept[-1] == f"run{runs.CAP + 4:04d}"


def test_a_directory_that_cannot_be_written_never_ends_a_run(state):
    state.parent.mkdir(parents=True)
    state.parent.joinpath("runs").write_text("not a directory")
    result = a_run()
    assert result.status == "done"
    assert result.run_id


def test_an_unknown_run_id_is_a_sentence_not_a_traceback(state, capsys):
    assert cli.main(["trace", "0123456789ab"]) == 1
    assert "0123456789ab" in capsys.readouterr().err


def test_trace_prints_a_step_table(state, capsys):
    result = a_run()
    assert cli.main(["trace", result.run_id]) == 0
    printed = capsys.readouterr().out
    assert result.run_id in printed
    assert "done · goal_achieved" in printed
    assert "CLICK" in printed
    assert "Search flights" in printed
    assert "1 steps, 2 decisions" in printed


def test_trace_json_prints_the_stored_result(state, capsys):
    result = a_run()
    assert cli.main(["trace", result.run_id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == result.run_id


def test_trace_html_writes_one_file_that_needs_nothing_else(state, tmp_path, capsys):
    result = a_run()
    page = tmp_path / "run.html"
    assert cli.main(["trace", result.run_id, "--html", str(page)]) == 0
    html = page.read_text()
    capsys.readouterr()
    assert html.startswith("<!doctype html>")
    assert result.run_id in html
    assert "<script src=" not in html
    assert "<link " not in html
    assert "https://" not in html


def test_the_page_carries_the_run_the_demo_data_shape_describes(state, tmp_path, capsys):
    result = a_run()
    page = tmp_path / "run.html"
    cli.main(["trace", result.run_id, "--html", str(page)])
    capsys.readouterr()
    embedded = json.loads(re.search(r"const RUN = (\{.*?\});\n", page.read_text(), re.DOTALL).group(1))
    demo = json.loads(DEMO.read_text())
    assert set(demo) <= set(embedded)
    assert set(demo["steps"][0]) <= set(embedded["steps"][0])


def test_the_html_path_defaults_to_the_run_id(state, tmp_path, monkeypatch, capsys):
    result = a_run()
    monkeypatch.chdir(tmp_path)
    assert cli.main(["trace", result.run_id, "--html"]) == 0
    assert (tmp_path / f"{result.run_id}.html").exists()
    assert f"{result.run_id}.html" in capsys.readouterr().out


def test_a_page_escapes_whatever_the_site_put_in_the_run():
    result = Result(status="done", reason="goal_achieved", title="</script><img onerror=alert(1)>")
    html = trace.page(result.as_dict())
    assert "</script><img" not in html
    assert "<\\/script>" in html or "\\u003c/script" in html


def test_profile_prints_where_the_run_went(state, capsys):
    result = a_run()
    assert cli.main(["profile", result.run_id]) == 0
    printed = capsys.readouterr().out
    assert result.run_id in printed
    assert "decide" in printed and "wait" in printed
    assert "1 step " in printed
    assert "outside the steps" in printed


def test_profile_json_carries_the_totals_and_the_steps(state, capsys):
    result = a_run()
    assert cli.main(["profile", result.run_id, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == result.run_id
    assert set(payload["totals"]) == set(CATEGORIES)
    assert payload["steps"] == result.steps


def test_profile_refuses_a_run_it_does_not_have(state, capsys):
    assert cli.main(["profile", "0123456789ab"]) == 1
    assert "0123456789ab" in capsys.readouterr().err
