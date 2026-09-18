"""Resolved settings: environment first, then the XDG config file, then defaults."""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_MODEL = "jev-latest"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
OPENROUTER_MODEL = "typesafe/jev-1.13"

KEY_VARIABLES = ("JEV_RA_API_KEY", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY")
DEFAULT_TEXT_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class Viewport:
    width: int = 1280
    height: int = 900


@dataclass(frozen=True)
class Budgets:
    max_steps: int = 40
    max_decisions: int = 80
    timeout_s: float = 120.0


@dataclass(frozen=True)
class TextModel:
    model: str
    base_url: str = DEFAULT_TEXT_BASE_URL
    api_key: str | None = None


@dataclass(frozen=True)
class Config:
    endpoint: str = TYPESAFE_ENDPOINT
    model: str = TYPESAFE_MODEL
    api_key: str | None = None
    key_variable: str | None = None
    text_model: TextModel | None = None
    viewport: Viewport = field(default_factory=Viewport)
    budgets: Budgets = field(default_factory=Budgets)

    @property
    def provider(self):
        return "openrouter" if is_openrouter(self.endpoint) else "typesafe"


def is_openrouter(endpoint):
    return "/alpha/decisions" in endpoint


def config_path(env=None):
    env = os.environ if env is None else env
    home = env.get("XDG_CONFIG_HOME") or Path(env.get("HOME", "~")).expanduser() / ".config"
    return Path(home) / "jev-ra" / "config.json"


def state_path(env=None):
    env = os.environ if env is None else env
    home = env.get("XDG_STATE_HOME") or Path(env.get("HOME", "~")).expanduser() / ".local" / "state"
    return Path(home) / "jev-ra" / "session.json"


def read_file(path):
    if not path or not path.exists():
        return {}
    try:
        stored = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        logger.warning("Ignoring unreadable config %s: %s", path, error)
        return {}
    if not isinstance(stored, dict):
        logger.warning("Ignoring config %s: expected a JSON object", path)
        return {}
    return stored


def positive_int(value, default, label):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if number <= 0:
        logger.warning("Ignoring invalid %s %r; using %s", label, value, default)
        return default
    return number


def positive_float(value, default, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not number > 0:
        logger.warning("Ignoring invalid %s %r; using %s", label, value, default)
        return default
    return number


def read_viewport(raw):
    default = Viewport()
    if raw is None:
        return default
    if isinstance(raw, str):
        parts = raw.lower().split("x")
        raw = {"width": parts[0], "height": parts[1]} if len(parts) == 2 else {}
    if not isinstance(raw, dict) or not raw:
        logger.warning("Ignoring invalid viewport %r; using %sx%s", raw, default.width, default.height)
        return default
    return Viewport(
        width=positive_int(raw.get("width"), default.width, "viewport width"),
        height=positive_int(raw.get("height"), default.height, "viewport height"),
    )


def read_budgets(env, stored):
    stored = stored if isinstance(stored, dict) else {}
    default = Budgets()

    def pick(name):
        return env.get("JEV_RA_" + name.upper(), stored.get(name))

    return Budgets(
        max_steps=positive_int(pick("max_steps") or default.max_steps, default.max_steps, "max_steps"),
        max_decisions=positive_int(
            pick("max_decisions") or default.max_decisions, default.max_decisions, "max_decisions"
        ),
        timeout_s=positive_float(pick("timeout_s") or default.timeout_s, default.timeout_s, "timeout_s"),
    )


def read_text_model(env, stored):
    stored = stored if isinstance(stored, dict) else {}
    model = env.get("JEV_RA_TEXT_MODEL") or stored.get("model")
    if not model:
        return None
    return TextModel(
        model=model,
        base_url=(env.get("JEV_RA_TEXT_BASE_URL") or stored.get("base_url") or DEFAULT_TEXT_BASE_URL).rstrip("/"),
        api_key=env.get("JEV_RA_TEXT_API_KEY") or stored.get("api_key"),
    )


def resolve_key(env, stored):
    for name in KEY_VARIABLES:
        value = env.get(name)
        if value:
            return value, name
    value = stored.get("api_key")
    return (value, "config.json") if value else (None, None)


def load(env=None, path=None):
    env = os.environ if env is None else env
    stored = read_file(config_path(env) if path is None else path)
    api_key, key_variable = resolve_key(env, stored)
    endpoint = env.get("JEV_RA_ENDPOINT") or stored.get("endpoint")
    model = env.get("JEV_RA_MODEL") or stored.get("model")
    # A namespaced model name only exists on OpenRouter, so an explicit model can
    # select the route on its own; an explicit endpoint always wins over both.
    openrouter = (
        is_openrouter(endpoint)
        if endpoint
        else "/" in model
        if model
        else key_variable == "OPENROUTER_API_KEY" or bool(api_key and api_key.startswith("sk-or-"))
    )
    return Config(
        endpoint=endpoint or (OPENROUTER_ENDPOINT if openrouter else TYPESAFE_ENDPOINT),
        model=model or (OPENROUTER_MODEL if openrouter else TYPESAFE_MODEL),
        api_key=api_key,
        key_variable=key_variable,
        text_model=read_text_model(env, stored.get("text_model")),
        viewport=read_viewport(env.get("JEV_RA_VIEWPORT") or stored.get("viewport")),
        budgets=read_budgets(env, stored.get("budgets")),
    )
