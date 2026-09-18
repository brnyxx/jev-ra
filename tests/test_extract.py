import pytest

from jev_ra.extract import extract

pytestmark = pytest.mark.browser


def test_text_mode_keeps_headings_as_markdown(session, fixture_server):
    session.open(f"{fixture_server}/list.html")
    result = extract(session, "text")
    assert result["mode"] == "text"
    assert result["title"] == "Reading list"
    assert result["url"].endswith("/list.html")
    assert "# Reading list" in result["text"]
    assert "## On incompleteness" in result["text"]
    assert "consistent formal system" in result["text"]
    assert "This paragraph is hidden." not in result["text"]
    assert result["truncated"] is False


def test_links_mode_returns_text_and_resolved_hrefs(session, fixture_server):
    session.open(f"{fixture_server}/list.html")
    links = extract(session, "links")["links"]
    assert [link["text"] for link in links] == ["Booking form", "Autocomplete", "External reference"]
    assert links[0]["href"] == f"{fixture_server}/form.html"
    assert links[2]["href"] == "https://example.com/external"


def test_tables_mode_returns_rows_of_cells(session, fixture_server):
    session.open(f"{fixture_server}/list.html")
    tables = extract(session, "tables")["tables"]
    assert len(tables) == 1
    assert tables[0]["rows"][0] == ["Title", "Year", "Pages"]
    assert tables[0]["rows"][1] == ["First edition", "1931", "26"]
    assert len(tables[0]["rows"]) == 3


def test_main_mode_narrows_to_the_article(session, fixture_server):
    session.open(f"{fixture_server}/list.html")
    text = extract(session, "main")["text"]
    assert "On incompleteness" in text
    assert "consistent formal system" in text
    assert "External reference" not in text


def test_elements_mode_lists_the_observed_controls(session, fixture_server):
    session.open(f"{fixture_server}/form.html")
    result = extract(session, "elements")
    labels = [element["label"] for element in result["elements"]]
    assert "Search flights" in labels
    assert result["omitted"] == 0
    assert all("rect" not in element for element in result["elements"])


def test_an_unknown_mode_is_refused(session, fixture_server):
    session.open(f"{fixture_server}/list.html")
    with pytest.raises(ValueError, match="mode must be one of"):
        extract(session, "summary")


def test_output_is_capped_and_reports_truncation(session, fixture_server):
    session.open(f"{fixture_server}/list.html")
    result = extract(session, "text", max_chars=200)
    assert result["truncated"] is True
    assert len(result["text"]) < 200
    links = extract(session, "links", max_chars=180)
    assert links["truncated"] is True
    assert len(links["links"]) < 3
