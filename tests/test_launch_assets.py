"""The launch surface: every asset the README and the landing page name actually exists."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "docs" / "index.html"
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
READMES = ("README.md", "docs/i18n/README.ko.md")


def local_references(text):
    """Every repository-relative path a markdown or HTML file points at."""
    found = re.findall(r"\]\(([^)]+)\)", text) + re.findall(r'src="([^"]+)"', text)
    return [
        item.split("#")[0]
        for item in found
        if not item.startswith(("http://", "https://", "#", "mailto:", "data:"))
    ]


@pytest.mark.parametrize("name", READMES)
def test_every_readme_link_resolves_inside_the_repository(name):
    path = ROOT / name
    for reference in local_references(path.read_text()):
        assert (path.parent / reference).exists(), f"{name} points at {reference}, which is not in the repo"


@pytest.mark.parametrize("name", READMES)
def test_the_readmes_use_the_brand_assets(name):
    text = (ROOT / name).read_text()
    for asset in ("logo.svg", "hero.png", "demo/flights-side-by-side.gif"):
        assert f"assets/{asset}" in text
    assert "shields.io" in text


@pytest.mark.parametrize("name", READMES)
def test_the_readmes_carry_the_same_measured_numbers(name):
    text = (ROOT / name).read_text()
    for number in ("2,714", "8,888", "3,806", "23,058", "66,414", "15,071"):
        assert number in text, f"{name} is missing {number}"


def test_the_landing_page_assets_exist():
    for reference in local_references(LANDING.read_text()):
        if reference in {"./"}:
            continue
        assert (ROOT / reference).exists(), f"docs/index.html points at {reference}"


def test_the_pages_workflow_assembles_the_landing_page_with_its_assets():
    text = PAGES.read_text()
    assert text.startswith("name: pages\n")
    # The page says `assets/...`, and assets live at the repo root, so the site has to carry a copy.
    assert "cp docs/index.html site/index.html" in text
    assert "cp -R assets site/assets" in text
    assert "actions/deploy-pages@v4" in text
    assert "pages: write" in text
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip(" "))
        assert "\t" not in line, "the workflow must not indent with tabs"
        assert indent % 2 == 0, f"odd indent on: {line!r}"


def test_the_demo_renders_are_small_enough_to_ship():
    for name in ("wikipedia.gif", "flights.gif", "oliveyoung_sort.gif", "flights-side-by-side.gif"):
        path = ROOT / "assets" / "demo" / name
        assert path.exists(), f"{name} has not been rendered"
        assert path.stat().st_size < 1_000_000, f"{name} is {path.stat().st_size} bytes"
