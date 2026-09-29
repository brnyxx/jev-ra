"""A control that asks for a file is offered, and pressing it hands the question back instead of a dialog."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.bench.scripted import scripted

pytestmark = pytest.mark.browser

PAGE = "/sites/file-upload.html"


def control(page, label, kind="click"):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def chosen(session):
    return session.evaluate("document.getElementById('resume').files.length")


def test_a_file_input_drawn_as_a_button_is_offered_as_the_button(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    assert control(page, "Attach resume/CV")["role"] == "button"


def test_pressing_it_says_what_the_page_asked_for_and_leaves_no_dialog_open(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    session.act(control(page, "Attach resume/CV"), page)
    page = session.observe()
    assert page["file_chooser"] == {"multiple": False, "accept": ".pdf,.doc,.docx,.txt"}
    assert chosen(session) == 0
    session.act(control(page, "Full name", "fill"), page, text="Ada Lovelace")
    assert "file_chooser" not in session.observe()


def test_a_button_that_opens_the_chooser_from_script_is_heard_too(session, fixture_server):
    session.open(fixture_server + PAGE)
    session.evaluate(
        "document.body.insertAdjacentHTML('beforeend', '<button id=up>Upload</button>');"
        "document.getElementById('up').onclick = () => document.getElementById('cover').click()"
    )
    page = session.observe()
    session.act(control(page, "Upload"), page)
    assert session.observe()["file_chooser"] == {"multiple": False, "accept": ".pdf,.txt"}


def test_a_file_input_with_no_name_is_offered_as_what_the_browser_draws(session, fixture_server):
    session.open(fixture_server + PAGE)
    session.evaluate("document.body.insertAdjacentHTML('beforeend', '<input type=file multiple>')")
    page = session.observe()
    session.act(control(page, "Choose file"), page)
    assert session.observe()["file_chooser"] == {"multiple": True}


def test_a_run_that_reaches_the_file_hands_it_back_naming_the_field(session, fixture_server):
    plan = [("TYPE_TEXT", "Full name", "name"), ("CLICK", "Attach resume/CV", None)]
    agent = Agent(session=session, config=config.load({}), decide=scripted(plan), prefetch=False)
    result = agent.run(
        "Apply as Ada Lovelace with her resume attached.",
        values={"name": "Ada Lovelace"},
        url=fixture_server + PAGE,
    )
    assert (result.status, result.reason) == ("escalate", "needs_file")
    assert {key: result.detail[key] for key in ("field", "multiple", "accept")} == {
        "field": "Attach resume/CV",
        "multiple": False,
        "accept": ".pdf,.doc,.docx,.txt",
    }
    assert chosen(session) == 0
