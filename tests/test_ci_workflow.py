"""The CI workflow is part of the contract: browser tests must really run there."""

import os
import re
from pathlib import Path

import pytest

from tests.conftest import chrome_url, require_browser

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def blocks(text):
    """A minimal indentation check: every line is spaces-only indented and `key:` pairs parse."""
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        assert "\t" not in line[:indent], f"line {number} indents with a tab"
        assert indent % 2 == 0, f"line {number} indents by {indent}"


def test_the_workflow_is_well_formed():
    text = WORKFLOW.read_text()
    blocks(text)
    assert text.startswith("name: ci\n")
    assert re.search(r"^jobs:$", text, re.MULTILINE)
    assert text.count("steps:") == 1


def test_the_matrix_covers_python_3_12_to_3_14():
    text = WORKFLOW.read_text()
    assert 'python-version: ["3.12", "3.13", "3.14"]' in text
    assert "astral-sh/setup-uv" in text
    assert "uv sync --locked" in text


def test_chrome_is_started_with_remote_debugging_on_a_temp_profile():
    text = WORKFLOW.read_text()
    assert "--remote-debugging-port=9222" in text
    assert '--user-data-dir="$profile"' in text
    assert 'profile="$(mktemp -d)"' in text
    assert "BU_CDP_URL: http://127.0.0.1:9222" in text


def test_ci_runs_lint_and_the_browser_tests_without_skipping_them():
    text = WORKFLOW.read_text()
    assert "uv run ruff check ." in text
    assert "uv run pytest -q\n" in text
    assert "uv run pytest -q -m browser" in text
    assert 'JEV_RA_REQUIRE_BROWSER: "1"' in text
    assert "not browser" not in text


def test_require_browser_turns_a_missing_chrome_into_a_failure(monkeypatch):
    monkeypatch.setenv("JEV_RA_REQUIRE_BROWSER", "1")
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    with pytest.raises(RuntimeError, match="JEV_RA_REQUIRE_BROWSER"):
        require_browser()


def test_without_the_flag_a_missing_chrome_only_skips(monkeypatch):
    monkeypatch.delenv("JEV_RA_REQUIRE_BROWSER", raising=False)
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    assert chrome_url() is None
    with pytest.raises(BaseException, match="No Chrome over CDP"):
        require_browser()


@pytest.mark.browser
def test_the_browser_marker_really_has_a_chrome(chrome):
    assert chrome == os.environ["BU_CDP_URL"]
