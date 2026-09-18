# Contributing

Thanks for looking. jev-ra is small on purpose; the fastest way to get a change merged is to keep it
that way.

## Setup

```sh
git clone https://github.com/brnyxx/jev-ra && cd jev-ra
uv sync
```

Browser tests need a Chrome with remote debugging on its own profile:

```sh
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir="$HOME/.jev-ra-chrome" &
export BU_CDP_URL=http://127.0.0.1:9222
```

Then the gates, which are the same ones CI runs:

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q          # coverage must stay at or above 85 %
```

Without `BU_CDP_URL` the browser-marked tests skip and coverage will fall short. They must pass
before anything is merged; CI sets `JEV_RA_REQUIRE_BROWSER=1` so a missing Chrome fails instead of
skipping.

## House rules

- Runtime dependencies are `browser-harness[mcp]` and `httpx[http2]`. Adding a third one needs a
  reason in the pull request.
- Model output never becomes a selector, coordinates, or JavaScript. Every executed target resolves
  from a node id observed in the same snapshot. Changes that weaken this will be declined.
- New behaviour comes with tests. A bug fix comes with the test that reproduces it, written first.
- Unit tests never touch the network. Use `httpx.MockTransport`, a fake `decide`, or a fake session.
- `pathlib.Path` for paths, `logging` for diagnostics. stdout belongs to the CLI and the MCP
  protocol.
- No `# noqa`, no `# type: ignore`, no `eval`, no `exec`.
- Public functions and classes carry a docstring and, where it helps, a type hint. Private helpers
  may stay bare.
- Regenerate `docs/USAGE.md` with `uv run python scripts/gen_usage.py` whenever a tool signature or a
  CLI flag changes. CI fails on drift.

## Fixtures

Browser tests serve their own pages from `http.server` on 127.0.0.1 and talk only to the local
Chrome. A fixture must:

- live in `tests/fixtures/` and be a single self-contained HTML file;
- contain no real personal data, no credentials, and no absolute local paths;
- reproduce the behaviour under test with the smallest markup that does so;
- never fetch anything from the network.

A test that needs a real site belongs in the benchmark corpus, not in the test suite.

## Changing the decision path

`NEXT_ACTION` and `TARGET` were measured on real tasks. Changing them, the budgets, the wait caps or
the loop detector needs numbers, not an argument:

```sh
uv run jev-ra bench --live --runs 5     # before and after, both in the pull request
```

The same applies to anything that changes how often Jev is called.

## Benchmarks

Numbers in the README and in `docs/BENCHMARKS.md` come from runs you can reproduce, with the date and
the route stated. Please do not add an estimate, and do not round in our favour. A run that finishes
without doing the task is a failure, not a time.

## Commits and pull requests

- English, conventional prefix, imperative, subject under 72 characters.
- No trailers of any kind, and no AI attribution anywhere in code, docs or messages.
- One concern per commit; the history should read as an incremental build.
- Fill in the pull request template, including the gate checklist.

By contributing you agree that your work is licensed under the MIT license, and that you will follow
the [Code of Conduct](CODE_OF_CONDUCT.md).
