"""How much the corpus and the live bench ask of one host, counted across every process on this machine.

The pacer spaces the navigations of one run inside one process. A measurement pass is many runs,
often several passes at once from different worktrees, and a day of them sent single hosts hundreds
of visits from one address until one of them started refusing it. This ledger is what those passes
share: one file per day beside the session state, one line per live attempt, rewritten only under a
lock, so every process sees every other's attempts. It gives each host a daily budget, a gap between
two attempts, and a rest for the rest of the day once the host has pushed back. A person's own run,
from the CLI or a host agent, is not a crawl and never goes through it.
"""

import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from .browser.chrome import loopback
from .config import HOST_DAILY_BUDGET, HOST_GAP_S, HOST_REST_S, load, state_path
from .pacing import host_of

logger = logging.getLogger(__name__)

SKIPPED = "skipped"
BUDGET = "host_budget"
RESTING = "host_resting"
PENDING = "pending"
REFUSED = "refused"
LOCK_NAME = ".lock"
CLAIM_ID_CHARS = 12
REFUSED_STATUSES = (403, 429)
REFUSED_REASONS = ("blocked_by_site", "needs_human")


def traffic_dir(env=None):
    """The directory the ledger's day files are kept in, beside the session state."""
    return state_path(env).parent / "traffic"


def ledger(config=None, env=None):
    """This machine's ledger, with the budget, gap and rest the configuration sets."""
    config = config or load(env)
    return Ledger(traffic_dir(env), config.host_daily_budget, config.host_gap_s, config.host_rest_s)


def skipped(row):
    """Whether an attempt was never sent to its host: a pass for nobody, and a failure for nobody."""
    return row.get("status") == SKIPPED


def skips(rows):
    """The attempts that were never sent, by reason: how many, and to which hosts."""
    found = {}
    for row in rows:
        if not skipped(row):
            continue
        entry = found.setdefault(row.get("reason") or SKIPPED, {"attempts": 0, "hosts": []})
        entry["attempts"] += 1
        host = host_of(row.get("url"))
        if host and host not in entry["hosts"]:
            entry["hosts"].append(host)
    return found


def refusal(row):
    """What in an attempt's row says the site pushed back, or an empty string when nothing did.

    A status the site refused with, an error it kept answering, a wall, and a check put up for a
    person all say no. A run that ended `blocked` is read as one too, unless being blocked is what
    its task expected: a file picker or a canvas is the task's own answer, not the site's.
    """
    status = row.get("http_status")
    if status in REFUSED_STATUSES:
        return f"http {status}"
    if row.get("site_error"):
        return "site_error"
    if row.get("reason") in REFUSED_REASONS:
        return row["reason"]
    if (row.get("human_wait_ms") or 0) > 0:
        return "check"
    if row.get("status") == "blocked" and not row.get("passed"):
        return "blocked"
    return ""


def end_of(day):
    """The moment a day's file stops being the one that counts."""
    return (datetime.fromisoformat(day) + timedelta(days=1)).timestamp()


def until_said(until, day):
    """When a rest ends, as the clock on this machine reads it."""
    if until >= end_of(day):
        return "the end of the day"
    return datetime.fromtimestamp(until).strftime("%H:%M")


@dataclass(frozen=True)
class Claim:
    """One live attempt the ledger let through, or the reason it did not."""

    host: str = ""
    task: str = ""
    id: str = ""
    day: str = ""
    at: float = 0.0
    held: float = 0.0
    skipped: str = ""
    said: str = ""


