"""Root logging setup: stderr only, at the level JEV_RA_LOG_LEVEL names."""

import logging
import os
import sys

ENV = "JEV_RA_LOG_LEVEL"
DEFAULT = "WARNING"
FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def level(env=None):
    """The level JEV_RA_LOG_LEVEL names, or WARNING when it names nothing."""
    env = os.environ if env is None else env
    name = (env.get(ENV) or DEFAULT).upper()
    return name if name in logging.getLevelNamesMapping() else DEFAULT


def configure(env=None, stream=None):
    """Send log lines to stderr at the configured level, without disturbing a host's logging."""
    logging.basicConfig(level=level(env), stream=stream or sys.stderr, format=FORMAT)
