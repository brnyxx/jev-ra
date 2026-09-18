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


@pytest.fixture
def fake_browser(monkeypatch):
    sessions = []

    def factory(_config=None, target_id=None, **_kwargs):
        session = FakeSession()
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
