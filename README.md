# jev-ra

**A fast browser-use layer for CLI coding agents.** Claude Code, Codex, or any MCP client hands
jev-ra a goal. TypeSafe Jev, a System One decision model, picks the operation *and* the target
element for every step in one round trip. Your agent plans, supplies the text values, reads what the
page says, and takes over when jev-ra escalates. No second LLM runs inside the loop.

![jev-ra opening the Gödel incompleteness article in 2.2 seconds](assets/demo/wikipedia.gif)

| task | browser-use 0.13.10 + gemini-3-flash `flash_mode` | jev-ra | |
|---|---|---|---|
| Wikipedia: open the Gödel incompleteness article | 23,058 ms · 4 steps | **2,205 ms · 2 steps** | **10.5×** |

2026-09-18, same machine, same dedicated Chrome, both through OpenRouter, one run each.
[Method and raw rows](docs/BENCHMARKS.md) — including the two tasks that do **not** pass yet.

## Quick start

**Claude Code**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra install claude
# then, in Claude Code: "open wikipedia.org and find the Gödel incompleteness article"
```

**Codex**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra install codex
# then, in Codex: "use jev-ra to open wikipedia.org and find the Gödel incompleteness article"
```

**Shell**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra doctor
uvx jev-ra run https://en.wikipedia.org/wiki/Main_Page "Open the Godel incompleteness article." \
  --value "search_query=Godel incompleteness theorems"
```

There is no install step: `uvx` runs jev-ra straight from PyPI and registers `uvx jev-ra mcp` as the
server command. For a permanent copy, `uv tool install jev-ra`. The key is forwarded from the
variable you already exported and is never printed.

## How it works

```
  your agent                      jev-ra                              Chrome
 ────────────                ───────────────                      ─────────────
  goal + values  ──────────▶  observe ─────────────────────────▶  snapshot.js
                              │   elements, guards, page marker  ◀──── one eval
                              ▼
                              one request: operation? target?
                              value? prev_ok? goal_achieved?  ──▶  Jev  (~300 ms)
                              │
                              ▼
                              freshness guard ──▶ act ──────────▶  trusted CDP input
                              │                                    (no JS clicks)
                              ▼
                              verify url/title/text/fields
                              │
       Result  ◀──────────────┴── done · blocked · escalate · budget
```

One decision per step, one round trip, no model in the act path. The only text that reaches the page
is text you supplied.

## MCP tools

| tool | arguments | what it does |
|---|---|---|
| `browser_open` | url | Open a URL in the shared session and summarise the page. |
| `browser_run` | goal, values?, max_steps? | Pursue a whole goal. Supply values for anything that must be typed. |
| `browser_search` | query, goal?, max_pages? | Search, read the best results in parallel tabs, rank them against the goal. |
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

## CLI

```sh
jev-ra run URL "goal" [--value name=text ...] [--max-steps N] [--json]
jev-ra search "query" ["what the page must answer"] [--max-pages 3]
jev-ra open URL | observe | extract [--mode text|elements|links|tables|main]
jev-ra act "instruction" | click REF | type REF TEXT | select REF OPTION
jev-ra scroll down|up | press Enter|Escape|Tab | wait | screenshot [PATH] | close
jev-ra mcp | install claude|codex [--scope user|project|local] | doctor | bench [--live]
```

`open` … `close` share one browser across invocations through a target id in
`$XDG_STATE_HOME/jev-ra/session.json`. Add `--json` to any command for the raw payload.

## Python

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

TYPE_TEXT needs a string, and jev-ra will not invent one. Jev picks which of *your* values belongs in
the field it is about to fill, in the same round trip that picks the field. If nothing fits and no
text helper is configured, the run stops with `needs_value` and reports the field's label, role and
current value. You supply the value and call again. The default install has no text model in the
loop, and that is the point.

## When it hands control back

`Result.status` is `done`, `blocked`, `escalate` or `budget`. An escalation carries `reason`
(`needs_value`, `stuck_loop`, `unverified_done`, `stale`, `invalid_decision`, `too_many_controls`),
the top eight operation/target candidates with their probabilities, and up to 3,000 characters of
page text — enough to decide what to do without observing again.

Verification is deterministic: after every action jev-ra compares url, title, text and field state,
and `page_changed` comes from a semantic page marker, not from the model's opinion.

## What it will not do

Canvas, file upload, pop-up windows, multi-tab workflows, auth flows, CAPTCHA, stealth. Pages with
more than 250 visible controls report `omitted` and escalate `too_many_controls` rather than guessing.
Cross-origin iframes are reported as one opaque element; open shadow roots and same-origin iframes
**are** traversed.

Two of the three benchmark tasks — Google Flights and the Olive Young sort — currently come back
`blocked`. See [docs/BENCHMARKS.md](docs/BENCHMARKS.md); the numbers there are not rounded in our
favour.

## FAQ

**OpenRouter or a TypeSafe key?** Either. jev-ra resolves `JEV_RA_API_KEY`, then `TYPESAFE_API_KEY`,
then `OPENROUTER_API_KEY`. A key starting `sk-or-` selects the OpenRouter route
(`typesafe/jev-1.13`); anything else goes direct (`jev-latest`). `JEV_RA_ENDPOINT` and
`JEV_RA_MODEL` override both. OpenRouter is easier to get; direct TypeSafe is roughly 140 ms faster
per decision according to the upstream measurements.

**What does a task cost?** The Wikipedia run above cost **$0.000874** for four decisions. Cost scales
with decisions, not with page size, because the state sent is the element table and the visible text,
never the HTML.

**Does it need its own Chrome?** It will find or launch one on its own profile
(`$XDG_STATE_HOME/jev-ra/chrome-profile`) and reuse it. Point `BU_CDP_URL` at a different Chrome to
override. Do not point it at a browser signed into anything you would not let an agent operate.

**Why no text model?** Because the host is already an LLM with the context. Adding a second one costs
675-938 ms per field and invents values. You can still configure one with `JEV_RA_TEXT_MODEL`.

## Configuration

| variable | effect |
|---|---|
| `JEV_RA_API_KEY`, `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY` | key, in that order of precedence |
| `JEV_RA_ENDPOINT`, `JEV_RA_MODEL` | override the route |
| `JEV_RA_CHROME` | path to the browser binary to launch |
| `BU_CDP_URL` | an existing Chrome to drive instead of launching one |
| `JEV_RA_VIEWPORT` | e.g. `1280x900` (the default) |
| `JEV_RA_MAX_STEPS`, `JEV_RA_MAX_DECISIONS`, `JEV_RA_TIMEOUT_S` | budgets (40 / 80 / 120) |
| `JEV_RA_BLOCK_RESOURCES` | `0` to stop blocking fonts and media |
| `JEV_RA_SEARCH_URL` | search endpoint template, `{query}` substituted |
| `JEV_RA_TEXT_MODEL`, `JEV_RA_TEXT_BASE_URL`, `JEV_RA_TEXT_API_KEY` | optional text helper, off by default |

`$XDG_CONFIG_HOME/jev-ra/config.json` sets the same keys; the environment wins.

## Credits

`jev_ra/browser/snapshot.js` and the `NEXT_ACTION` / `TARGET` instruction texts are adapted from
[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast) (MIT), where they were
measured. Chrome is driven through
[browser-harness](https://github.com/browser-use/browser-harness) (MIT).
See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

MIT licensed. [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [한국어](README.ko.md)
