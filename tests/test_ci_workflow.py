"""The CI workflow is part of the contract: browser tests must really run there."""

import os
import re
import tomllib
from pathlib import Path

import pytest

from tests.conftest import chrome_url, require_browser


def load_script(name):
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(name, root / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "ci.yml"
RELEASE = WORKFLOWS / "release.yml"


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


def test_the_release_workflow_is_well_formed():
    text = RELEASE.read_text()
    blocks(text)
    assert text.startswith("name: release\n")
    assert re.search(r"^jobs:$", text, re.MULTILINE)
    assert text.count("steps:") == 3


def test_the_release_workflow_builds_and_uploads_on_tags():
    text = RELEASE.read_text()
    assert 'tags: ["v*"]' in text
    assert "run: uv build" in text
    assert "actions/upload-artifact@v4" in text
    assert "jev-ra --version" in text


def test_publishing_is_gated_on_trusted_publishing_being_configured():
    text = RELEASE.read_text()
    assert "vars.PYPI_TRUSTED == 'true'" in text
    assert "id-token: write" in text
    assert "pypa/gh-action-pypi-publish@release/v1" in text
    # Nothing may fall back to a long-lived token.
    assert "PYPI_API_TOKEN" not in text
    assert "secrets.PYPI" not in text


def test_the_release_workflow_refuses_a_tag_that_does_not_match_the_version():
    text = RELEASE.read_text()
    assert "scripts/check_versions.py" in text
    assert '--tag "$GITHUB_REF_NAME"' in text


def test_the_release_workflow_publishes_the_npm_launcher_with_provenance():
    text = RELEASE.read_text()
    assert "npm publish --provenance --access public" in text
    assert "vars.NPM_PUBLISH == 'true'" in text
    assert "NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}" in text
    assert 'npm pack --dry-run' in text
    assert 'node --test "test/*.test.mjs"' in text


def test_every_version_in_the_repository_agrees():
    check = load_script("check_versions")
    found = check.versions()
    assert set(found) == {"pyproject.toml", "npm/package.json", "npm/bin/jev-ra.js", "jev_ra/__init__.py"}
    assert check.disagreements(found)[0] == []
    assert check.disagreements(found, tag="v" + found["pyproject.toml"])[0] == []
    assert check.disagreements(found, tag="v9.9.9")[0] == ["tag: v9.9.9"]
    assert check.main([]) == 0


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


def test_ci_also_type_checks():
    assert "uv run ty check" in WORKFLOW.read_text()


def test_ci_also_checks_the_format():
    assert "uv run ruff format --check ." in WORKFLOW.read_text()


def test_ci_fails_when_a_version_disagrees():
    assert "scripts/check_versions.py" in WORKFLOW.read_text()


def test_the_npm_publish_job_can_read_the_repository():
    npm_job = RELEASE.read_text().split("  npm:", 1)[1]
    assert "contents: read" in npm_job
    assert "id-token: write" in npm_job


def test_ci_fails_when_the_generated_usage_guide_drifts():
    assert "scripts/gen_usage.py --check" in WORKFLOW.read_text()


def test_ci_fails_when_a_translated_readme_drifts():
    assert "scripts/check_i18n.py --check" in WORKFLOW.read_text()


def test_the_gates_are_configured_in_pyproject():
    data = tomllib.loads((WORKFLOWS.parents[1] / "pyproject.toml").read_text())
    lint = data["tool"]["ruff"]["lint"]
    assert set(lint["select"]) == {"E", "F", "I", "B", "UP", "SIM", "RUF", "D"}
    assert lint["pydocstyle"]["convention"] == "google"
    assert "--cov-fail-under=85" in data["tool"]["pytest"]["ini_options"]["addopts"]
    assert data["tool"]["ty"]["src"]["include"] == ["jev_ra"]
    assert any(name.startswith("ty") for name in data["dependency-groups"]["dev"])
    assert any(name.startswith("pytest-cov") for name in data["dependency-groups"]["dev"])


def test_pre_commit_runs_the_same_gates():
    text = (WORKFLOWS.parents[1] / ".pre-commit-config.yaml").read_text()
    blocks(text)
    assert "ruff-pre-commit" in text
    assert "ty-pre-commit" in text
    assert "uv run pytest -q" in text
    assert "detect-private-key" in text


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
