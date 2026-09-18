"""One error taxonomy. Every surface renders the same sentence plus the same next step."""


class JevRaError(Exception):
    """Something jev-ra could not do. Carries what happened and what to do about it."""

    next_step = ""

    def __init__(self, message, next_step=None):
        super().__init__(message)
        self.message = str(message)
        if next_step is not None:
            self.next_step = next_step

    def render(self):
        """One line: what happened, then what to do about it."""
        return f"{self.message} {self.next_step}".strip()


class ConfigError(JevRaError):
    """jev-ra is not configured well enough to do this."""

    next_step = "Export OPENROUTER_API_KEY, then run `jev-ra doctor`."


class ChromeError(JevRaError):
    """No Chrome could be found, launched or reached."""

    next_step = "Start one with --remote-debugging-port and export BU_CDP_URL, or run `jev-ra doctor`."


class JevError(JevRaError):
    """A decision could not be obtained. No action has been executed."""

    next_step = "Run `jev-ra doctor` to check the key and the route."


class JevAuthError(JevError):
    """The provider rejected the key."""

    next_step = "Check the key in that variable, then run `jev-ra doctor`."


class JevUnavailable(JevError):
    """The provider could not be reached or kept failing."""

    next_step = "Check the connection and try again; `jev-ra doctor` confirms the route."


class JevBadResponse(JevError):
    """The provider answered, but the answers cannot be trusted, so nothing was executed."""

    next_step = "Nothing was executed. Retry; if it persists the provider is returning invalid answers."


class StalePage(JevRaError, ValueError):
    """A decision no longer refers to the observed page."""

    next_step = "Observe the page again before acting on it."


class Escalated(JevRaError):
    """The run stopped and handed control back to the host agent."""

    next_step = "Decide what to do and call again."


def render(error):
    """The user-facing line for any error, jev-ra's own or not."""
    return error.render() if isinstance(error, JevRaError) else str(error)
