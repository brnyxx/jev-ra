"""A single-page app changes the address first and renders after; the reading has to wait."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/route-change.html"


def test_a_route_change_is_read_after_the_new_route_renders(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    go = next(action for action in page["actions"] if action["label"] == "Reference")
    session.act(go, page)
    page = session.observe()
    assert "p=reference" in page["url"]
    assert "useEffect" in page["text"]
    assert "The library for web and native" not in page["text"]
