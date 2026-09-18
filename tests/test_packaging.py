"""The package has to be runnable with uvx, with no prior install step."""

import tomllib
from pathlib import Path

from jev_ra import __version__, cli, config

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def project():
    return tomllib.loads(PYPROJECT.read_text())["project"]


def test_both_entry_points_are_declared():
    scripts = project()["scripts"]
    assert scripts["jev-ra"] == "jev_ra.cli:main"
    assert scripts["jev-ra-mcp"] == "jev_ra.mcp_server:main"


def test_the_metadata_is_complete_enough_to_publish():
    data = project()
    assert data["version"] == __version__
    assert data["requires-python"] == ">=3.12"
    assert data["license"] == "MIT"
    assert data["readme"] == "README.md"
    assert set(data["urls"]) >= {"Homepage", "Repository", "Issues", "Changelog"}
    assert any(line.startswith("License :: OSI Approved :: MIT") for line in data["classifiers"])
    assert sorted(data["dependencies"]) == ["browser-harness[mcp]>=0.1.13,<0.2", "httpx[http2]>=0.28,<1"]


def test_the_server_command_prefers_an_installed_entry_point():
    assert cli.server_command(which=lambda name: f"/usr/local/bin/{name}") == ["jev-ra", "mcp"]


def test_the_server_command_falls_back_to_uvx():
    assert cli.server_command(which=lambda _name: None) == ["uvx", "jev-ra", "mcp"]


def test_install_registers_the_uvx_command_when_jev_ra_is_absent():
    resolved = config.load({"OPENROUTER_API_KEY": "sk-or-v1-x"})
    argv = cli.install_argv("claude", "user", resolved, which=lambda name: None if name == "jev-ra" else "/bin/" + name)
    assert argv[-3:] == ["uvx", "jev-ra", "mcp"]
    assert cli.install_display(argv, resolved.key_variable).endswith("-- uvx jev-ra mcp")


def test_install_registers_the_plain_command_when_it_is_on_path():
    resolved = config.load({"OPENROUTER_API_KEY": "sk-or-v1-x"})
    argv = cli.install_argv("codex", "user", resolved, which=lambda name: "/bin/" + name)
    assert argv[-2:] == ["jev-ra", "mcp"]


def test_the_readme_quick_start_uses_uvx():
    readme = (PYPROJECT.parent / "README.md").read_text()
    assert "uvx jev-ra doctor" in readme
    assert "uvx jev-ra install claude" in readme
    assert "uvx jev-ra install codex" in readme
