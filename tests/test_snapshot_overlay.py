"""What is covered cannot be acted on, so it must not be offered as though it could."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/consent-overlay.html"


def labels(page):
    return {element["label"] for element in page["elements"]}


def action_for(page, label, kind):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def test_a_consent_wall_hides_the_form_underneath_it(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert "Accept all" in labels(page)
    assert "Reject all" in labels(page)
    assert "From" not in labels(page)
    assert "Find cheap tickets" not in labels(page)


def test_dismissing_the_wall_brings_the_form_back(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Accept all", "click"), page)
    page = session.observe()
    assert "From" in labels(page)
    session.act(action_for(page, "From", "fill"), page, text="London")
    assert session.evaluate("document.getElementById('origin').value") == "London"


def test_everything_offered_can_actually_be_acted_on(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    for action in page["actions"]:
        if action["kind"] in {"click", "fill"}:
            assert session.fresh(page, action), f"{action['label']} is offered but not reachable"


def test_a_checkbox_painted_over_by_its_own_label_is_still_offered(session, fixture_server):
    page = session.open(fixture_server + "/sites/styled-filter.html")
    assert "닥터자르트" in labels(page)
    session.act(action_for(page, "닥터자르트", "click"), page)
    assert session.evaluate("document.getElementById('b1').checked") is True
    assert "filtered: dr-jart" in session.observe()["text"]
