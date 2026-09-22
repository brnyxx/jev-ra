"""Where a run's Result is kept after it ends, so it can be rendered again by its id."""

import json
import logging
import uuid

from .config import state_path
from .errors import JevRaError

logger = logging.getLogger(__name__)

CAP = 200
RUN_ID_CHARS = 12


class RunMissing(JevRaError):
    """No run was stored under that id."""

    next_step = "Run `jev-ra trace` with an id from a result or from the server's log."


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


def write(result, env=None, cap=CAP):
    """Store one Result under its run id and return the path, or None when it could not be kept.

    A run that has already done its work is not failed over the file that records it.
    """
    payload = result.as_dict() if hasattr(result, "as_dict") else result
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


def read(run_id, env=None):
    """The stored Result for a run id."""
    path = runs_dir(env) / f"{run_id}.json"
    try:
        return json.loads(path.read_text())
    except OSError as error:
        raise RunMissing(f"No run {run_id} is stored under {runs_dir(env)}.") from error
    except ValueError as error:
        raise RunMissing(f"The stored run {run_id} is not readable JSON ({error}).") from error
