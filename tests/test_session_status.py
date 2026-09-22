"""The status the site answered with is part of what the session observed."""

import pytest

pytestmark = pytest.mark.browser


def test_an_error_answer_is_reported_with_its_status(session, flaky_server):
    url = flaky_server(status=502, failures=1)
    page = session.open(url)
    assert page["http_status"] == 502
    page = session.open(url)
    assert page["http_status"] == 200


def test_an_ordinary_page_reports_its_own_status(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    assert page["http_status"] == 200


def test_a_missing_page_reports_the_status_it_was_served_with(session, fixture_server):
    page = session.open(f"{fixture_server}/does-not-exist.html")
    assert page["http_status"] == 404
