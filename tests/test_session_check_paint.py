"""A page showing a check has painted everything it will show until a person answers it."""

import time

import pytest

from jev_ra.browser import session as session_module

pytestmark = pytest.mark.browser

CHECKS = ("cloudflare-challenge.html", "perimeterx-wall.html", "akamai-challenge.html", "turnstile-wall.html")


@pytest.mark.parametrize("name", CHECKS)
def test_opening_a_check_does_not_wait_out_the_paint_budget(session, fixture_server, name):
    started = time.monotonic()
    page = session.open(f"{fixture_server}/sites/{name}")
    elapsed = time.monotonic() - started
    assert page["challenge"]
    assert elapsed < session_module.PAINT_BUDGET_S, f"waited {elapsed:.2f}s for controls a check never shows"


def test_a_page_with_nothing_to_act_on_is_still_given_its_paint_budget(session, fixture_server):
    started = time.monotonic()
    session.open(f"{fixture_server}/sites/empty.html")
    assert time.monotonic() - started >= session_module.PAINT_BUDGET_S
