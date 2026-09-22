"""Every number and every payload a tool takes is held to a range at the edge it arrives at."""

import pytest

from jev_ra import cli, config
from jev_ra.agent import Agent
from jev_ra.browser import MAX_ELEMENTS
from jev_ra.mcp_server import Browser, build_server
from tests.test_mcp_server import call, payload, server_with
from tests.test_search import CONTENT_PAGE, SERP_PAGE, FakeTab, greedy_decide


@pytest.fixture
def steps_asked(monkeypatch):
    """Every max_steps a run is finally started with."""
    seen = []
    original = Agent.run

    def record(self, goal, values=None, max_steps=None, url=None):
        seen.append(max_steps)
        return original(self, goal, values=values, max_steps=max_steps, url=url)

    monkeypatch.setattr(Agent, "run", record)
    return seen


def searching_server():
    """A server whose search finds a two-link SERP, so the page cap is what limits the reading."""
    tabs = []

    def factory():
        tab = FakeTab(
            page=SERP_PAGE if not tabs else CONTENT_PAGE, hrefs={1: "https://one.test/", 2: "https://two.test/"}
        )
        tabs.append(tab)
        return tab

    return build_server(Browser(config=config.load({}), session_factory=factory, decide=greedy_decide))


@pytest.mark.parametrize(("asked", "given"), ((0, 1), (-5, 1), (1000, 200), (200, 200), (7, 7)))
def test_max_steps_is_held_between_one_and_two_hundred(asked, given, steps_asked):
    server, _browser, _fake = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    payload(call(server, "browser_run", goal="confirm the page", max_steps=asked))
    assert steps_asked == [given]


@pytest.mark.parametrize(("asked", "shown"), ((0, 1), (-2, 1), (900, 2), (12, 2), (1, 1)))
def test_max_elements_is_held_between_one_and_the_snapshot_cap(asked, shown):
    server, _browser, _fake = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    result = payload(call(server, "browser_observe", max_elements=asked))
    assert result["elements"] == ["[e1] textbox City", "[e2] button Search flights"][:shown]


@pytest.mark.parametrize(("asked", "read"), ((0, 1), (-3, 1), (99, 2), (1, 1)))
def test_max_pages_is_held_between_one_and_ten(asked, read):
    found = payload(call(searching_server(), "browser_search", query="godel", max_pages=asked))
    assert len(found["results"]) == read


def test_too_many_values_are_refused_with_the_limit_named():
    server, _browser, _fake = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    failed = call(server, "browser_run", goal="x", values={f"n{n}": "v" for n in range(51)})
    assert failed.is_error
    assert "50" in failed.content[0].text


def test_values_that_are_too_long_in_total_are_refused_with_the_limit_named():
    server, _browser, _fake = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    failed = call(server, "browser_act", instruction="x", values={"bio": "a" * 20_001})
    assert failed.is_error
    assert "20000" in failed.content[0].text.replace(",", "")


def test_values_inside_both_limits_still_go_through():
    server, _browser, _fake = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    result = payload(call(server, "browser_run", goal="x", values={"name": "Ada Lovelace"}))
    assert result["status"] == "done"


def test_the_cli_holds_the_same_flags_to_the_same_range():
    parser = cli.build_parser()
    assert parser.parse_args(["run", "https://x.test", "goal", "--max-steps", "0"]).max_steps == 1
    assert parser.parse_args(["run", "https://x.test", "goal", "--max-steps", "9999"]).max_steps == 200
    assert parser.parse_args(["run", "https://x.test", "goal", "--max-steps", "7"]).max_steps == 7
    assert parser.parse_args(["search", "q", "--max-pages", "0"]).max_pages == 1
    assert parser.parse_args(["search", "q", "--max-pages", "40"]).max_pages == 10
    assert parser.parse_args(["observe", "--max-elements", "0"]).max_elements == 1
    assert parser.parse_args(["observe", "--max-elements", "9999"]).max_elements == MAX_ELEMENTS
