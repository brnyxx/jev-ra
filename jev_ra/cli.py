"""Command line entry point."""

import argparse

from . import __version__


def build_parser():
    parser = argparse.ArgumentParser(prog="jev-ra", description="A fast browser-use layer for CLI coding agents.")
    parser.add_argument("--version", action="version", version=f"jev-ra {__version__}")
    return parser


def main(argv=None):
    build_parser().parse_args(argv)
    return 0
