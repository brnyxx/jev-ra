import json
import subprocess

import pytest

from jev_ra import cli, config
from jev_ra.decide import JevUnavailable, Reply
from tests.test_agent import FakeSession, answer

SECRET = "sk-or-v1-supersecret"


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for name in ("JEV_RA_API_KEY", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "JEV_RA_ENDPOINT", "JEV_RA_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture
def recorded(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="Added stdio MCP server jev-ra\n", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    return calls


def test_install_claude_builds_the_documented_argv(clean_env, monkeypatch, recorded, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    assert cli.main(["install", "claude", "--scope", "user"]) == 0
    assert recorded[0] == [
        "claude",
        "mcp",
        "add",
        "jev-ra",
        "-s",
        "user",
        "-e",
        f"OPENROUTER_API_KEY={SECRET}",
        "--",
        "jev-ra",
        "mcp",
    ]
    out = capsys.readouterr().out
    assert 'claude mcp add jev-ra -s user -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" -- jev-ra mcp' in out
    assert "forwarding OPENROUTER_API_KEY" in out
    assert SECRET not in out


def test_install_codex_builds_the_documented_argv(clean_env, monkeypatch, recorded, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-secret")
    assert cli.main(["install", "codex"]) == 0
    assert recorded[0] == [
        "codex",
        "mcp",
        "add",
        "jev-ra",
        "--env",
        "TYPESAFE_API_KEY=ts-secret",
        "--",
        "jev-ra",
        "mcp",
    ]
    assert "ts-secret" not in capsys.readouterr().out


def test_install_scope_reaches_the_command(clean_env, monkeypatch, recorded):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    cli.main(["install", "claude", "--scope", "project"])
    assert recorded[0][5] == "project"


def test_install_without_a_key_omits_the_env_flag(clean_env, recorded, capsys):
    assert cli.main(["install", "claude"]) == 0
    assert recorded[0] == ["claude", "mcp", "add", "jev-ra", "-s", "user", "--", "jev-ra", "mcp"]
    assert "no key variable to forward" in capsys.readouterr().out


def test_a_missing_binary_prints_the_command_instead_of_running_it(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    ran = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: ran.append(a))
    assert cli.main(["install", "claude"]) == 1
    out = capsys.readouterr().out
    assert "claude is not on PATH" in out
    assert 'OPENROUTER_API_KEY="$OPENROUTER_API_KEY"' in out
    assert SECRET not in out
    assert ran == []


def test_install_json_never_carries_the_key(clean_env, monkeypatch, recorded, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    cli.main(["install", "claude", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["installed"] is True
    assert SECRET not in json.dumps(payload)


def test_doctor_without_a_key_explains_and_exits_one(clean_env, capsys):
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "key: missing" in out
    assert "OPENROUTER_API_KEY" in out
    assert "decision" not in out


def doctor_client(monkeypatch, reply=None, error=None):
    class Client:
        def __init__(self, _config, **_kwargs):
            pass

        def decide(self, state, questions):
            if error:
                raise error
            return reply

        def close(self):
            pass

    monkeypatch.setattr(cli, "DecisionClient", Client)
    monkeypatch.setattr(cli, "Session", lambda *_a, **_k: FakeSession())


def test_doctor_reports_route_chrome_and_one_live_decision(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    reply = Reply(answers={"operation": answer("DONE")}, model="typesafe/jev-1.13", latency_ms=290)
    doctor_client(monkeypatch, reply=reply)
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "key: found in OPENROUTER_API_KEY" in out
    assert f"endpoint: {config.OPENROUTER_ENDPOINT} (openrouter)" in out
    assert "chrome: ok, http://127.0.0.1:9222 (the Chrome you pointed BU_CDP_URL at)" in out
    assert "decision: DONE in" in out
    assert " ms via typesafe/jev-1.13" in out
    assert SECRET not in out


def test_doctor_json_reports_the_measured_latency(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    doctor_client(monkeypatch, reply=Reply(answers={"operation": answer("DONE")}, model="m", latency_ms=1))
    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["chrome"]["source"] == "BU_CDP_URL"
    assert payload["decision"]["ok"] is True
    assert payload["decision"]["latency_ms"] >= 0
    assert payload["key"] is True
    assert SECRET not in json.dumps(payload)


def test_doctor_reports_an_unreachable_endpoint_and_exits_one(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    doctor_client(monkeypatch, error=JevUnavailable("Could not reach the endpoint"))
    assert cli.main(["doctor"]) == 1
    assert "decision: failed (Could not reach the endpoint)" in capsys.readouterr().out


def test_doctor_explains_how_to_start_chrome_when_none_answers(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    doctor_client(monkeypatch, reply=Reply(answers={"operation": answer("DONE")}, model="m"))

    def refuse(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(cli, "Session", refuse)
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "chrome: unreachable" in out
    assert "--remote-debugging-port=9222" in out
