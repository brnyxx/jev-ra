"""A hash change is not rendered route content merely because its links changed."""

from jev_ra.browser.session import routed


def test_changed_action_links_do_not_count_as_a_rendered_route():
    before = [1, "https://example.test/#overview", 0, 0, 1280, 900, "Docs", "Overview", ["view"], ["old"], []]
    after = [1, "https://example.test/#install", 0, 0, 1280, 900, "Docs", "Overview", ["view"], ["new"], []]

    assert not routed(after, before)
    assert routed([*after[:7], "Installation", *after[8:]], before)
