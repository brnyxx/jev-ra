import json
import logging

from jev_ra import config


def test_key_precedence_prefers_jev_ra_over_typesafe_over_openrouter():
    env = {"JEV_RA_API_KEY": "a", "TYPESAFE_API_KEY": "b", "OPENROUTER_API_KEY": "c"}
    assert config.load(env, path=None).api_key == "a"
    assert config.load({k: v for k, v in env.items() if k != "JEV_RA_API_KEY"}).api_key == "b"
    assert config.load({"OPENROUTER_API_KEY": "c"}).api_key == "c"


def test_openrouter_key_selects_the_openrouter_route():
    resolved = config.load({"TYPESAFE_API_KEY": "sk-or-v1-xyz"})
    assert resolved.provider == "openrouter"
    assert resolved.endpoint == config.OPENROUTER_ENDPOINT
    assert resolved.model == config.OPENROUTER_MODEL
    assert resolved.key_variable == "TYPESAFE_API_KEY"


def test_typesafe_key_selects_the_direct_route():
    resolved = config.load({"TYPESAFE_API_KEY": "ts-123"})
    assert resolved.provider == "typesafe"
    assert resolved.endpoint == config.TYPESAFE_ENDPOINT
    assert resolved.model == config.TYPESAFE_MODEL


def test_explicit_endpoint_wins_over_the_key_shape():
    resolved = config.load({"OPENROUTER_API_KEY": "sk-or-v1-xyz", "JEV_RA_ENDPOINT": config.TYPESAFE_ENDPOINT})
    assert resolved.provider == "typesafe"
    assert resolved.model == config.TYPESAFE_MODEL


def test_explicit_namespaced_model_selects_openrouter():
    resolved = config.load({"TYPESAFE_API_KEY": "ts-123", "JEV_RA_MODEL": "typesafe/jev-1.13"})
    assert resolved.endpoint == config.OPENROUTER_ENDPOINT
    assert resolved.model == "typesafe/jev-1.13"


def test_text_model_is_absent_by_default_and_optional():
    assert config.load({}).text_model is None
    text_model = config.load({"JEV_RA_TEXT_MODEL": "gpt-4.1-mini", "JEV_RA_TEXT_BASE_URL": "https://x/v1/"}).text_model
    assert text_model.model == "gpt-4.1-mini"
    assert text_model.base_url == "https://x/v1"
    assert text_model.api_key is None


def test_viewport_and_budget_defaults():
    resolved = config.load({})
    assert (resolved.viewport.width, resolved.viewport.height) == (1280, 900)
    assert resolved.budgets.max_steps == 40
    assert resolved.budgets.max_decisions == 80
    assert resolved.budgets.timeout_s == 120.0
    assert resolved.api_key is None


def test_environment_overrides_viewport_and_budgets():
    resolved = config.load({"JEV_RA_VIEWPORT": "800x600", "JEV_RA_MAX_STEPS": "7", "JEV_RA_TIMEOUT_S": "1.5"})
    assert (resolved.viewport.width, resolved.viewport.height) == (800, 600)
    assert resolved.budgets.max_steps == 7
    assert resolved.budgets.timeout_s == 1.5


def test_invalid_values_fall_back_with_warnings(caplog):
    with caplog.at_level(logging.WARNING, logger="jev_ra.config"):
        resolved = config.load({"JEV_RA_VIEWPORT": "wide", "JEV_RA_MAX_STEPS": "-3", "JEV_RA_TIMEOUT_S": "soon"})
    assert (resolved.viewport.width, resolved.viewport.height) == (1280, 900)
    assert resolved.budgets.max_steps == 40
    assert resolved.budgets.timeout_s == 120.0
    assert len(caplog.records) == 3


def test_config_file_fills_gaps_and_environment_wins(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "api_key": "from-file",
                "model": "jev-latest",
                "viewport": {"width": 1000, "height": 700},
                "budgets": {"max_decisions": 9},
                "text_model": {"model": "local-writer", "base_url": "http://127.0.0.1:1234/v1"},
            }
        )
    )
    resolved = config.load({}, path=path)
    assert resolved.api_key == "from-file"
    assert resolved.key_variable == "config.json"
    assert resolved.viewport.width == 1000
    assert resolved.budgets.max_decisions == 9
    assert resolved.text_model.base_url == "http://127.0.0.1:1234/v1"
    assert config.load({"JEV_RA_API_KEY": "from-env"}, path=path).api_key == "from-env"


def test_unreadable_config_file_is_ignored_with_a_warning(tmp_path, caplog):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    with caplog.at_level(logging.WARNING, logger="jev_ra.config"):
        resolved = config.load({}, path=path)
    assert resolved.api_key is None
    assert "Ignoring unreadable config" in caplog.text


def test_xdg_paths_follow_the_environment(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_STATE_HOME": str(tmp_path / "state")}
    assert config.config_path(env) == tmp_path / "cfg" / "jev-ra" / "config.json"
    assert config.state_path(env) == tmp_path / "state" / "jev-ra" / "session.json"
