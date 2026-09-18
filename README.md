# jev-ra

**A fast browser-use layer for CLI coding agents.** Claude Code, Codex, or any MCP client hands
jev-ra a goal. TypeSafe Jev, a System One decision model, picks the operation *and* the target
element for every step in one round trip. Your agent plans, supplies the text values, reads what
the page says, and takes over when jev-ra escalates. No second LLM runs inside the loop.

One package, three faces on one browser core: an MCP server (`jev-ra mcp`), a CLI
(`jev-ra run|open|observe|extract|…`), and a Python API (`jev_ra.Agent`).

## Why

Browser agents that put a full LLM in every step pay 1-3 s per click. jev-ra pays one typed
decision, measured at 274-508 ms through OpenRouter.

| | browser-use 0.13.10 + gemini-3-flash `flash_mode` | jev-ra |
|---|---|---|
| Wikipedia: open the Gödel incompleteness article | 23,058 ms · 4 steps | **2,798 ms · 2 steps** (8.2×) |

Both rows: 2026-09-18, same machine, same dedicated Chrome (`BU_CDP_URL=http://127.0.0.1:9222`,
1280×900), models through OpenRouter, one run each. The browser-use rows are in
[`docs/benchmarks/2026-09-18-browser-use-baseline/`](docs/benchmarks/2026-09-18-browser-use-baseline/);
reproduce the jev-ra row with `jev-ra bench --live`. See [Benchmarks](#benchmarks) for the two
tasks that do **not** pass yet.

## Install

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra doctor
```

No install step: `uvx` runs it straight from PyPI. For a permanent copy, `uv tool install jev-ra`
or `pip install jev-ra`.

`doctor` checks the key, the route, the Chrome connection, and makes one live decision with its
latency. jev-ra talks to a real Chrome over CDP through
[browser-harness](https://github.com/browser-use/browser-harness). Point it at a dedicated
automation profile so it never drives your own browser:

```sh
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir="$HOME/.jev-ra-chrome" &
export BU_CDP_URL=http://127.0.0.1:9222
```

## Use it from a coding agent

```sh
uvx jev-ra install claude   # runs: claude mcp add jev-ra -s user -e OPENROUTER_API_KEY=… -- uvx jev-ra mcp
uvx jev-ra install codex    # runs: codex  mcp add jev-ra --env OPENROUTER_API_KEY=… -- uvx jev-ra mcp
```

Nothing to install first: `uvx` fetches jev-ra on demand, and the registered command is `uvx
jev-ra mcp`. If jev-ra is already on `PATH`, the plain `jev-ra mcp` command is registered instead.
`--scope user|project|local` picks where Claude Code stores it.

The key is forwarded from the variable you already exported and is never printed. If `claude` or
`codex` is not on `PATH`, the command to run is printed instead.

### MCP tools

| tool | arguments | what it does |
|---|---|---|
| `browser_open` | url | Open a URL in the shared session and summarise the page. |
| `browser_run` | goal, values?, max_steps? | Pursue a whole goal. Supply values for anything that must be typed. |
| `browser_act` | instruction, values? | Take one decided step towards an instruction. |
| `browser_observe` | max_elements? | List the observed controls and the visible text. |
| `browser_extract` | mode? | Structured page data: `text`, `elements`, `links`, `tables`, `main`. |
| `browser_click` | ref | Click one observed element by its ref. |
| `browser_type` | ref, text | Type into one observed field. |
| `browser_select` | ref, option | Select an observed dropdown option. |
| `browser_scroll` | direction? | Scroll one viewport step up or down. |
| `browser_press` | key | Press Enter, Escape or Tab. |
| `browser_wait` | - | Wait a moment and observe again. |
| `browser_screenshot` | - | JPEG of the current viewport. |
| `browser_close` | - | Close the session held by the server. |

Every response carries `elapsed_ms`, and `decisions` plus `cost` whenever Jev was called.

## Use it from the shell

```sh
jev-ra run https://en.wikipedia.org/wiki/Main_Page \
  "Find and open the Wikipedia article about Godel incompleteness theorems." \
  --value "search_query=Godel incompleteness theorems"
```

```
done: goal_achieved
https://en.wikipedia.org/wiki/G%C3%B6del%27s_incompleteness_theorems
  1. TYPE_TEXT Search Wikipedia 'Godel incompleteness theorems' (p=0.88, 326 ms, changed)
  2. CLICK Gödel's incompleteness theorems … (p=0.75, 274 ms, changed)
2 steps, 5 decisions, 0 text calls, 2959 ms, $0.001195
```

`open` … `close` share one browser across invocations, so you can drive it step by step:

```sh
jev-ra open https://example.com
jev-ra observe
jev-ra click e3
jev-ra extract --mode links
jev-ra close
```

Add `--json` to any command for the raw payload. `jev-ra --help` lists everything.

## Use it from Python

```python
from jev_ra import Agent

with Agent() as agent:
    result = agent.run(
        "Place the order with express shipping.",
        values={"name": "Ada Lovelace", "email": "ada@example.com"},
        url="https://example.com/checkout",
    )
print(result.status, result.elapsed_ms, [step["target_label"] for step in result.steps])
```

## Values, not guesses

TYPE_TEXT needs a string, and jev-ra will not invent one. Jev picks which of *your* values belongs
in the field it is about to fill, in the same round trip that picks the field. If nothing fits and
no text helper is configured, the run stops with `needs_value` and tells you the field's label,
role and current value. You supply the value and call again. That is the whole point: the default
install has no text model in the loop.

## When it hands control back

`Result.status` is `done`, `blocked`, `escalate` or `budget`. An escalation carries `reason`
(`needs_value`, `stuck_loop`, `unverified_done`, `stale`, `invalid_decision`, `too_many_controls`),
the top eight operation/target candidates with their probabilities, and up to 3,000 characters of
page text — enough for your agent to decide what to do without observing again.

Verification is deterministic: after every action jev-ra compares url, title, text and field state,
and `page_changed` comes from a semantic page marker, not from the model's opinion. Three actions
that change nothing, or the same choice three times running, end the run.

## Safety properties

- Model output never becomes a selector, coordinates, or JavaScript. Every executed target resolves
  from a node id observed in the same snapshot.
- Every action re-checks freshness immediately before input; a moved, replaced, disabled or covered
  control raises `StalePage` instead of clicking something else.
- Input is dispatched as trusted CDP events, never synthetic JS clicks.
- Password, file and hidden inputs are never observed or reported.

## Benchmarks

Recorded browser-use baseline, 2026-09-18, `use_vision=False`, one run each
([raw rows](docs/benchmarks/2026-09-18-browser-use-baseline/)):

| task | gemini-3-flash | gemini-3-flash `flash_mode` | gpt-5-mini |
|---|---|---|---|
| Wikipedia: Gödel incompleteness article | 46,461 ms · 5 steps | 23,058 ms · 4 steps | 100,399 ms · 11 steps |
| Google Flights ZRH→LON one-way | 63,565 ms · 11 steps | 66,414 ms · 11 steps | 238,045 ms (budget hit) |
| Olive Young category: sort by 신상품순 | 17,493 ms · 3 steps | 15,071 ms · 3 steps | timeout at 240 s |

claude-sonnet-5 could not drive browser-use at all through OpenRouter (`compiled grammar is too
large` on its structured-output schema) and is excluded.

`jev-ra bench` times two offline fixture tasks with scripted decisions and no network
(form fill 164 ms · 4 steps; catalog sort 73 ms · 2 steps). `jev-ra bench --live` runs the three
tasks above and prints `jev-ra ms / flash_mode ms = ratio` with a PASS/FAIL against the v0.1
acceptance bar of ≥ 3× on every task.

**Where v0.1 stands, 2026-09-18, one run each:**

| task | jev-ra | ratio | verdict |
|---|---|---|---|
| Wikipedia | 2,798 ms · 2 steps · 5 decisions | 8.2× | PASS |
| Google Flights | `blocked` after 4,377 ms | - | FAIL, does not complete |
| Olive Young sort | `blocked` after 6,482 ms | - | FAIL, does not complete |

Both failures are capability, not speed: those pages put their controls inside shadow roots and
iframes, which v0.1 does not traverse. No number in this README is estimated.

## What it will not do in v0.1

Shadow roots, iframes, canvas, file upload, pop-up windows, multi-tab workflows, auth flows,
CAPTCHA, stealth. Pages with more than 250 visible controls report `omitted` and escalate
`too_many_controls` rather than guessing.

## Configuration

| variable | effect |
|---|---|
| `JEV_RA_API_KEY`, `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY` | key, in that order of precedence |
| `JEV_RA_ENDPOINT`, `JEV_RA_MODEL` | override the route; a key starting `sk-or-` selects OpenRouter |
| `JEV_RA_VIEWPORT` | e.g. `1280x900` (the default) |
| `JEV_RA_MAX_STEPS`, `JEV_RA_MAX_DECISIONS`, `JEV_RA_TIMEOUT_S` | budgets (40 / 80 / 120) |
| `JEV_RA_TEXT_MODEL`, `JEV_RA_TEXT_BASE_URL`, `JEV_RA_TEXT_API_KEY` | optional text helper, off by default |
| `BU_CDP_URL` | the Chrome to drive |

`$XDG_CONFIG_HOME/jev-ra/config.json` sets the same keys; the environment wins.

## Credits

`jev_ra/browser/snapshot.js` and the `NEXT_ACTION` / `TARGET` instruction texts are adapted from
[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast) (MIT), where they were
measured. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

MIT licensed. [한국어 README](README.ko.md).
