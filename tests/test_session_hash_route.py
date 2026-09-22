"""An address that only changes after the # is a navigation, and its view is waited for."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/hash-router.html"


def test_the_view_a_fragment_names_is_on_the_page_when_open_returns(session, fixture_server):
    session.open(f"{fixture_server}{FIXTURE}#overview")
    page = session.open(f"{fixture_server}{FIXTURE}#install")
    assert page["url"].endswith("#install")
    assert "Run the installer" in page["text"]
    assert "What this library is for" not in page["text"]


def test_the_route_is_waited_for_however_many_times_the_fragment_changes(session, fixture_server):
    session.open(f"{fixture_server}{FIXTURE}#install")
    session.open(f"{fixture_server}{FIXTURE}#overview")
    page = session.open(f"{fixture_server}{FIXTURE}#install")
    assert "Run the installer" in page["text"]
    assert "What this library is for" not in page["text"]


def test_asking_for_the_fragment_already_open_leaves_the_view_where_it_is(session, fixture_server):
    session.open(f"{fixture_server}{FIXTURE}#overview")
    session.open(f"{fixture_server}{FIXTURE}#install")
    page = session.open(f"{fixture_server}{FIXTURE}#install")
    assert page["url"].endswith("#install")
    assert "Run the installer" in page["text"]


def test_an_address_without_a_fragment_still_loads_its_own_document(session, fixture_server):
    session.open(f"{fixture_server}{FIXTURE}#install")
    page = session.open(f"{fixture_server}/sites/form.html")
    assert page["url"].endswith("/form.html")
