# jev-ra (npm launcher)

A fast browser-use layer for CLI coding agents. Claude Code, Codex, or any MCP client hands jev-ra a
goal; TypeSafe Jev picks the operation and the target element for every step in one round trip.

**This package contains no jev-ra code.** It is a launcher: it finds [uv](https://docs.astral.sh/uv/),
offering to install it the first time, and then runs the Python package through `uvx`. Use it when
you do not want to set Python up yourself.

```sh
npx -y jev-ra install claude     # or: install codex
npx -y jev-ra doctor
npx -y jev-ra run https://en.wikipedia.org/wiki/Main_Page "Open the Godel incompleteness article." \
  --value "search_query=Godel incompleteness theorems"
```

Every argument is passed through untouched, so anything in
[the CLI reference](https://github.com/brnyxx/jev-ra/blob/main/docs/USAGE.md) works here.

## Flags this launcher understands

| flag | effect |
|---|---|
| `--yes` | install uv without asking, when it is missing |
| `--no-install` | never install uv; print how to do it and exit 2 |

Neither reaches the Python side. `JEV_RA_FROM` overrides the pinned package specifier, for a local
wheel or a fork.

## Requirements

Node 20 or newer, and a Chrome, Chromium or Edge installed. jev-ra launches its own Chrome on a
dedicated profile, or attaches to `BU_CDP_URL` if you set it. You need an API key in the
environment: `OPENROUTER_API_KEY` or `TYPESAFE_API_KEY`.

MIT licensed. Source, docs and benchmarks: https://github.com/brnyxx/jev-ra
