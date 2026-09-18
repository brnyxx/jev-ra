import re

import pytest

from jev_ra import config, search
from jev_ra.decide import Reply


def noul_reply(value, cost=0.0001):
    return Reply(answers={"answers_goal": {"noul": value}}, latency_ms=5, usage={"cost": cost})


def ranking_decider(order, verdicts):
    """One answer for the SERP ranking, then one answers_goal per page, keyed by url suffix."""
    seen = []

    def decide(state, questions):
        seen.append(questions)
        if "result" in questions:
            criteria = questions["result"]["criteria"]
            weights = {}
            for target, text in criteria.items():
                weights[target] = next((1.0 - n * 0.1 for n, name in enumerate(order) if name in text), 0.01)
            total = sum(weights.values())
            spread = {target: weight / total for target, weight in weights.items()}
            best = max(spread, key=spread.get)
            return Reply(
                answers={"result": {"choice": best, "confidence": 0.9, "probabilities": spread}},
                latency_ms=4,
                usage={"cost": 0.0002},
            )
        url = state["page"]["url"]
        return noul_reply(next((value for suffix, value in verdicts.items() if url.endswith(suffix)), 0.0))

    decide.seen = seen
    return decide


def test_the_engine_url_is_duckduckgo_by_default_and_configurable():
    assert search.engine_url("godel proof", env={}) == "https://html.duckduckgo.com/html/?q=godel+proof"
    assert search.engine_url("a b", engine="https://x/s?q={query}") == "https://x/s?q=a+b"
    assert search.engine_url("a b", env={"JEV_RA_SEARCH_URL": "https://y/?s={query}"}) == "https://y/?s=a+b"


def test_blocked_resources_cover_images_fonts_and_media():
    assert "*.png" in search.BLOCKED_URLS
    assert "*.woff2" in search.BLOCKED_URLS
    assert "*.mp4" in search.BLOCKED_URLS
    assert not any(pattern.endswith((".html", ".js", ".css")) for pattern in search.BLOCKED_URLS)


class RecordingSession:
    def __init__(self, calls):
        self.calls = calls
        self.closed = False
        self.max_elements = 250

    def call(self, method, **params):
        self.calls.append((method, params))

    def open(self, url):
        return {"url": url, "title": "", "text": "", "elements": [], "actions": [], "omitted": 0}

    def observe(self, timer=None):
        return self.open("about:blank")

    def evaluate(self, _expression):
        return None

    def close(self):
        self.closed = True


def test_the_blocked_url_list_is_applied_to_every_tab():
    calls = []
    session = RecordingSession(calls)
    applied = search.block_resources(session)
    assert [method for method, _ in calls] == ["Network.enable", "Network.setBlockedURLs"]
    assert calls[1][1]["urls"] == applied == list(search.BLOCKED_URLS)


def test_a_serp_without_links_returns_nothing_and_asks_nothing():
    calls = []
    session = RecordingSession(calls)

    def decide(_state, _questions):
        raise AssertionError("nothing to rank")

    payload = search.search("x", config=config.load({}), decide=decide, session=session, session_factory=None)
    assert payload["results"] == []
    assert payload["decisions"] == 0
    assert session.closed is False


@pytest.mark.browser
def test_search_ranks_and_reads_the_best_pages(session, fixture_server, monkeypatch):
    decide = ranking_decider(
        order=["reading list", "Booking form", "Where to?"],
        verdicts={"/list.html": 0.92, "/form.html": 0.1, "/autocomplete.html": 0.05},
    )
    opened = []

    def factory():
        from jev_ra.browser.session import Session

        made = Session(config.load({}))
        opened.append(made)
        return made

    payload = search.search(
        "godel incompleteness",
        "Find a page explaining the incompleteness theorems.",
        max_pages=2,
        config=config.load({}),
        decide=decide,
        session=session,
        session_factory=factory,
        engine=f"{fixture_server}/serp.html?q=" + "{query}",
    )
    assert [item["rank"] for item in payload["results"]] == [1, 2]
    assert payload["results"][0]["url"].endswith("/list.html")
    assert payload["results"][0]["answers_goal"] == 0.92
    assert "consistent formal system" in payload["results"][0]["text"]
    assert payload["decisions"] == 3
    assert payload["cost"] > 0
    assert payload["elapsed_ms"] > 0
    # Every reading tab is opened and closed again.
    assert len(opened) == 2
    assert all(tab.target_id is None for tab in opened)


@pytest.mark.browser
def test_search_reads_pages_in_separate_tabs_with_resources_blocked(session, fixture_server):
    decide = ranking_decider(order=["reading list"], verdicts={"/list.html": 0.9})
    payload = search.search(
        "godel",
        max_pages=1,
        config=config.load({}),
        decide=decide,
        session=session,
        engine=f"{fixture_server}/serp.html?q=" + "{query}",
    )
    assert payload["results"][0]["blocked"] == list(search.BLOCKED_URLS)
    assert session.observe()["url"].startswith(fixture_server)


