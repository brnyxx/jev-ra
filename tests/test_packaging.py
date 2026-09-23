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
    assert set(data["urls"]) == {"Homepage", "Documentation", "Repository", "Issues", "Changelog"}
    assert data["urls"]["Homepage"] == "https://brnyxx.github.io/jev-ra/"
    others = (url for name, url in data["urls"].items() if name != "Homepage")
    assert all(url.startswith("https://github.com/brnyxx/jev-ra") for url in others)
    assert sorted(data["dependencies"]) == ["browser-harness[mcp]>=0.1.13,<0.2", "httpx[http2]>=0.28,<1"]


def test_the_classifiers_say_what_this_is():
    classifiers = project()["classifiers"]
    for needed in (
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Topic :: Internet :: WWW/HTTP :: Browsers",
        "Typing :: Typed",
    ):
        assert needed in classifiers, f"missing classifier {needed}"
    for version in ("3.12", "3.13", "3.14"):
        assert f"Programming Language :: Python :: {version}" in classifiers


def test_the_package_ships_its_data_files():
    package = PYPROJECT.parent / "jev_ra"
    assert (package / "py.typed").exists()
    assert (package / "browser" / "snapshot.js").exists()
    assert sorted(item.name for item in (package / "bench" / "pages").iterdir()) == [
        "catalog.html",
        "checkout.html",
    ]


def test_the_sdist_ships_the_package_and_not_the_brand():
    targets = tomllib.loads(PYPROJECT.read_text())["tool"]["hatch"]["build"]["targets"]
    assert targets["sdist"]["include"] == [
        "jev_ra/**",
        "tests/**",
        "scripts/**",
        "corpus/**",
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "AGENTS.md",
        "pyproject.toml",
    ]
    assert not any(pattern.startswith(("assets", "docs", "npm")) for pattern in targets["sdist"]["include"])


def test_the_social_preview_is_the_size_github_wants():
    from PIL import Image

    with Image.open(PYPROJECT.parent / "assets" / "social-preview.png") as image:
        assert image.size == (1280, 640)


def test_the_npm_keywords_cover_how_people_will_look_for_it():
    import json

    keywords = json.loads((PYPROJECT.parent / "npm" / "package.json").read_text())["keywords"]
    for needed in ("mcp", "mcp-server", "browser-automation", "claude-code", "codex"):
        assert needed in keywords


def test_the_server_command_prefers_an_installed_entry_point():
    assert cli.server_command(which=lambda name: f"/usr/local/bin/{name}") == ["/usr/local/bin/jev-ra", "mcp"]


def test_the_server_command_names_a_virtualenv_entry_point_by_its_path():
    # `uv run` puts the project's .venv/bin on PATH for that run only; the agent starts the server later.
    def which(name):
        return {"jev-ra": "/work/jev-ra/.venv/bin/jev-ra", "uvx": "/opt/bin/uvx"}.get(name)

    assert cli.server_command(which=which) == ["/work/jev-ra/.venv/bin/jev-ra", "mcp"]


def test_the_server_command_falls_back_to_uvx():
    assert cli.server_command(which=lambda name: "/bin/uvx" if name == "uvx" else None) == [
        "uvx",
        "jev-ra",
        "mcp",
    ]


def test_the_server_command_falls_back_to_npx_when_only_node_is_present():
    assert cli.server_command(which=lambda name: "/bin/npx" if name == "npx" else None) == [
        "npx",
        "-y",
        "jev-ra",
        "mcp",
    ]


def test_with_nothing_on_path_the_command_still_names_uvx():
    assert cli.server_command(which=lambda _name: None) == ["uvx", "jev-ra", "mcp"]


def test_the_npm_launcher_pins_the_same_version():
    import json

    package = json.loads((PYPROJECT.parent / "npm" / "package.json").read_text())
    launcher = (PYPROJECT.parent / "npm" / "bin" / "jev-ra.js").read_text()
    assert package["version"] == __version__
    assert f'export const PINNED = "{__version__}"' in launcher
    assert package["bin"] == {"jev-ra": "bin/jev-ra.js"}
    assert "dependencies" not in package


def test_install_registers_the_uvx_command_when_jev_ra_is_absent():
    resolved = config.load({"OPENROUTER_API_KEY": "sk-or-v1-x"})
    argv = cli.install_argv("claude", "user", resolved, which=lambda name: None if name == "jev-ra" else "/bin/" + name)
    assert argv[-3:] == ["uvx", "jev-ra", "mcp"]
    assert cli.install_display(argv, resolved.key_variable).endswith("-- uvx jev-ra mcp")


def test_install_registers_the_plain_command_when_it_is_on_path():
    resolved = config.load({"OPENROUTER_API_KEY": "sk-or-v1-x"})
    argv = cli.install_argv("codex", "user", resolved, which=lambda name: "/bin/" + name)
    assert argv[-2:] == ["/bin/jev-ra", "mcp"]


def test_the_readme_quick_start_uses_uvx():
    readme = (PYPROJECT.parent / "README.md").read_text()
    assert "uvx jev-ra doctor" in readme
    assert "uvx jev-ra install claude" in readme
    assert "uvx jev-ra install codex" in readme


def test_the_server_command_skips_the_entry_point_uvx_is_running_from():
    def which(name):
        return {"jev-ra": "/Users/me/.cache/uv/archive-v0/Ab12/bin/jev-ra", "uvx": "/opt/bin/uvx"}.get(name)

    assert cli.server_command(which=which) == ["uvx", "jev-ra", "mcp"]


def test_the_server_command_skips_the_entry_point_npx_is_running_from():
    def which(name):
        return {"jev-ra": "/Users/me/.npm/_npx/9f/node_modules/.bin/jev-ra", "npx": "/opt/bin/npx"}.get(name)

    assert cli.server_command(which=which) == ["npx", "-y", "jev-ra", "mcp"]
