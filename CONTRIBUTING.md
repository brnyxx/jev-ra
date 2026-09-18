# Contributing

Thanks for looking. jev-ra is small on purpose; the fastest way to get a change merged is to keep it
that way.

## Setup

```sh
uv sync
export BU_CDP_URL=http://127.0.0.1:9222   # a Chrome with remote debugging, on its own profile
uv run ruff check . && uv run pytest -q
```

Without `BU_CDP_URL` the browser-marked tests skip. They must pass before anything is merged; CI runs
them against a headless Chrome and fails if they skip.

## House rules

- Runtime dependencies are `browser-harness[mcp]` and `httpx[http2]`. Adding a third one needs a
  reason in the pull request.
- Model output never becomes a selector, coordinates, or JavaScript. Every executed target resolves
  from a node id observed in the same snapshot. Changes that weaken this will be declined.
- New behaviour comes with tests. A bug fix comes with the test that reproduces it, written first.
- Unit tests never touch the network. Use `httpx.MockTransport`, a fake `decide`, or a fake session.
- Browser tests serve their fixtures from `http.server` on 127.0.0.1 and talk only to the local
  Chrome.
- `pathlib.Path` for paths, `logging` for diagnostics. stdout belongs to the CLI and the MCP
  protocol.
- No `# noqa`, no `# type: ignore`, no `eval`, no `exec`.
- The `NEXT_ACTION` and `TARGET` instruction texts were measured. Changing them requires a
  `jev-ra bench --live` run before and after, in the pull request.

## Benchmarks

Numbers in the README and in `docs/BENCHMARKS.md` come from runs you can reproduce, with the date
and the route stated. Please do not add an estimate.

## Commits

English, conventional prefix, imperative, subject under 72 characters, no trailers.
