"""A field the browser draws itself - a date, a time, a colour, a slider - is given its value."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.bench.scripted import scripted
from jev_ra.errors import BadValue

pytestmark = pytest.mark.browser


def field(page, label):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == "fill")


def text_of(session, element_id):
    return session.evaluate(f"document.getElementById('{element_id}').textContent")


def test_a_date_a_time_and_a_number_are_fields_the_run_can_fill(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/native-inputs.html")
    assert [(field(page, label)["role"], field(page, label).get("format")) for label in ("Date", "Time", "Guests")] == [
        ("textbox", "date"),
        ("textbox", "time"),
        ("spinbutton", None),
    ]
    assert not [a for a in page["actions"] if a["label"] in ("Open Date", "Open Time")]


def test_a_slider_and_a_colour_take_their_values_and_the_page_hears_them(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/settings-sliders.html")
    assert field(page, "Text size")["role"] == "slider"
    session.act(field(page, "Text size"), page, text="18")
    page = session.observe()
    session.act(field(page, "Accent colour"), page, text="#FF6600")
    session.observe()
    assert text_of(session, "preview") == "Saved: text 18 px, accent #ff6600"


def test_a_framework_that_tracks_its_input_hears_the_date(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/controlled-date.html")
    session.act(field(page, "Check-in date"), page, text="2026-10-05")
    session.observe()
    assert text_of(session, "state") == "Checking in on 2026-10-05."


def test_a_date_the_field_cannot_read_is_refused_with_the_form_it_takes(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/native-inputs.html")
    with pytest.raises(BadValue, match="a date as yyyy-mm-dd"):
        session.act(field(page, "Date"), page, text="October 5, 2026")
    assert session.evaluate("document.getElementById('date').value") == ""


def test_a_slider_refuses_a_value_off_its_scale_and_says_what_its_scale_is(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/settings-sliders.html")
    with pytest.raises(BadValue, match="a number from 12 to 24 in steps of 1"):
        session.act(field(page, "Text size"), page, text="40")


def test_a_run_handed_a_date_it_cannot_use_asks_for_it_again(session, fixture_server):
    decide = scripted([("TYPE_TEXT", "Date", "date")])
    agent = Agent(session=session, config=config.load({}), decide=decide, prefetch=False)
    result = agent.run(
        "Find a table on October 5.",
        values={"date": "October 5, 2026"},
        url=f"{fixture_server}/sites/native-inputs.html",
    )
    assert (result.status, result.reason) == ("escalate", "needs_value")
    assert result.detail["field"]["label"] == "Date"
    assert "yyyy-mm-dd" in result.detail["reason"]


def test_a_refused_value_leaves_the_field_as_it_was(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/settings-sliders.html")
    with pytest.raises(BadValue, match="a colour as #rrggbb"):
        session.act(field(page, "Accent colour"), page, text="18")
    assert session.evaluate("document.getElementById('accent').value") == "#1a56db"
    assert text_of(session, "preview") == "Saved: text 14 px, accent #1a56db"
