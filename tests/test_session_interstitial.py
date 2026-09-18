"""A document that is replaced while it is being read is not an error the caller should see."""

import pytest

pytestmark = pytest.mark.browser


def test_open_follows_an_interstitial_to_the_page_it_lands_on(session, fixture_server):
    page = session.open(fixture_server + "/sites/interstitial.html")
    assert page["url"].endswith("/form.html")
    assert any(element["label"] == "Search flights" for element in page["elements"])


def test_observe_survives_the_document_changing_under_it(session, fixture_server):
    session.open(fixture_server + "/sites/interstitial.html")
    page = session.observe()
    assert page["url"].endswith("/form.html")
