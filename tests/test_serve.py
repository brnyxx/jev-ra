"""`jev-ra serve`: the same tools over HTTP and SSE, behind a key, a quota and JSON logs."""

import asyncio
import io
import json
import logging
from pathlib import Path

import httpx2
import pytest
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from jev_ra import __version__, cli, config, serve
from jev_ra.decide import Reply
from tests.test_agent import FakeSession, answer
from tests.test_mcp_server import TOOLS

BASE = "http://127.0.0.1:8765"
KEY = "team-alpha-secret"
OTHER = "team-beta-secret"


def decide_done(_state, _questions):
    return Reply(
        answers={"operation": answer("DONE"), "goal_achieved": {"noul": 0.95}},
        latency_ms=9,
        usage={"cost": 0.0001},
    )


@pytest.fixture
def quiet_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers, root.level = handlers, level


def app_with(tmp_path, keys=(KEY,), limit=None, decide=decide_done, day="2026-09-22"):
    meter = serve.Meter()
    browser = serve.MeteredBrowser(meter=meter, config=config.load({}), session_factory=FakeSession, decide=decide)
    quota = serve.Quota(tmp_path / "quota.json", limit=limit, today=lambda: day)
    return serve.build_app(keys=keys, quota=quota, browser=browser), quota


def headers(key):
    return {"Authorization": f"Bearer {key}"} if key else {}


def over_http(app, call, key=KEY):
    async def once():
        async with app.app.router.lifespan_context(app.app):
            transport = httpx2.ASGITransport(app)
            async with httpx2.AsyncClient(transport=transport, base_url=BASE, headers=headers(key)) as http:
                return await call(http)

    return asyncio.run(once())


def with_client(app, call, key=KEY):
    async def talk(http):
        async with Client(streamable_http_client(f"{BASE}/mcp", http_client=http)) as client:
            return await call(client)

    return over_http(app, talk, key=key)


def test_the_keys_are_a_comma_list_from_the_environment():
    assert serve.read_keys({"JEV_RA_SERVE_KEYS": "one, two ,, three "}) == ("one", "two", "three")
    assert serve.read_keys({}) == ()


def test_a_key_is_named_in_a_log_by_a_digest_and_never_by_itself():
    identity = serve.key_id(KEY)
    assert len(identity) == 12
    assert KEY not in identity
    assert serve.key_id(OTHER) != identity


def test_the_quota_file_lives_under_the_state_directory():
    assert serve.quota_path({"XDG_STATE_HOME": "/s"}) == Path("/s/jev-ra/quota.json")


def test_a_request_without_a_key_is_refused(tmp_path):
    app, _quota = app_with(tmp_path)
    answered = over_http(app, lambda http: http.post("/mcp", json={}), key=None)
    assert answered.status_code == 401
    body = answered.json()
    assert "key" in body["error"].lower()
    assert body["next_step"]


def test_a_request_with_the_wrong_key_is_refused(tmp_path):
    app, _quota = app_with(tmp_path)
    answered = over_http(app, lambda http: http.post("/mcp", json={}), key=OTHER)
    assert answered.status_code == 401


def test_the_health_check_needs_no_key(tmp_path):
    app, _quota = app_with(tmp_path)
    answered = over_http(app, lambda http: http.get("/healthz"), key=None)
    assert answered.status_code == 200
    assert answered.json() == {"ok": True, "version": __version__}


def test_the_tools_over_http_are_the_tools_over_stdio(tmp_path):
    app, _quota = app_with(tmp_path)
    listing = with_client(app, lambda client: client.list_tools())
    assert {tool.name for tool in listing.tools} == TOOLS


def test_a_tool_call_runs_over_http(tmp_path):
    app, _quota = app_with(tmp_path)
    result = with_client(app, lambda client: client.call_tool("browser_open", {"url": "http://127.0.0.1/form.html"}))
    assert not result.is_error, result.content
    assert json.loads(result.content[0].text)["url"] == "http://127.0.0.1/form.html"


def test_the_transport_answers_with_server_sent_events(tmp_path):
    app, _quota = app_with(tmp_path)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    accept = {"Accept": "application/json, text/event-stream"}
    answered = over_http(app, lambda http: http.post("/mcp", json=request, headers=accept))
    assert answered.status_code == 200
    assert answered.headers["content-type"].startswith("text/event-stream")


async def open_and_run(client):
    await client.call_tool("browser_open", {"url": "http://127.0.0.1/form.html"})
    return await client.call_tool("browser_run", {"goal": "read the page"})


def test_a_request_is_charged_the_decisions_it_made(tmp_path):
    app, quota = app_with(tmp_path)
    result = with_client(app, open_and_run)
    assert not result.is_error, result.content
    assert quota.used(serve.key_id(KEY)) == 1


def test_a_key_over_its_quota_is_refused(tmp_path):
    app, quota = app_with(tmp_path, limit=1)
    quota.spend(serve.key_id(KEY), 1)
    answered = over_http(app, lambda http: http.post("/mcp", json={}))
    assert answered.status_code == 429
    assert "quota" in answered.json()["error"].lower()


