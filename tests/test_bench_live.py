"""The live bench paths, driven on the local fixture pages with scripted decisions."""

import pytest

from jev_ra import bench, config
from jev_ra.decide import Reply
from tests.conftest import require_browser

CONFIG = {"OPENROUTER_API_KEY": "test-key"}


class Closer:
    def __init__(self, _config=None):
        self.closed = False

    def close(self):
        self.closed = True


class Client:
    def __init__(self, _config):
        self.closed = False
        self.decide = done_decider

    def close(self):
        self.closed = True


def certain(choice, criteria):
    return {"choice": choice, "confidence": 0.95, "probabilities": {key: float(key == choice) for key in criteria}}


def done_decider(_state, questions):
    answers = {"operation": certain("DONE", questions["operation"]["criteria"])}
    answers["goal_achieved"] = {"noul": 1.0}
    return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})


def search_task():
    return next(item for item in bench.LIVE_TASKS if item.kind == "search")


def search_payload(
    text="Python 3.12 was released on October 2, 2023.", url="https://docs.python.org/3/whatsnew/3.12.html"
):
    return {
        "query": "Python 3.12 release date",
        "results": [{"url": url, "text": text}],
        "decisions": 4,
        "cost": 0.00035,
        "engine": "https://duckduckgo.com/",
    }


def fixture_task():
    return bench.LiveTask(
        key="fixture_order",
        page="checkout.html",
        goal="Open the local order page.",
        verify=lambda row: row["url"].endswith("/checkout.html"),
    )


def test_a_search_task_is_scored_from_what_it_found(monkeypatch):
    monkeypatch.setattr(bench, "Session", Closer)
    monkeypatch.setattr("jev_ra.search.search", lambda *_args, **_kwargs: search_payload())
    row = bench.measure_search(search_task(), config.load(CONFIG), done_decider)
    assert (row["status"], row["ok"]) == ("done", True)
    assert row["decisions"] == 4 and row["cost"] == 0.00035
    assert row["url"] == "https://duckduckgo.com/"
    assert row["results"][0]["url"] == "https://docs.python.org/3/whatsnew/3.12.html"


def test_a_search_with_nothing_to_cite_is_not_a_pass(monkeypatch):
    monkeypatch.setattr(bench, "Session", Closer)
    monkeypatch.setattr("jev_ra.search.search", lambda *_args, **_kwargs: {**search_payload(), "results": []})
    row = bench.measure_search(search_task(), config.load(CONFIG), done_decider)
    assert (row["status"], row["ok"]) == ("blocked", False)


def test_a_run_that_does_not_verify_is_marked_with_why(monkeypatch):
    monkeypatch.setattr(bench, "Session", Closer)
    monkeypatch.setattr("jev_ra.search.search", lambda *_args, **_kwargs: search_payload("nothing here", "https://x/"))
    row = bench.measure_search(search_task(), config.load(CONFIG), done_decider)
    assert row["ok"] is False and row["reason"] == "finished but the page does not show the task done"


@pytest.mark.browser
def test_the_live_runner_serves_a_page_task_and_verifies_it(monkeypatch):
    require_browser()
    monkeypatch.setattr(bench, "DecisionClient", Client)
    measured = bench.run_live(config=config.load(CONFIG), tasks=(fixture_task(),), runs=1)
    assert [row["task"] for row in measured] == ["fixture_order"]
    assert all(row["status"] == "done" and row["ok"] for row in measured)
    assert all(row["elapsed_ms"] > 0 for row in measured)


@pytest.mark.browser
def test_the_live_runner_dispatches_a_search_task_to_the_search_measure(monkeypatch):
    require_browser()
    monkeypatch.setattr(bench, "DecisionClient", Client)
    monkeypatch.setattr("jev_ra.search.search", lambda *_args, **_kwargs: search_payload())
    measured = bench.run_live(config=config.load(CONFIG), tasks=(search_task(), fixture_task()), runs=1)
    assert [row["task"] for row in measured] == [search_task().key, "fixture_order"]
    assert all(row["ok"] for row in measured)
