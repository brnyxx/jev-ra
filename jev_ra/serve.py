"""The MCP tools over HTTP and SSE: one key per team, a daily quota, and a JSON line per request."""

import hashlib
import hmac
import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from . import __version__
from .config import SERVE_HOST, SERVE_PORT, state_path
from .mcp_server import Browser, build_server

logger = logging.getLogger(__name__)

HOST = SERVE_HOST
PORT = SERVE_PORT
MCP_PATH = "/mcp"
HEALTH_PATH = "/healthz"
RUN_HEADER = "x-jev-ra-run-id"
RUN_ID_CHARS = 12
KEY_ID_CHARS = 12
KEYS_VARIABLE = "JEV_RA_SERVE_KEYS"
QUOTA_VARIABLE = "JEV_RA_SERVE_QUOTA"
NO_KEY = {
    "error": "This server needs an API key.",
    "next_step": "Send it as `Authorization: Bearer <key>`, using a key from JEV_RA_SERVE_KEYS.",
}
OVER_QUOTA = {
    "error": "This key has spent its decision quota for today.",
    "next_step": "Wait for the quota to reset at midnight UTC, or raise --quota on the server.",
}
NO_KEYS_CONFIGURED = (
    f"{KEYS_VARIABLE} is empty, and `jev-ra serve` will not open an unauthenticated port. "
    f"Set {KEYS_VARIABLE} to a comma-separated list of keys and start it again."
)


def quota_path(env=None):
    """The JSON file the per-key counters live in, beside the session state."""
    return state_path(env).parent / "quota.json"


def read_keys(env=None):
    """The keys this server accepts, as a comma list in the environment."""
    env = os.environ if env is None else env
    return tuple(part.strip() for part in env.get(KEYS_VARIABLE, "").split(",") if part.strip())


def read_quota(env=None):
    """The configured decisions-per-day limit, or None when nothing is capped."""
    env = os.environ if env is None else env
    raw = env.get(QUOTA_VARIABLE)
    if not raw:
        return None
    try:
        limit = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s %r; no quota is enforced", QUOTA_VARIABLE, raw)
        return None
    return limit if limit > 0 else None


def key_id(key):
    """A short digest naming a key in a log or a counter file, so neither ever holds the key."""
    return hashlib.sha256(key.encode()).hexdigest()[:KEY_ID_CHARS]


def identify(presented, keys):
    """The id of the key a request presented, or None. Compared in constant time."""
    for key in keys:
        if hmac.compare_digest(presented, key):
            return key_id(key)
    return None


def presented_key(headers):
    """The key a request carries, from `Authorization: Bearer` or `x-api-key`."""
    scheme, _, token = headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return headers.get("x-api-key", "").strip()


def today():
    """The UTC date the quota counts against."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


class Quota:
    """Decisions per key per day, in a JSON file so a restart does not hand out a fresh allowance."""

    def __init__(self, path, limit=None, today=today):
        self.path = Path(path)
        self.limit = limit
        self.today = today

    def read(self):
        """The counters for today; a file from another day or an unreadable one counts as empty."""
        day = self.today()
        try:
            stored = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {"day": day, "used": {}}
        if not isinstance(stored, dict) or stored.get("day") != day:
            return {"day": day, "used": {}}
        used = stored.get("used")
        return {"day": day, "used": used if isinstance(used, dict) else {}}

    def used(self, identity):
        """How many decisions this key has spent today."""
        return int(self.read()["used"].get(identity, 0))

    def exhausted(self, identity):
        """Whether this key has nothing left to spend today."""
        return self.limit is not None and self.used(identity) >= self.limit

    def spend(self, identity, decisions=1):
        """Charge decisions to this key and return its new total."""
        if decisions <= 0:
            return self.used(identity)
        stored = self.read()
        total = int(stored["used"].get(identity, 0)) + decisions
        stored["used"][identity] = total
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(stored, indent=2))
        return total


class Meter:
    """Counts every decision the shared browser asks for, so a request can be charged its own."""

    def __init__(self):
        self.decisions = 0
        self.run_id = None

    def count(self, decide):
        """The same decision callable, counted."""

        def counted(state, questions):
            """Ask for one decision and record that it was spent."""
            self.decisions += 1
            return decide(state, questions)

        return counted


class MeteredBrowser(Browser):
    """The MCP server's browser with a meter on the decisions it makes."""

    def __init__(self, meter=None, **kwargs):
        super().__init__(**kwargs)
        self.meter = meter or Meter()

    def decider(self):
        """The decision callable the tools share, counted by this server's meter."""
        return self.meter.count(super().decider())

    def agent(self):
        """An agent that runs under the id this request was already logged with."""
        agent = super().agent()
        agent.run_id = self.meter.run_id
        return agent


