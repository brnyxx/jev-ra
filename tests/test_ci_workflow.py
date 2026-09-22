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
    assert text.count("steps:") == 5


def test_the_cold_start_job_launches_its_own_browser_without_a_cdp_url():
    cold = WORKFLOW.read_text().split("  cold-start:", 1)[1]
    assert "runs-on: ubuntu-latest" in cold
    assert 'python-version: "3.12"' in cold
    assert "JEV_RA_REQUIRE_BROWSER" in cold
    assert "doctor --json" in cold
    assert '"launched"' in cold
    assert "tests/test_first_run.py tests/test_chrome.py" in cold
    # The whole point of the job: no Chrome is handed to it.
    assert "BU_CDP_URL" not in cold


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


def test_pypi_publishes_with_the_maintainer_token_and_skips_what_is_already_there():
    text = RELEASE.read_text()
    assert "vars.PYPI_TRUSTED == 'true'" in text
    assert "pypa/gh-action-pypi-publish@release/v1" in text
    assert "password: ${{ secrets.PYPI_API_TOKEN }}" in text
    assert "skip-existing: true" in text
    pypi_job = text[text.index("  pypi:") : text.index("  npm:")]
    # The token is the credential; the job asks for no OIDC token it would not use.
    assert "id-token: write" not in pypi_job


def test_the_release_workflow_refuses_a_tag_that_does_not_match_the_version():
    text = RELEASE.read_text()
    assert "scripts/check_versions.py" in text
    assert '--tag "$GITHUB_REF_NAME"' in text


def test_the_release_workflow_publishes_the_npm_launcher_with_provenance():
    text = RELEASE.read_text()
    assert "npm publish --provenance --access public" in text
    assert "vars.NPM_PUBLISH == 'true'" in text
    assert "NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}" in text
    assert "npm pack --dry-run" in text
    assert "npm test" in text  # package.json spells the glob; Node 20 does not expand a quoted one


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


def job(name):
    """One job out of the workflow: everything under its name up to the next job's."""
    chunk = WORKFLOW.read_text().split(f"\n  {name}:\n", 1)[1]
    following = re.search(r"^  \w[\w-]*:$", chunk, re.MULTILINE)
    return chunk[: following.start()] if following else chunk


def test_ci_starts_cold_on_windows_and_macos():
    assert "runs-on: windows-latest" in job("windows")
    assert "runs-on: macos-latest" in job("macos")
    # Cold means the browser jev-ra finds and launches itself, so neither job may point it at one.
    for name in ("windows", "macos"):
        assert "BU_CDP_URL:" not in job(name)
        assert "export BU_CDP_URL" not in job(name)
        assert "doctor --json" in job(name)
        assert "chrome" in job(name)


def test_the_windows_job_says_why_it_is_not_blocking_yet():
    windows = job("windows")
    assert "continue-on-error: true" in windows
    reason = [line.strip(" #") for line in windows.splitlines() if line.strip().startswith("#")]
    assert any("never been run on Windows" in line for line in reason), reason


def test_the_macos_job_is_blocking():
    assert "continue-on-error" not in job("macos")


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
