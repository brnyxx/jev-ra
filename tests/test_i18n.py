"""Every translated README says the same thing about structure, commands and numbers."""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("docs/i18n/README.ko.md", "docs/i18n/README.ja.md", "docs/i18n/README.zh-CN.md")
SWITCHER = ("English", "한국어", "日本語", "简体中文")


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_i18n", ROOT / "scripts" / "check_i18n.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", VARIANTS)
def test_the_translation_is_in_sync(checker, name):
    problems = checker.compare(checker.ENGLISH.read_text(), (ROOT / name).read_text())
    assert problems == [], f"{name}: " + "; ".join(problems)


def test_the_checker_reports_every_variant(checker):
    assert [name for name, _ in checker.report()] == list(VARIANTS)
    assert checker.main([]) == 0


def test_the_checker_actually_catches_drift(checker):
    english = checker.ENGLISH.read_text()
    assert checker.compare(english, english.replace("2,714", "1,000"))
    assert checker.compare(english, english.replace("## Quick start", "### Quick start"))
    assert checker.compare(english, english.replace("uvx jev-ra doctor", "uvx jev-ra check"))
    assert checker.compare(english, english.replace("296 ms", "150 ms"))


@pytest.mark.parametrize("name", ("README.md", *VARIANTS))
def test_every_readme_carries_the_language_switcher(name):
    text = (ROOT / name).read_text()
    for language in SWITCHER:
        assert language in text, f"{name} does not link {language}"


@pytest.mark.parametrize("name", ("README.md", *VARIANTS))
def test_every_link_resolves_from_where_the_file_lives(name):
    path = ROOT / name
    text = path.read_text()
    references = re.findall(r"\]\(([^)]+)\)", text) + re.findall(r'src="([^"]+)"', text)
    for reference in references:
        if reference.startswith(("http://", "https://", "#", "mailto:")):
            continue
        assert (path.parent / reference.split("#")[0]).exists(), f"{name} points at {reference}"


@pytest.mark.parametrize("name", VARIANTS)
def test_code_blocks_stay_in_english(checker, name):
    """A translated command is a command that no longer works."""
    assert checker.commands((ROOT / name).read_text()) == checker.commands(checker.ENGLISH.read_text())
