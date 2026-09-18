"""GitHub's community standards checklist, as a test."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md",
    "LICENSE",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SUPPORT.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
)


@pytest.mark.parametrize("name", REQUIRED)
def test_the_file_exists(name):
    path = ROOT / name
    assert path.exists(), f"{name} is missing"
    assert path.stat().st_size > 0, f"{name} is empty"


@pytest.mark.parametrize("name", [item for item in REQUIRED if item.endswith(".md")])
def test_every_local_link_resolves(name):
    text = (ROOT / name).read_text()
    for reference in re.findall(r"\]\(([^)]+)\)", text):
        if reference.startswith(("http://", "https://", "#", "mailto:")):
            continue
        assert (ROOT / reference.split("#")[0]).exists(), f"{name} points at {reference}"


def test_the_code_of_conduct_is_the_contributor_covenant_with_a_real_contact():
    text = (ROOT / "CODE_OF_CONDUCT.md").read_text()
    assert "Contributor Covenant" in text
    assert "version 2.1" in text
    assert "github.com/brnyxx" in text
    assert "[INSERT CONTACT METHOD]" not in text


def test_security_states_the_scope_and_the_response_target():
    text = (ROOT / "SECURITY.md").read_text()
    assert "security/advisories/new" in text
    assert "7 days" in text
    for scope in ("MCP server", "CLI", "Chrome launcher"):
        assert scope in text


def test_support_separates_discussions_from_issues():
    text = (ROOT / "SUPPORT.md").read_text()
    assert "/discussions" in text
    assert "bug.yml" in text
    assert "jev-ra doctor" in text


def test_contributing_covers_setup_browser_tests_fixtures_and_commits():
    text = (ROOT / "CONTRIBUTING.md").read_text()
    for needed in ("uv sync", "BU_CDP_URL", "uv run ty check", "--runs 5", "Fixtures", "No trailers"):
        assert needed in text, f"CONTRIBUTING.md does not mention {needed}"


def test_the_pull_request_template_lists_the_gates():
    text = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text()
    for gate in ("ruff check", "ty check", "pytest -q", "gen_usage.py", "bench --live"):
        assert gate in text


def test_the_bug_template_asks_for_what_a_maintainer_needs_first():
    text = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug.yml").read_text()
    for field in ("jev-ra doctor", "Site", "Version and OS", "How are you driving it", "stuck_loop"):
        assert field in text


def test_blank_issues_are_off_and_discussions_are_linked():
    text = (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text()
    assert "blank_issues_enabled: false" in text
    assert "/discussions" in text


def test_dependabot_watches_python_actions_and_npm():
    text = (ROOT / ".github" / "dependabot.yml").read_text()
    assert "package-ecosystem: pip" in text
    assert "package-ecosystem: github-actions" in text
    assert "package-ecosystem: npm" in text
    assert text.count("interval: weekly") == 3


def test_codeowners_names_the_maintainer():
    assert "* @brnyxx" in (ROOT / ".github" / "CODEOWNERS").read_text()
