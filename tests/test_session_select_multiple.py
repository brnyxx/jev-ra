"""A list that keeps every option chosen offers each option to add or to remove, and keeps the rest."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent

pytestmark = pytest.mark.browser

PAGE = "/sites/select-multiple.html"


def option(page, label):
    return next(a for a in page["actions"] if a["kind"] == "select" and a["label"] == label)


def chosen(session):
    return session.evaluate("[...document.getElementById('toppings').selectedOptions].map(o => o.value).join()")


def test_each_option_is_offered_as_what_choosing_it_would_do(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    labels = [a["label"] for a in page["actions"] if a["kind"] == "select" and a["label"].startswith("Toppings")]
    assert labels[:3] == ["Toppings → remove Extra cheese", "Toppings → add Mushrooms", "Toppings → add Onions"]
    assert option(page, "Size → Large")["option"] == "Large"
    assert [e["role"] for e in page["elements"] if e["label"] in ("Size", "Toppings")] == ["combobox", "listbox"]


def test_an_option_added_joins_the_ones_already_chosen(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    session.act(option(page, "Toppings → add Mushrooms"), page)
    page = session.observe()
    session.act(option(page, "Toppings → add Olives"), page)
    page = session.observe()
    assert chosen(session) == "cheese,mushrooms,olives"
    assert "Toppings: Extra cheese, Mushrooms, Olives" in page["text"]


def test_an_option_removed_leaves_the_others_chosen(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    session.act(option(page, "Toppings → add Onions"), page)
    page = session.observe()
    session.act(option(page, "Toppings → remove Extra cheese"), page)
    session.observe()
    assert chosen(session) == "onions"


def never(_state, _questions):
    raise AssertionError("a direct select never asks the model")


def test_a_direct_select_names_the_option_by_its_text(session, fixture_server):
    session.open(fixture_server + PAGE)
    agent = Agent(session=session, config=config.load({}), decide=never)
    ref = next(e["ref"] for e in session.observe()["elements"] if e["label"] == "Toppings")
    agent.select(ref, "Green peppers")
    assert chosen(session) == "cheese,peppers"
