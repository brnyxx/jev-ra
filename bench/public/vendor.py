"""The benchmark repositories, fetched at a pinned commit into a directory git never sees.

Neither task set may live in this repository: Online-Mind2Web is CC-BY data behind a gated
Hugging Face repo, WebVoyager's is a 137 kB file its authors maintain, and both change when the
web underneath them changes. So the runners fetch what they need at run time, always at a commit
named here, into `bench/public/vendor/`, which `.gitignore` keeps out of every commit.
"""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

VENDOR = Path(__file__).resolve().parent / "vendor"
GIT_TIMEOUT_S = 600


@dataclass(frozen=True)
class Pin:
    """One upstream repository at one commit, checked out down to the paths that are used."""

    url: str
    commit: str
    paths: tuple


PINS = {
    "online-mind2web": Pin(
        url="https://github.com/OSU-NLP-Group/Online-Mind2Web.git",
        commit="f0d805ee0e9e0b3ea70911e45e5264b72968f3dc",
        paths=("README.md", "requirements.txt", "script/*", "src/*", "data/schema_v2/*"),
    ),
    "webvoyager": Pin(
        url="https://github.com/MinorJerry/WebVoyager.git",
        commit="5a7896738c10bfb8b9edccce6bb0e0411f8ae569",
        paths=("README.md", "data/*", "evaluation/*"),
    ),
}


def git(*args, cwd=None):
    """One git command, with its own stderr in the exception when it fails."""
    done = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout.strip()


def ensure(name, root=None):
    """The checkout of one pinned repository, fetched on first use and reused after that."""
    pin = PINS[name]
    path = Path(root or VENDOR) / name
    if (path / ".git").exists() and head(path) == pin.commit:
        return path
    path.mkdir(parents=True, exist_ok=True)
    logger.info("Fetching %s at %s into %s", pin.url, pin.commit[:12], path)
    git("init", "-q", str(path))
    if "origin" in remotes(path):
        git("remote", "remove", "origin", cwd=path)
    git("remote", "add", "origin", pin.url, cwd=path)
    git("sparse-checkout", "set", "--no-cone", *pin.paths, cwd=path)
    # Blobless and one commit deep: the history of these repositories is screenshots, and the
    # only thing wanted from them is the tree at a commit that will not move under a number.
    git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", pin.commit, cwd=path)
    git("checkout", "-q", "FETCH_HEAD", cwd=path)
    return path


def head(path):
    """The commit a checkout is on, or an empty string when it has none."""
    try:
        return git("rev-parse", "HEAD", cwd=path)
    except RuntimeError:
        return ""


def remotes(path):
    """The remotes a checkout already has."""
    return git("remote", cwd=path).split()