class JsonFormatter(logging.Formatter):
    """One JSON object per record, carrying whatever fields the call attached to it."""

    def format(self, record):
        """Render the record as a single line of JSON."""
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(stream=None, level=logging.INFO):
    """Send this process's logs to stderr as one JSON object per line."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    return handler


class Gate:
    """The key, the quota and the log line every request passes through on its way to the tools."""

    def __init__(self, app, keys, quota, meter, clock=time.perf_counter):
        self.app = app
        self.keys = tuple(keys)
        self.quota = quota
        self.meter = meter
        self.clock = clock

    async def __call__(self, scope, receive, send):
        """Answer one ASGI call: the key, the quota, the tools, then the line that records it."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        run_id = uuid.uuid4().hex[:RUN_ID_CHARS]
        started = self.clock()
        identity = None
        if scope.get("path") != HEALTH_PATH:
            identity = identify(presented_key(Headers(scope=scope)), self.keys)
            if identity is None:
                await self.refuse(scope, receive, send, run_id, started, 401, NO_KEY, None)
                return
            if self.quota.exhausted(identity):
                await self.refuse(scope, receive, send, run_id, started, 429, OVER_QUOTA, identity)
                return
        spent = self.meter.decisions
        status = [0]
        # The tools run inside this call, so what the meter gains is what this request spent, and
        # a run started here is stored under the id the line below reports.
        self.meter.run_id = run_id
        try:
            await self.app(scope, receive, self.stamped(send, run_id, status))
        finally:
            self.meter.run_id = None
        decisions = self.meter.decisions - spent
        if identity is not None:
            self.quota.spend(identity, decisions)
        self.record(scope, run_id, started, status[0], identity, decisions)

    def stamped(self, send, run_id, status):
        """The caller's send, with the run id on the response and its status remembered."""

        async def relay(message):
            """Pass one ASGI message on, stamping the response head as it goes."""
            if message["type"] == "http.response.start":
                status[0] = message["status"]
                message["headers"] = [*message.get("headers", []), (RUN_HEADER.encode(), run_id.encode())]
            await send(message)

        return relay

    async def refuse(self, scope, receive, send, run_id, started, status, body, identity):
        """Answer a request that never reaches the tools, and log it the same way."""
        response = JSONResponse(body, status_code=status, headers={RUN_HEADER: run_id})
        await response(scope, receive, send)
        self.record(scope, run_id, started, status, identity, 0)

    def record(self, scope, run_id, started, status, identity, decisions):
        """One structured line for the request that just ended."""
        logger.info(
            "%s %s %s",
            scope.get("method", ""),
            scope.get("path", ""),
            status,
            extra={
                "fields": {
                    "event": "request",
                    "run_id": run_id,
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "status": status,
                    "key": identity,
                    "decisions": decisions,
                    "elapsed_ms": round((self.clock() - started) * 1000),
                }
            },
        )


def build_app(keys, quota, browser=None, host=HOST):
    """The ASGI app: the MCP endpoint behind the gate, plus a health check that needs no key."""
    browser = browser or MeteredBrowser()
    server = build_server(browser)

    @server.custom_route(HEALTH_PATH, methods=["GET"])
    async def health(_request):
        """Say this server is up, for a container or a load balancer."""
        return JSONResponse({"ok": True, "version": __version__})

    app = server.streamable_http_app(streamable_http_path=MCP_PATH, host=host)
    return Gate(app, keys=keys, quota=quota, meter=browser.meter)


def serve(host=HOST, port=PORT, quota=None, env=None, run=None):
    """Run the tools over HTTP and SSE until the process is stopped."""
    env = os.environ if env is None else env
    configure_logging()
    keys = read_keys(env)
    if not keys:
        logger.error(NO_KEYS_CONFIGURED)
        return 1
    limit = quota if quota is not None else read_quota(env)
    app = build_app(keys, Quota(quota_path(env), limit=limit), host=host)
    logger.info(
        "jev-ra serve on http://%s:%s%s",
        host,
        port,
        MCP_PATH,
        extra={"fields": {"event": "start", "keys": len(keys), "quota": limit, "path": MCP_PATH}},
    )
    (run or uvicorn.run)(app, host=host, port=port, log_config=None)
    return 0
