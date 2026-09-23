"""Where a run's Result is kept after it ends, so it can be rendered again by its id."""

import json
import logging
import re
import uuid

from .config import state_path
from .errors import JevRaError

logger = logging.getLogger(__name__)

CAP = 200
RUN_ID_CHARS = 12
# A run id comes back from whoever holds it - a host agent, an HTTP client - and becomes a file
# name, so it is only ever the characters an id is made of.
RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class RunMissing(JevRaError):
    """No run was stored under that id."""

    next_step = "Run `jev-ra trace` with an id from a result or from the server's log."


class NotResumable(JevRaError):
    """The stored run did not stop for a human check, so there is nothing to carry on."""

    next_step = "Start the goal again instead."


def runs_dir(env=None):
    """The directory a run's Result is written to, beside the session state."""
    return state_path(env).parent / "runs"


def new_id():
    """A fresh run id: short enough to paste, long enough not to collide."""
    return uuid.uuid4().hex[:RUN_ID_CHARS]


def prune(directory, cap=CAP):
    """Delete the oldest stored runs until only `cap` are left."""
    stored = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for path in stored[: max(0, len(stored) - cap)]:
        path.unlink(missing_ok=True)


def write(result, env=None, cap=CAP, resume=None):
    """Store one Result under its run id and return the path, or None when it could not be kept.

    A run that has already done its work is not failed over the file that records it. A run that
    stopped for a human check keeps what it needs to carry on beside its Result, under `resume`.
    """
    payload = result.as_dict() if hasattr(result, "as_dict") else result
    if resume is not None:
        payload = {**payload, "resume": resume}
    directory = runs_dir(env)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{payload['run_id']}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        prune(directory, cap)
    except OSError as error:
        logger.warning("Could not store run %s under %s: %s", payload.get("run_id"), directory, error)
        return None
    return path


def resumable(run_id, env=None):
    """The stored run a resume carries on: one that stopped for a human check nobody cleared."""
    stored = read(run_id, env)
    if stored.get("reason") != "needs_human" or not isinstance(stored.get("resume"), dict):
        raise NotResumable(
            f"Run {run_id} ended as {stored.get('reason') or stored.get('status')}, not needs_human; "
            "only a run that stopped for a human check can be resumed."
        )
    return stored


def read(run_id, env=None):
    """The stored Result for a run id."""
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise RunMissing(f"{run_id!r} is not a run id.")
    path = runs_dir(env) / f"{run_id}.json"
    try:
        return json.loads(path.read_text())
    except OSError as error:
        raise RunMissing(f"No run {run_id} is stored under {runs_dir(env)}.") from error
    except ValueError as error:
        raise RunMissing(f"The stored run {run_id} is not readable JSON ({error}).") from error
