import json

import pytest

from jev_ra import cli
from jev_ra.decide import Reply
from tests.test_agent import FakeSession, answer


@pytest.fixture
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("JEV_RA_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    return tmp_path / "state" / "jev-ra" / "session.json"


class FakeClient:
    def __init__(self, _config, **_kwargs):
        self.closed = False

    def decide(self, state, questions):
        return Reply(
            answers={"operation": answer("DONE"), "goal_achieved": {"noul": 0.95}},
            latency_ms=7,
            usage={"cost": 0.0003},
        )

    def close(self):
        self.closed = True


class ScreenshotSession(FakeSession):
    def screenshot(self):
        return b"jpeg"


@pytest.fixture
def fake_browser(monkeypatch):
    sessions = []

    def factory(_config=None, target_id=None, **_kwargs):
        session = ScreenshotSession()
        session.target_id = target_id or f"target-{len(sessions) + 1}"
        sessions.append(session)
        return session

    monkeypatch.setattr(cli, "Session", factory)
    monkeypatch.setattr(cli, "DecisionClient", FakeClient)
    return sessions


def test_parse_values_accepts_repeated_name_equals_text():
    assert cli.parse_values(["city=London", "note=a=b"]) == {"city": "London", "note": "a=b"}
    assert cli.parse_values(None) == {}
    with pytest.raises(ValueError, match="--value expects NAME=TEXT"):
        cli.parse_values(["city"])


def test_run_json_prints_the_result(state_home, fake_browser, capsys):
    assert cli.main(["run", "http://127.0.0.1/form.html", "confirm the page", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "done"
    assert result["decisions"] == 1
    assert result["cost"] == pytest.approx(0.0003)
    assert fake_browser[0].closed is True


def test_run_without_json_prints_a_readable_summary(state_home, fake_browser, capsys):
    assert cli.main(["run", "http://127.0.0.1/form.html", "confirm the page"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("done: goal_achieved")
    assert "0 steps, 1 decisions, 0 text calls" in out


def test_run_leaves_no_stateful_session_behind(state_home, fake_browser):
    cli.main(["run", "http://127.0.0.1/form.html", "goal", "--json"])
    assert not state_home.exists()


def test_open_writes_the_session_file_and_close_removes_it(state_home, fake_browser, capsys):
    assert cli.main(["open", "http://127.0.0.1/form.html", "--json"]) == 0
    stored = json.loads(state_home.read_text())
    assert stored["target_id"] == "target-1"
    assert stored["url"] == "http://127.0.0.1/form.html"
    capsys.readouterr()
    assert cli.main(["close"]) == 0
    assert not state_home.exists()
    assert capsys.readouterr().out.strip() == "closed"


def test_stateful_commands_reattach_to_the_stored_target(state_home, fake_browser, capsys):
    cli.main(["open", "http://127.0.0.1/form.html"])
    capsys.readouterr()
    assert cli.main(["observe", "--json"]) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["elements"] == ["[e1] textbox City", "[e2] button Search flights"]
    assert fake_browser[-1].target_id == "target-1"


def test_single_step_commands_move_the_stored_session(state_home, fake_browser, capsys):
    cli.main(["open", "http://127.0.0.1/form.html"])
    capsys.readouterr()
    assert cli.main(["click", "e2"]) == 0
    assert cli.main(["type", "e1", "London"]) == 0
    assert fake_browser[-1].acted == [("e1", "fill", "London")]
    assert "Booking form" in capsys.readouterr().out


def test_commands_without_an_open_session_fail_with_one_line(state_home, fake_browser, capsys):
    assert cli.main(["observe"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "No open session. Run `jev-ra open URL` first."


def test_a_missing_ref_fails_with_one_line(state_home, fake_browser, capsys):
    cli.main(["open", "http://127.0.0.1/form.html"])
    capsys.readouterr()
    assert cli.main(["click", "e9"]) == 1
    assert "No click action for e9" in capsys.readouterr().err


def test_bare_invocation_prints_help(capsys):
    assert cli.main([]) == 0
    assert "COMMAND" in capsys.readouterr().out


def test_unreadable_session_state_is_ignored(state_home, fake_browser, capsys):
    state_home.parent.mkdir(parents=True)
    state_home.write_text("{not json")
    assert cli.main(["observe"]) == 1
    assert "No open session" in capsys.readouterr().err


def test_a_stored_session_that_is_gone_is_reported_and_cleared(state_home, fake_browser, monkeypatch, capsys):
    state_home.parent.mkdir(parents=True)
    state_home.write_text(json.dumps({"target_id": "gone", "url": "http://x/"}))

    class Gone:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("the daemon is not running")

    monkeypatch.setattr(cli, "Session", Gone)
    assert cli.main(["observe"]) == 1
    assert "The stored session is gone" in capsys.readouterr().err
    assert not state_home.exists()


def test_clear_state_is_quiet_when_nothing_is_stored(state_home):
    cli.clear_state()
    assert not state_home.exists()


def test_the_human_result_rendering_shows_each_step():
    result = {
        "status": "done",
        "reason": "goal_achieved",
        "url": "http://127.0.0.1/form.html",
        "steps": [
            {
                "n": 1,
                "operation": "TYPE_TEXT",
                "target_label": "City",
                "text": "London",
                "probability": 0.9,
                "latency_ms": 300,
                "page_changed": True,
            },
            {
                "n": 2,
                "operation": "CLICK",
                "target_label": "Search flights",
                "text": None,
                "probability": 0.8,
                "latency_ms": 120,
                "page_changed": False,
            },
        ],
        "decisions": 2,
        "text_calls": [],
        "elapsed_ms": 900,
        "cost": 0.0003,
    }
    lines = cli.result_lines(result)
    assert lines[0] == "done: goal_achieved"
    assert "1. TYPE_TEXT City 'London'" in lines[2]
    assert "2. CLICK Search flights" in lines[3]
    assert lines[-1].endswith("$0.000300")


def test_extract_runs_through_the_cli(state_home, fake_browser, capsys):
    cli.main(["open", "http://127.0.0.1/form.html"])
    capsys.readouterr()
    assert cli.main(["extract", "--mode", "elements", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "elements"
    assert payload["elements"][0]["label"] == "City"


def test_act_runs_one_decided_step_through_the_cli(state_home, fake_browser, capsys):
    cli.main(["open", "http://127.0.0.1/form.html"])
    capsys.readouterr()
    assert cli.main(["act", "confirm the page", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "done"
    assert payload["decisions"] == 1


def test_no_decision_refuses_to_ask_the_model():
    with pytest.raises(RuntimeError, match="never calls the decision model"):
        cli.no_decision(None, None)


def test_screenshot_writes_the_viewport_to_a_path(state_home, fake_browser, tmp_path, capsys):
    cli.main(["open", "http://127.0.0.1/form.html"])
    capsys.readouterr()
    path = tmp_path / "shot.jpg"
    assert cli.main(["screenshot", str(path)]) == 0
    assert path.read_bytes() == b"jpeg"


def test_chrome_check_reports_a_browser_that_will_not_open(monkeypatch):
    class Broken:
        def __init__(self, _config):
            pass

        def open(self, _url):
            raise RuntimeError("no debugging port")

        def close(self):
            pass

    monkeypatch.setattr(cli, "Session", Broken)
    ok, detail, source = cli.chrome_check(cli.load())
    assert ok is False
    assert "no debugging port" in detail
    assert source is None


def test_the_skill_text_reports_a_missing_guide(monkeypatch):
    class MissingGuide:
        def with_name(self, _name):
            return self

        def resolve(self):
            return self

        @property
        def parents(self):
            return [self, self]

        def __truediv__(self, _name):
            return self

        def exists(self):
            return False

    monkeypatch.setattr(cli, "Path", lambda _path: MissingGuide())
    with pytest.raises(cli.GuideMissing, match=r"AGENTS\.md is missing"):
        cli.skill_text()


def test_mcp_runs_the_stdio_server(monkeypatch):
    from jev_ra import mcp_server

    served = []
    monkeypatch.setattr(mcp_server, "main", lambda: served.append(True))
    assert cli.main(["mcp"]) == 0
    assert served == [True]


def test_search_prints_the_ranked_pages(state_home, fake_browser, monkeypatch, capsys):
    from jev_ra import search as search_module

    payload = {
        "query": "godel",
        "elapsed_ms": 12,
        "results": [
            {"rank": 1, "title": "Proof", "label": "Proof", "url": "https://x/proof", "answers_goal": 0.9},
            {"rank": 2, "label": "Overview", "url": "https://x/overview", "answers_goal": 0.4},
        ],
    }
    monkeypatch.setattr(search_module, "search", lambda *_args, **_kwargs: payload)
    assert cli.main(["search", "godel", "explain the proof"]) == 0
    out = capsys.readouterr().out
    assert "godel — 2 pages in 12 ms" in out
    assert "1. Proof (answers_goal=0.90)" in out
    assert "2. Overview (answers_goal=0.40)" in out
