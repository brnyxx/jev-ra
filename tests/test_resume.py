"""A run that stopped for a human check carries on from its last page and history when resumed."""

import json

import pytest

from jev_ra import cli, config, runs
from jev_ra.agent import Agent
from jev_ra.errors import JevRaError
from jev_ra.pacing import Pacer
from tests.test_agent import CLICK_SUBMIT, DONE, FakeSession, agent_with, decider, page
from tests.test_human_handoff import PLAN, VALUES, Person, scripted
from tests.test_mcp_server import call, payload, server_with

GOAL = "Place an order for Ada Lovelace with express shipping."


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("JEV_RA_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    return tmp_path / "jev-ra" / "runs"


def checked(n=0, url="http://127.0.0.1/form.html"):
    return {**page(n, url=url, text="One more step"), "challenge": "reCAPTCHA"}


def stopped(session=None):
    """A run that clicked once and then met a check nobody could clear."""
    session = session or FakeSession([page(0), checked(1), page(2)])
    result = agent_with(decider([CLICK_SUBMIT]), session=session).run("submit the form")
    assert result.reason == "needs_human"
    return result, session


def test_a_check_nobody_cleared_hands_back_a_token_to_resume_it(state):
    result, _session = stopped()
    assert result.detail["resume"] == result.run_id
    assert result.run_id in result.detail["next_step"]
    stored = json.loads((state / f"{result.run_id}.json").read_text())
    kept = stored["resume"]
    assert kept["goal"] == "submit the form"
    assert kept["url"] == "http://127.0.0.1/form.html"
    assert "history" not in kept
    assert [step["target_label"] for step in stored["steps"]] == ["Search flights"]
    assert kept["target_id"] == "fake-target"


def test_the_resume_state_never_holds_the_values_it_was_given(state):
    session = FakeSession([page(0), checked(1)])
    result = agent_with(decider([CLICK_SUBMIT]), session=session).run("submit", values={"password": "hunter2"})
    stored = (state / f"{result.run_id}.json").read_text()
    assert "hunter2" not in stored
    assert json.loads(stored)["resume"]["spent"] == []


def test_a_resumed_run_carries_on_from_the_stored_history_and_counts(state):
    result, session = stopped()
    session.index = 2
    decide = decider([DONE])
    resumed = agent_with(decide, session=session).run(resume=result.run_id)
    assert (resumed.status, resumed.reason) == ("done", "goal_achieved")
    assert resumed.run_id == result.run_id
    assert resumed.steps == result.steps
    assert resumed.decisions == result.decisions + 1
    first_state, _questions = decide.seen[0]
    assert first_state["goal"] == "submit the form"
    assert [line["action"] for line in first_state["recent_actions"]] == ["Search flights"]
    stored = json.loads((state / f"{result.run_id}.json").read_text())
    assert stored["status"] == "done" and "resume" not in stored


def test_a_resumed_run_has_only_the_steps_that_are_left(state):
    result, session = stopped()
    session.index = 2
    resumed = agent_with(decider([CLICK_SUBMIT]), session=session).run(resume=result.run_id, max_steps=2)
    assert (resumed.status, resumed.reason) == ("budget", "max_steps (2) reached")
    assert len(resumed.steps) == 2


def test_a_resumed_run_keeps_the_values_it_already_typed_spent(state):
    fill = {
        "operation": {"choice": "TYPE_TEXT", "confidence": 0.9, "probabilities": {"TYPE_TEXT": 1.0}},
        "type_text_target": {"choice": "e1", "confidence": 0.9, "probabilities": {"e1": 1.0}},
        "value_for_field": {"choice": "city", "confidence": 0.9, "probabilities": {"city": 1.0}},
        "goal_achieved": {"noul": 0.1},
    }
    session = FakeSession([page(0), checked(1), page(2)])
    result = agent_with(decider([fill]), session=session).run("book it", values={"city": "Busan", "name": "Ada"})
    assert json.loads((state / f"{result.run_id}.json").read_text())["resume"]["spent"] == ["city"]
    session.index = 2
    decide = decider([DONE])
    agent_with(decide, session=session).run(values={"city": "Busan", "name": "Ada"}, resume=result.run_id)
    first_state, _questions = decide.seen[0]
    assert first_state["values_available"] == ["name"]


def test_a_resumed_run_opens_its_page_again_when_the_browser_is_elsewhere(state):
    result, _session = stopped()
    elsewhere = FakeSession([page(0, url="about:blank"), page(1)])
    opened = []
    original = elsewhere.open

    def open_and_remember(url):
        opened.append(url)
        elsewhere.index = 1
        return original(url)

    elsewhere.open = open_and_remember
    resumed = agent_with(decider([DONE]), session=elsewhere).run(resume=result.run_id)
    assert opened == ["http://127.0.0.1/form.html"]
    assert resumed.status == "done"


def test_only_a_run_that_stopped_for_a_person_can_be_resumed(state):
    finished = agent_with(decider([DONE])).run("confirm the page")
    with pytest.raises(JevRaError, match="needs_human"):
        agent_with(decider([DONE])).run(resume=finished.run_id)
    with pytest.raises(runs.RunMissing):
        agent_with(decider([DONE])).run(resume="000000000000")


def test_a_token_that_is_not_a_run_id_never_becomes_a_path(state, tmp_path):
    (tmp_path / "secret.json").write_text(json.dumps({"reason": "needs_human", "resume": {"goal": "x"}}))
    with pytest.raises(runs.RunMissing, match="not a run id"):
        agent_with(decider([DONE])).run(resume="../../secret")


def test_a_resume_that_names_another_goal_is_refused(state):
    result, session = stopped()
    with pytest.raises(JevRaError, match="goal"):
        agent_with(decider([DONE]), session=session).run("do something else", resume=result.run_id)


def test_a_run_needs_a_goal_or_a_run_to_resume(state):
    with pytest.raises(JevRaError, match="goal"):
        agent_with(decider([DONE])).run()


def test_the_mcp_tool_resumes_a_run_by_its_token(state):
    session = FakeSession([page(0), checked(1), page(2)])
    server, _browser, _session = server_with(session=session, decide=decider([CLICK_SUBMIT, DONE]))
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    first = payload(call(server, "browser_run", goal="submit the form"))
    assert first["reason"] == "needs_human"
    session.index = 2
    resumed = payload(call(server, "browser_run", resume=first["detail"]["resume"]))
    assert (resumed["status"], resumed["run_id"]) == ("done", first["run_id"])
    assert len(resumed["steps"]) == 1


def test_the_mcp_tool_needs_a_goal_or_a_token(state):
    server, _browser, _session = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    result = call(server, "browser_run")
    assert result.is_error
    assert "resume" in result.content[0].text


def test_the_mcp_tool_opens_a_browser_to_resume_in_when_none_is_open(state):
    result, _session = stopped()
    fresh = FakeSession([page(0, url="about:blank"), page(1)])
    fresh.open = lambda url: (setattr(fresh, "index", 1), fresh.observe())[1]
    server, _browser, _session = server_with(session=fresh, decide=decider([DONE]))
    resumed = payload(call(server, "browser_run", resume=result.run_id))
    assert (resumed["status"], resumed["run_id"]) == ("done", result.run_id)


class Visible(FakeSession):
    """A session someone at this machine can see."""

    def __init__(self, pages=None, **options):
        super().__init__(pages, **options)
        self.presenter = self

    def hidden(self):
        return ""

    def present(self, site, check):
        return None


@pytest.fixture
def cli_sessions(monkeypatch, state):
    made = []

    def factory(_config=None, target_id=None, profile=None, **_kwargs):
        session = Visible([page(0), checked(1), page(2)] if target_id is None else [page(2)], profile=profile)
        session.target_id = target_id or f"target-{len(made) + 1}"
        made.append(session)
        return session

    class Client:
        def __init__(self, _config, **_kwargs):
            self.decide = decider([CLICK_SUBMIT, DONE])

        def close(self):
            return None

    monkeypatch.setattr(cli, "Session", factory)
    monkeypatch.setattr(cli, "DecisionClient", Client)
    monkeypatch.setattr("jev_ra.agent.SHARED", Pacer(backoff=0, sleep=lambda _seconds: None))
    monkeypatch.setenv("JEV_RA_HUMAN_WAIT_S", "0")
    return made


def test_the_cli_leaves_the_check_open_and_resumes_in_the_same_tab(cli_sessions, capsys):
    assert cli.main(["run", "http://127.0.0.1/form.html", "submit the form", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["reason"] == "needs_human"
    assert cli_sessions[0].closed is False
    assert cli.main(["run", "--resume", first["run_id"], "--json"]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert (resumed["status"], resumed["run_id"]) == ("done", first["run_id"])
    assert cli_sessions[1].target_id == "target-1"
    assert cli_sessions[1].closed is True


def test_the_cli_tells_a_person_what_to_do_about_a_check(cli_sessions, capsys):
    cli.main(["run", "http://127.0.0.1/form.html", "submit the form"])
    out = capsys.readouterr().out
    assert out.startswith("escalate: needs_human")
    assert "--resume" in out


def test_the_cli_needs_an_address_and_a_goal_or_a_run_to_resume(cli_sessions, capsys):
    assert cli.main(["run", "--json"]) == 1
    assert "--resume" in capsys.readouterr().err


@pytest.mark.browser
def test_a_timed_out_check_resumes_in_the_browser_and_reaches_the_goal(session, fixture_server, state):
    session.presenter = Person(session, clears=False)
    env = config.load({"JEV_RA_HUMAN_WAIT_S": "0.3"})
    pacer = Pacer(backoff=0, sleep=lambda _seconds: None)
    first = Agent(
        session=session, config=env, decide=scripted([("CLICK", "Check out", None)]), prefetch=False, pacer=pacer
    )
    stopped = first.run(GOAL, values=VALUES, url=f"{fixture_server}/sites/checkout-link.html")
    assert stopped.reason == "needs_human"
    session.presenter = Person(session)
    decide = scripted(PLAN)
    again = Agent(session=session, config=config.load({}), decide=decide, prefetch=False, pacer=pacer)
    resumed = again.run(values=VALUES, resume=stopped.detail["resume"])
    assert (resumed.status, resumed.reason) == ("done", "goal_achieved")
    assert [step["operation"] for step in resumed.steps] == ["CLICK", "TYPE_TEXT", "TYPE_TEXT", "SELECT", "CLICK"]
    assert "Order confirmed" in resumed.final_page["text"]
    assert [line["action"] for line in decide.calls[0]["recent_actions"]] == ["Check out"]
    assert resumed.human_wait_ms >= stopped.human_wait_ms
