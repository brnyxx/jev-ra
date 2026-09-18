"""A field that will not take the pointer's focus is focused, not clicked at again."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/focus-refusing-field.html"


def action_for(page, label, kind):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def test_typing_into_it_clicks_once_and_leaves_the_panel_open(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Search the archive", "fill"), page, text="transformer")
    assert session.evaluate("document.getElementById('clicks').textContent") == "1"
    assert session.evaluate("document.getElementById('panel').hidden") is False
    assert session.evaluate("document.getElementById('q').value") == "transformer"
