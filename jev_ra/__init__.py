"""A fast browser-use layer for CLI coding agents."""

from .agent import Agent, Result
from .browser.session import Session, StalePage

__version__ = "0.1.0"

__all__ = ["Agent", "Result", "Session", "StalePage", "__version__"]
