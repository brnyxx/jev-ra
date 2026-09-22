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

SERVE_HOST = "127.0.0.1"
SERVE_PORT = 8765

KEY_VARIABLES = ("JEV_RA_API_KEY", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY")
DEFAULT_TEXT_BASE_URL = "https://api.openai.com/v1"
ENV_VARIABLES = (
    *KEY_VARIABLES,
    "JEV_RA_ENDPOINT",
    "JEV_RA_MODEL",
    "JEV_RA_CHROME",
    "BU_CDP_URL",
    "JEV_RA_VIEWPORT",
    "JEV_RA_MAX_STEPS",
    "JEV_RA_MAX_DECISIONS",
    "JEV_RA_TIMEOUT_S",
    "JEV_RA_BLOCK_RESOURCES",
    "JEV_RA_ALLOW_FILE_URLS",
    "JEV_RA_SEARCH_URL",
    "JEV_RA_TEXT_MODEL",
    "JEV_RA_TEXT_BASE_URL",
    "JEV_RA_TEXT_API_KEY",
    "JEV_RA_SERVE_KEYS",
    "JEV_RA_SERVE_QUOTA",
    "JEV_RA_LOG_LEVEL",
)


# What one call may ask a tool for. These are not budgets the caller is spending, they are the range
# the tool can answer for at all: a run of ten thousand steps, a search of four hundred pages or a
# snapshot of every node on a large page is a mistake at the edge, not a decision worth making.
MAX_STEPS_LIMIT = 200
MAX_PAGES_LIMIT = 10
MAX_VALUES = 50
MAX_VALUE_CHARS = 20000


def clamp(value, low, high, label):
    """One integer argument held inside the range a tool can answer for."""
    if value is None:
        return None
    held = max(low, min(high, int(value)))
    if held != value:
        logger.info("%s %s is outside %s..%s; using %s", label, value, low, high, held)
    return held


@dataclass(frozen=True)
class Viewport:
    """The window size every session emulates."""

    width: int = 1280
    height: int = 900


@dataclass(frozen=True)
class Budgets:
    """How far one run may go before it stops on its own."""

    max_steps: int = 40
    max_decisions: int = 80
    timeout_s: float = 120.0


@dataclass(frozen=True)
class TextModel:
    """An optional OpenAI-compatible model that writes field values."""

    model: str
    base_url: str = DEFAULT_TEXT_BASE_URL
    api_key: str | None = None


@dataclass(frozen=True)
class Config:
    """Everything one run needs to know, resolved from env, file and defaults."""

    endpoint: str = TYPESAFE_ENDPOINT
    model: str = TYPESAFE_MODEL
    api_key: str | None = None
    key_variable: str | None = None
    text_model: TextModel | None = None
    viewport: Viewport = field(default_factory=Viewport)
    budgets: Budgets = field(default_factory=Budgets)
    block_resources: bool = True
    allow_file_urls: bool = False

    @property
    def provider(self):
        """Which route the endpoint belongs to: `openrouter` or `typesafe`."""
        return "openrouter" if is_openrouter(self.endpoint) else "typesafe"


def is_openrouter(endpoint):
    """Whether this endpoint is the OpenRouter decisions route."""
    return "/alpha/decisions" in endpoint


def redact(text, secret):
    """Text with a secret taken out of it, for anything a caller or a log will see."""
    if not secret:
        return text
    return text.replace(secret, "[redacted]")


def config_path(env=None):
    """The XDG config file jev-ra reads."""
    env = os.environ if env is None else env
    home = env.get("XDG_CONFIG_HOME") or Path(env.get("HOME", "~")).expanduser() / ".config"
    return Path(home) / "jev-ra" / "config.json"


def state_path(env=None):
    """The XDG state file the stateful CLI commands share."""
    env = os.environ if env is None else env
    home = env.get("XDG_STATE_HOME") or Path(env.get("HOME", "~")).expanduser() / ".local" / "state"
    return Path(home) / "jev-ra" / "session.json"


def read_file(path):
    """The stored config as a dict; an unreadable file is a warning, not an error."""
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


FALSE_VALUES = {"0", "false", "no", "off"}


def read_flag(value, default):
    """A boolean from a string, treating 0/false/no/off as false."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in FALSE_VALUES


def positive_int(value, default, label):
    """A positive int, or the default with a warning."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if number <= 0:
        logger.warning("Ignoring invalid %s %r; using %s", label, value, default)
        return default
    return number


def positive_float(value, default, label):
    """A positive float, or the default with a warning."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not number > 0:
        logger.warning("Ignoring invalid %s %r; using %s", label, value, default)
        return default
    return number


def read_viewport(raw):
    """A viewport from `WIDTHxHEIGHT` or a mapping, falling back to the default."""
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
    """The step, decision and time budgets, environment first."""
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
    """The optional text helper, or None when none is configured."""
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
    """The first key the environment offers, and where it came from."""
    for name in KEY_VARIABLES:
        value = env.get(name)
        if value:
            return value, name
    value = stored.get("api_key")
    return (value, "config.json") if value else (None, None)


def load(env=None, path=None):
    """Resolve the full configuration for this process."""
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
        block_resources=read_flag(env.get("JEV_RA_BLOCK_RESOURCES", stored.get("block_resources")), True),
        allow_file_urls=read_flag(env.get("JEV_RA_ALLOW_FILE_URLS", stored.get("allow_file_urls")), False),
    )