def test_one_key_never_spends_another_key_s_quota(tmp_path):
    app, quota = app_with(tmp_path, keys=(KEY, OTHER), limit=1)
    quota.spend(serve.key_id(KEY), 1)
    answered = over_http(app, lambda http: http.get("/healthz"), key=OTHER)
    assert answered.status_code == 200
    assert quota.used(serve.key_id(OTHER)) == 0


def test_the_quota_starts_over_on_a_new_day(tmp_path):
    day = ["2026-09-22"]
    quota = serve.Quota(tmp_path / "quota.json", limit=5, today=lambda: day[0])
    quota.spend("abc123", 4)
    assert quota.used("abc123") == 4
    assert quota.exhausted("abc123") is False
    quota.spend("abc123", 1)
    assert quota.exhausted("abc123") is True
    day[0] = "2026-09-23"
    assert quota.used("abc123") == 0


def test_an_unreadable_quota_file_starts_the_day_over(tmp_path):
    path = tmp_path / "quota.json"
    path.write_text("{not json")
    quota = serve.Quota(path, limit=2)
    assert quota.used("abc123") == 0
    assert quota.spend("abc123", 1) == 1


def test_no_quota_configured_never_refuses(tmp_path):
    quota = serve.Quota(tmp_path / "quota.json")
    quota.spend("abc123", 10_000)
    assert quota.exhausted("abc123") is False


def test_every_answered_request_is_one_json_line_with_a_run_id(tmp_path, quiet_logging):
    stream = io.StringIO()
    serve.configure_logging(stream)
    app, _quota = app_with(tmp_path)
    with_client(app, open_and_run)
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    answered = [line for line in lines if line.get("event") == "request"]
    assert answered
    fields = {"ts", "run_id", "method", "path", "status", "key", "decisions", "elapsed_ms"}
    assert all(set(line) >= fields for line in answered)
    assert all(len(line["run_id"]) == 12 for line in answered)
    assert all(line["key"] == serve.key_id(KEY) for line in answered)
    assert sum(line["decisions"] for line in answered) == 1
    assert KEY not in stream.getvalue()


def test_the_logged_run_id_is_the_id_the_run_is_stored_under(tmp_path, quiet_logging, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    stream = io.StringIO()
    serve.configure_logging(stream)
    app, _quota = app_with(tmp_path)
    with_client(app, open_and_run)
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    spent = [line["run_id"] for line in lines if line.get("event") == "request" and line["decisions"]]
    stored = [path.stem for path in (tmp_path / "state" / "jev-ra" / "runs").glob("*.json")]
    assert spent == stored


def test_a_refused_request_is_logged_too(tmp_path, quiet_logging):
    stream = io.StringIO()
    serve.configure_logging(stream)
    app, _quota = app_with(tmp_path)
    over_http(app, lambda http: http.post("/mcp", json={}), key=OTHER)
    refused = [json.loads(line) for line in stream.getvalue().splitlines() if '"request"' in line]
    assert [line["status"] for line in refused] == [401]
    assert refused[0]["key"] is None
    assert OTHER not in stream.getvalue()


def test_the_run_id_comes_back_on_the_response(tmp_path, quiet_logging):
    stream = io.StringIO()
    serve.configure_logging(stream)
    app, _quota = app_with(tmp_path)
    answered = over_http(app, lambda http: http.get("/healthz"), key=None)
    logged = [json.loads(line) for line in stream.getvalue().splitlines() if '"request"' in line]
    assert answered.headers[serve.RUN_HEADER] == logged[0]["run_id"]


def test_serve_refuses_to_start_without_keys(quiet_logging):
    started = []
    assert serve.serve(env={}, run=lambda *args, **kwargs: started.append(kwargs)) == 1
    assert started == []


def test_serve_runs_the_app_on_the_given_host_and_port(tmp_path, quiet_logging):
    started = []
    code = serve.serve(
        host="0.0.0.0",
        port=9001,
        env={"JEV_RA_SERVE_KEYS": KEY, "XDG_STATE_HOME": str(tmp_path)},
        run=lambda app, **kwargs: started.append((app, kwargs)),
    )
    assert code == 0
    assert started[0][1]["host"] == "0.0.0.0"
    assert started[0][1]["port"] == 9001


def test_the_cli_exposes_serve_with_a_host_and_a_port():
    args = cli.build_parser().parse_args(["serve", "--host", "0.0.0.0", "--port", "9001", "--quota", "500"])
    assert args.handler is cli.cmd_serve
    assert (args.host, args.port, args.quota) == ("0.0.0.0", 9001, 500)


def test_the_cli_hands_the_parsed_arguments_to_the_server(monkeypatch):
    seen = {}
    monkeypatch.setattr(serve, "serve", lambda **kwargs: seen.update(kwargs) or 0)
    args = cli.build_parser().parse_args(["serve"])
    assert args.handler(args) == 0
    assert seen == {"host": serve.HOST, "port": serve.PORT, "quota": None}
