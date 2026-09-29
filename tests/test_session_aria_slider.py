"""A slider drawn from divs is moved the way its keyboard contract says, to the value it was given."""

import pytest

from jev_ra.errors import BadValue

pytestmark = pytest.mark.browser

PAGE = "/sites/price-slider.html"


def handle(page, label):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == "fill")


def shown(session):
    return session.evaluate("document.getElementById('range').textContent")


def test_each_handle_is_a_field_holding_the_value_it_announces(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    low, high = handle(page, "Minimum price"), handle(page, "Maximum price")
    assert (low["role"], low["value"], low["format"]) == ("slider", "$0", "slider")
    assert high["value"] == "$5,000"
    assert not [a for a in page["actions"] if a["label"] == "Open Maximum price"]


def test_a_handle_is_moved_to_the_value_it_was_given(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    session.act(handle(page, "Maximum price"), page, text="2000")
    page = session.observe()
    assert shown(session) == "$0 - $2,000"
    assert handle(page, "Maximum price")["value"] == "$2,000"


def test_a_value_written_the_way_the_page_shows_it_is_the_same_value(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    session.act(handle(page, "Minimum price"), page, text="$1,200")
    session.observe()
    assert shown(session) == "$1,200 - $5,000"


def test_the_ends_of_the_range_are_reached_directly(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    session.act(handle(page, "Maximum price"), page, text="0")
    session.observe()
    assert shown(session) == "$0 - $0"


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("6000", "Maximum price takes a number from 0 to 5000, and '6000' is not one."),
        ("cheap", "Maximum price takes a number from 0 to 5000, and 'cheap' is not one."),
        ("2050", "Maximum price moves in steps of 100 from 5000, and '2050' is not one of them."),
    ],
)
def test_a_value_the_handle_cannot_take_is_refused_and_the_handle_left_where_it_was(
    session, fixture_server, text, said
):
    page = session.open(fixture_server + PAGE)
    with pytest.raises(BadValue) as refused:
        session.act(handle(page, "Maximum price"), page, text=text)
    assert refused.value.message == said
    assert shown(session) == "$0 - $5,000"