SERP_PAGE = {
    "url": "https://engine.test/serp?q=godel",
    "title": "godel at the engine",
    "text": "results",
    "elements": [
        {"ref": "e1", "node": 1, "role": "link", "label": "First result", "value": ""},
        {"ref": "e2", "node": 2, "role": "link", "label": "Second result", "value": ""},
    ],
    "actions": [
        {"id": "e1", "node": 1, "role": "link", "kind": "click", "label": "First result"},
        {"id": "e2", "node": 2, "role": "link", "kind": "click", "label": "Second result"},
    ],
    "marker": "serp",
    "page_key": [],
    "guards": {},
    "omitted": 0,
}

CONTENT_PAGE = {
    "url": "",
    "title": "A page",
    "text": "",
    "elements": [],
    "actions": [],
    "marker": "page",
    "page_key": [],
    "guards": {},
    "omitted": 0,
}


class FakeTab:
    """A session that answers from dicts: no CDP, no network, no browser."""

    def __init__(self, page=None, hrefs=None, fail_on_open=False):
        self.max_elements = 250
        self.page = page or CONTENT_PAGE
        self.hrefs = hrefs or {}
        self.fail_on_open = fail_on_open
        self.calls = []
        self.closed = False

    def call(self, method, **params):
        self.calls.append((method, params))

    def open(self, url):
        if self.fail_on_open:
            raise RuntimeError("this tab will not open")
        return {**self.page, "url": url}

    def observe(self, timer=None):
        return self.open(self.page.get("url", ""))

    def evaluate(self, expression):
        match = re.search(r"nodes\.get\((\d+)\)", expression)
        if match:
            return self.hrefs.get(int(match.group(1)))
        return {"text": "page body"}

    def close(self):
        self.closed = True


def greedy_decide(_state, questions):
    if "result" in questions:
        return Reply(
            answers={"result": {"choice": "e1", "confidence": 0.9, "probabilities": {"e1": 0.8, "e2": 0.2}}},
            latency_ms=3,
            usage={"cost": 0.0002},
        )
    return Reply(answers={"answers_goal": {"noul": 0.9}}, latency_ms=1, usage={"cost": 0.0001})


def test_search_ranks_and_reads_the_picked_pages_without_a_browser():
    engine = FakeTab(page=SERP_PAGE, hrefs={1: "https://one.test/", 2: "https://two.test/"})
    tabs = []

    def factory():
        tab = FakeTab(page=CONTENT_PAGE)
        tabs.append(tab)
        return tab

    payload = search.search(
        "godel",
        "explain the incompleteness theorems",
        max_pages=2,
        config=config.load({}),
        decide=greedy_decide,
        session=engine,
        session_factory=factory,
        engine="https://engine.test/serp?q={query}",
    )
    assert [item["rank"] for item in payload["results"]] == [1, 2]
    assert [item["url"] for item in payload["results"]] == ["https://one.test/", "https://two.test/"]
    assert payload["results"][0]["answers_goal"] == 0.9
    assert payload["decisions"] == 3
    assert payload["cost"] == pytest.approx(0.0004)
    assert payload["blocked"] == list(search.BLOCKED_URLS)
    assert engine.closed is False
    assert len(tabs) == 2 and all(tab.closed for tab in tabs)
    assert [method for method, _ in engine.calls] == ["Network.enable", "Network.setBlockedURLs"]


def test_a_tab_that_will_not_open_is_recorded_as_an_error():
    engine = FakeTab(page=SERP_PAGE, hrefs={1: "https://one.test/", 2: "https://two.test/"})
    tabs = []

    def factory():
        tab = FakeTab(page=CONTENT_PAGE, fail_on_open=not tabs)
        tabs.append(tab)
        return tab

    payload = search.search(
        "godel",
        max_pages=2,
        config=config.load({}),
        decide=greedy_decide,
        session=engine,
        session_factory=factory,
        engine="https://engine.test/serp?q={query}",
    )
    failed = [item for item in payload["results"] if item.get("error")]
    assert len(failed) == 1
    assert "will not open" in failed[0]["error"]
    assert payload["results"][0]["url"] == "https://two.test/"
    assert payload["results"][0]["answers_goal"] == 0.9


def test_search_owns_and_closes_the_session_and_skips_links_without_an_href(monkeypatch):
    engine = FakeTab(page=SERP_PAGE, hrefs={1: None, 2: "https://two.test/"})
    monkeypatch.setattr(search, "Session", lambda _config: engine)
    payload = search.search(
        "godel",
        max_pages=2,
        config=config.load({}),
        decide=greedy_decide,
        engine="https://engine.test/serp?q={query}",
    )
    assert [item["url"] for item in payload["results"]] == ["https://two.test/"]
    assert payload["decisions"] == 2
    assert engine.closed is True
