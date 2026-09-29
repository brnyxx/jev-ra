"""A JavaScript dialog is the page in front of the page: observed, answered, never waited out."""

import time

import pytest

from jev_ra.browser import actions
from jev_ra.browser import session as session_module
from jev_ra.errors import DialogOpen

pytestmark = pytest.mark.browser


def action_for(page, label, kind="click"):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def labels(page):
    return [element["label"] for element in page["elements"]]


def test_a_click_that_opens_a_confirm_comes_back_with_the_dialog_as_the_page(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/confirm-delete.html")
    started = time.monotonic()
    session.act(action_for(page, "Delete Work address"), page)
    page = session.observe()
    assert time.monotonic() - started < session_module.CALL_TIMEOUT_S
    assert page["dialog"] == "confirm"
    assert page["text"].endswith("says\nDelete the Work address? This cannot be undone.")
    assert labels(page) == ["OK", "Cancel"]
    assert page["title"] == "Saved addresses"


def test_ok_answers_the_confirm_and_the_page_goes_on(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/confirm-delete.html")
    session.act(action_for(page, "Delete Work address"), page)
    page = session.observe()
    session.act(action_for(page, "OK"), page)
    page = session.observe()
    assert "dialog" not in page
    assert "Work address deleted" in page["text"]
    assert "Delete Work address" not in labels(page)


def test_cancel_answers_the_confirm_and_nothing_is_deleted(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/confirm-delete.html")
    session.act(action_for(page, "Delete Work address"), page)
    page = session.observe()
    session.act(action_for(page, "Cancel"), page)
    page = session.observe()
    assert "Delete Work address" in labels(page)


def test_what_is_typed_into_a_prompt_is_its_answer(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/prompt-folder.html")
    session.act(action_for(page, "New folder"), page)
    page = session.observe()
    field = action_for(page, "Name the new folder", "fill")
    assert field["value"] == "Untitled folder"
    session.act(field, page, text="Invoices")
    page = session.observe()
    assert action_for(page, "Name the new folder", "fill")["value"] == "Invoices"
    session.act(action_for(page, "OK"), page)
    assert "📁 Invoices" in session.observe()["text"]


def test_an_alert_raised_while_the_page_parses_is_the_first_thing_observed(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/alert-on-load.html")
    assert page["dialog"] == "alert"
    assert "Online filing is closed on Sundays." in page["text"]
    session.act(action_for(page, "OK"), page)
    assert "Download forms" in labels(session.observe())


def test_the_page_under_a_dialog_is_not_touched_until_the_dialog_is_answered(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/confirm-delete.html")
    delete = action_for(page, "Delete Home address")
    session.act(action_for(page, "Delete Work address"), page)
    with pytest.raises(DialogOpen):
        session.act(delete, page)
    assert session.observe()["dialog"] == "confirm"


def test_an_answer_is_refused_once_its_dialog_is_gone(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/confirm-delete.html")
    session.act(action_for(page, "Delete Work address"), page)
    dialog = session.observe()
    session.act(action_for(dialog, "Cancel"), dialog)
    assert session.fresh(dialog, action_for(dialog, "OK")) is False


def test_leaving_a_page_with_an_unsaved_draft_asks_first(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/unsaved-draft.html")
    session.act(action_for(page, "Post body", "fill"), page, text="Half a thought")
    page = session.observe()
    session.act(action_for(page, "All posts"), page)
    page = session.observe()
    assert page["dialog"] == "beforeunload"
    assert labels(page) == ["Leave", "Cancel"]
    session.act(action_for(page, "Cancel"), page)
    page = session.observe()
    assert page["url"].endswith("/sites/unsaved-draft.html")
    assert action_for(page, "Post body", "fill")["value"] == "Half a thought"


def test_opening_another_address_leaves_a_page_that_asks_to_be_kept(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/unsaved-draft.html")
    session.act(action_for(page, "Post body", "fill"), page, text="Half a thought")
    session.observe()
    page = session.open(f"{fixture_server}/sites/static.html")
    assert page["url"].endswith("/sites/static.html")
    assert "dialog" not in page


def test_a_dialog_offers_only_its_answers(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/prompt-folder.html")
    session.act(action_for(page, "New folder"), page)
    space = actions.build(session.observe())
    assert sorted(space.offered()) == ["CLICK", "TYPE_TEXT"]
