"""Where a link goes decides when it is offered: the site first, the rest of the web last."""

import pytest

from jev_ra.browser import actions

pytestmark = pytest.mark.browser

FIXTURE = "/sites/off-site-links.html"


def clicks(page, goal=""):
    space = actions.build(page, goal=goal)
    labels = {element["ref"]: element["label"] for element in space.elements}
    return [labels[target] for target in space.targets["CLICK"]]


def test_a_link_that_leaves_the_site_is_offered_after_every_link_that_does_not(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert clicks(page) == ["Documentation", "Contact us", "Learn more", "Reserved names"]


def test_a_host_the_goal_names_counts_as_the_site_it_is_on(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert clicks(page, "Read what iana.org says about reserved example domains.") == [
        "Learn more",
        "Documentation",
        "Contact us",
        "Reserved names",
    ]


def test_ordering_offers_the_same_links_either_way(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert sorted(clicks(page)) == sorted(clicks(page, "Open iana.org."))


def test_a_relative_link_is_never_somewhere_else(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    hosts = {element["label"]: element.get("host") for element in page["elements"]}
    assert hosts["Documentation"] is None
    assert hosts["Learn more"] == "www.iana.org"