class Ledger:
    """Today's live attempts per host, in a file every process on this machine reads and writes."""

    def __init__(
        self,
        directory,
        budget=HOST_DAILY_BUDGET,
        gap_s=HOST_GAP_S,
        rest_s=HOST_REST_S,
        clock=time.time,
        sleep=time.sleep,
    ):
        self.directory = Path(directory)
        self.budget = budget
        self.gap_s = gap_s
        self.rest_s = rest_s
        self.clock = clock
        self.sleep = sleep

    def day(self, now):
        """The date whose file an attempt at this moment is written to."""
        return date.fromtimestamp(now).isoformat()

    def path(self, day):
        """The file a day's attempts are kept in."""
        return self.directory / f"{day}.jsonl"

    @contextmanager
    def locked(self):
        """Hold the ledger against every other process for one read and write.

        The lock is `flock`, which only a Unix has. It is imported here rather than with the module,
        so a platform without it still runs the bench's local pages, which never reach the ledger,
        and stops at its first live attempt instead of sending one nobody counted.
        """
        import fcntl

        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / LOCK_NAME).open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def read(self, day):
        """Every attempt recorded on a day, oldest first; a line that is not one is passed over."""
        try:
            text = self.path(day).read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        entries = []
        for line in text.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("host"):
                entries.append(entry)
        return entries

    def append(self, day, entry):
        """Add one attempt to a day's file."""
        with self.path(day).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def write(self, day, entries):
        """Replace a day's file in one step, so no reader ever sees half of it."""
        path = self.path(day)
        partial = path.with_suffix(".partial")
        partial.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries), encoding="utf-8")
        partial.replace(path)

    def rest(self, entries, now, day):
        """Until when a host rests after the latest refusal among its attempts, and that refusal; or None."""
        latest = None
        for entry in entries:
            if entry.get("outcome") != REFUSED:
                continue
            until = min(float(entry.get("ended") or entry.get("at") or 0.0) + self.rest_s, end_of(day))
            if until > now and (latest is None or until > latest[0]):
                latest = (until, entry.get("why") or REFUSED)
        return latest

    def resting(self, host, rest, day, task):
        """The claim for an attempt on a host that pushed back today, which is not made."""
        until, why = rest
        said = f"{host} pushed back today ({why}) and is left alone until {until_said(until, day)}; not attempted."
        logger.info("Skipping %s: %s", task or host, said)
        return Claim(host=host, task=task, day=day, skipped=RESTING, said=said)

    def claim(self, url, task=""):
        """Let one live attempt at this url through once its host's gap has passed, or say why it is not made.

        The attempt is written down before it starts, at the moment it may start, so a process that
        asks a moment later waits its own gap after this one instead of starting beside it. A claim
        that had to wait asks once more before it goes: a refusal another process recorded in the
        meantime rests the host, and the claim is taken back unmade.
        """
        host = host_of(url)
        if not host or loopback(urlsplit(url).hostname):
            return Claim(host=host, task=task)
        with self.locked():
            now = self.clock()
            day = self.day(now)
            entries = [entry for entry in self.read(day) if entry["host"] == host]
            rest = self.rest(entries, now, day)
            if rest is not None:
                return self.resting(host, rest, day, task)
            if len(entries) >= self.budget:
                said = f"{host} has had its {self.budget} live attempts for {day}; not attempted."
                logger.info("Skipping %s: %s", task or host, said)
                return Claim(host=host, task=task, day=day, skipped=BUDGET, said=said)
            last = max((float(entry.get("at") or 0.0) for entry in entries), default=None)
            start = now if last is None else max(now, last + self.gap_s)
            claim = Claim(
                host=host, task=task, id=uuid.uuid4().hex[:CLAIM_ID_CHARS], day=day, at=start, held=start - now
            )
            self.append(day, {"id": claim.id, "host": host, "at": round(start, 3), "task": task, "outcome": PENDING})
        if claim.held <= 0:
            return claim
        logger.info("Holding the next live attempt on %s for %.1f s", host, claim.held)
        self.sleep(claim.held)
        with self.locked():
            entries = self.read(day)
            rest = self.rest([entry for entry in entries if entry["host"] == host], self.clock(), day)
            if rest is None:
                return claim
            self.write(day, [entry for entry in entries if entry.get("id") != claim.id])
        return self.resting(host, rest, day, task)

    def settle(self, claim, row):
        """Write down how an attempt ended, and return the refusal it was when the site pushed back."""
        if not claim.id:
            return ""
        why = refusal(row)
        with self.locked():
            entries = self.read(claim.day)
            entry = next((entry for entry in entries if entry.get("id") == claim.id), None)
            if entry is None:
                entry = {"id": claim.id, "host": claim.host, "at": round(claim.at, 3), "task": claim.task}
                entries.append(entry)
            entry.update(outcome=REFUSED if why else row.get("status") or "", ended=round(self.clock(), 3))
            if why:
                entry["why"] = why
            self.write(claim.day, entries)
        if why:
            logger.warning(
                "%s pushed back (%s); the corpus and the bench leave it alone for %g s", claim.host, why, self.rest_s
            )
        return why

    def today(self):
        """Today's attempts per host, how many each has left, and which hosts are resting and why."""
        with self.locked():
            now = self.clock()
            day = self.day(now)
            entries = self.read(day)
        hosts = {}
        for entry in entries:
            hosts.setdefault(entry["host"], []).append(entry)
        rows = []
        for host, attempts in sorted(hosts.items(), key=lambda item: (-len(item[1]), item[0])):
            rest = self.rest(attempts, now, day)
            rows.append(
                {
                    "host": host,
                    "attempts": len(attempts),
                    "left": max(0, self.budget - len(attempts)),
                    "refused": sum(1 for entry in attempts if entry.get("outcome") == REFUSED),
                    "resting_until": round(rest[0], 3) if rest else None,
                    "resting_until_said": until_said(rest[0], day) if rest else "",
                    "why": rest[1] if rest else "",
                }
            )
        return {
            "day": day,
            "path": str(self.path(day)),
            "budget": self.budget,
            "gap_s": self.gap_s,
            "rest_s": self.rest_s,
            "hosts": rows,
        }
