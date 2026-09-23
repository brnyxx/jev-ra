"""A box the page lets you type into is a field however its contenteditable attribute is written."""

import pytest

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("attribute", ["contenteditable", 'contenteditable=""', 'contenteditable="plaintext-only"'])
def test_every_spelling_of_contenteditable_is_a_field_to_type_into(session, fixture_server, attribute):
    session.open(f"{fixture_server}/sites/static.html")
    session.evaluate(
        f"document.body.insertAdjacentHTML('beforeend', '<div {attribute} aria-label=\"Notes\" "
        'style="min-height:40px;border:1px solid"></div>\')'
    )
    page = session.observe()
    field = next(a for a in page["actions"] if a["label"] == "Notes" and a["kind"] == "fill")
    assert field["role"] == "textbox"
    session.act(field, page, text="Call Grace on Friday")
    assert next(e for e in session.observe()["elements"] if e["label"] == "Notes")["value"] == "Call Grace on Friday"
