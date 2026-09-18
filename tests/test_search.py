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

    def observe(self):
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
