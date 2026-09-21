"""A fast browser-use layer for CLI coding agents."""

from .agent import Agent, Result
from .browser.session import Session
from .errors import (
    ChromeError,
    ConfigError,
    Escalated,
    JevAuthError,
    JevBadResponse,
    JevError,
    JevRaError,
    JevUnavailable,
    StalePage,
)

__version__ = "0.1.1"

__all__ = [
    "Agent",
    "ChromeError",
    "ConfigError",
    "Escalated",
    "JevAuthError",
    "JevBadResponse",
    "JevError",
    "JevRaError",
    "JevUnavailable",
    "Result",
    "Session",
    "StalePage",
    "__version__",
]
