"""A link a client router answers late is read at the address it pushes, not at the click."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/late-route-menu.html"


def follow(session, url, label):
    page = session.open(url)
    action = next(a for a in page["actions"] if a["label"] == label and a["role"] == "link")
    session.act(action, page)
    return session.observe()


def test_a_link_routed_a_moment_after_the_click_is_read_at_its_address(session, fixture_server):
    page = follow(session, f"{fixture_server}{FIXTURE}?delay=500", "Society")
    assert "genre=society" in page["url"]
    assert "Society headlines." in page["text"]
