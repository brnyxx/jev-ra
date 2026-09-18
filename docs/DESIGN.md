# jev-ra design

**jev-ra is a fast browser-use layer for CLI coding agents.** Claude Code, Codex, or any MCP client hands it a goal; TypeSafe Jev, a System One decision model, picks the operation and the target element for every step in one round trip (measured 274-660 ms through OpenRouter, ~180 ms direct); the host agent plans, supplies text values, reads what the page says, and takes over when jev-ra escalates. No second LLM runs inside the loop.

It ships as one Python package with three faces on one browser core: an MCP server (`jev-ra mcp`), a CLI (`jev-ra run|open|act|observe|extract|...`), and a Python API (`jev_ra.Agent`).

## Why this shape

Browser agents that put an LLM in every step pay 1-3 s per click. jev-ultrafast (browser-use org, MIT) showed that a typed decision model on an indexed DOM snapshot completes a Google Flights search in ~7 s with 17 decisions. But it is a demo: no MCP, no CLI beyond one script, no extraction, and it needs a second text model to type anything.

jev-ra keeps that loop and fixes the missing pieces by leaning on the host agent, which is already an LLM:

| need | jev-ultrafast | jev-ra |
|---|---|---|
| plan the task | one goal string | host agent, refined between calls |
| pick op + element per step | Jev | Jev (same design) |
| type a value | mercury-2.5 helper, 675-938 ms | host-supplied `values`; Jev binds field to value (no text model); optional helper only if configured |
| read the page / extract data | none | `observe`/`extract` return visible text + element table; the host structures it |
| recover when stuck | stops `blocked` | escalation contract with candidates; host decides |
| integrate with an agent | none | MCP stdio server + CLI + install helpers |

## Measured baselines (2026-09-18, this machine, OpenRouter)

| task | jev-ultrafast as shipped | notes |
|---|---|---|
| Wikipedia: open the Gödel incompleteness article | 4,274 ms, 6 steps | repo claims 2,798 ms direct |
| Google Flights ZRH→LON one-way, verified 7 checks | 17,197 ms, ~17 decisions + 2 text calls | repo claims 7,073 ms direct |
| Olive Young category page: scroll + click "신상품순" | 5,342 ms, 2 decisions | sort bar was below the 780 px viewport |
| one Jev decision | median 315 ms (n=5) | +~140 ms vs direct TypeSafe |
| one text-helper call (mercury-2.5) | 675-938 ms (n=5) | removed from the loop in jev-ra |

Targets for v0.1: Wikipedia task ≤ 4 s, Flights ≤ 12 s through OpenRouter with `values` supplied, zero text-model calls in either. `jev-ra bench` reports these.

## Dependencies

| package | why | license |
|---|---|---|
| `browser-harness[mcp]` (browser-use org, MIT, 17k★) | daemon + one CDP websocket to a real Chrome (`ensure_daemon`, `cdp`); pins `mcp==2.1.1` under the `mcp` extra | MIT |
| `mcp` (official SDK, v2) | `MCPServer`, `@mcp.tool()`, `mcp.run()` stdio | MIT |
| `httpx[http2]` | Jev requests; HTTP/2 keep-alive matters at ~300 ms budgets | BSD |

`snapshot.js` is adapted from jev-ultrafast (MIT, Copyright 2026 Browser Use). Keep the copyright line in the file header and in `THIRD_PARTY_NOTICES.md`.

No other runtime deps. Python >= 3.12.

## Jev transport

| | TypeSafe direct | OpenRouter |
|---|---|---|
| URL | `https://api.typesafe.ai/v1/systemone` | `https://openrouter.ai/api/alpha/decisions` |
| model | `jev-latest` | `typesafe/jev-1.13` |
| key env | `TYPESAFE_API_KEY` | `OPENROUTER_API_KEY` |

Request `{"model", "state", "questions"}`; response `{"model", "answers", "usage"}`. OpenRouter validates `instructions` as a string and every `criteria` value as a string (noul `{true,false}`, choice `{name: text}`, score `[text]`), so the action-space builder renders criteria as strings always; the same body works on both endpoints. Answers: noul → `noul`; choice → `choice`, `confidence`, `probabilities`; score → `score`, `confidence`, `probabilities`, `legend`. Reject any response missing an asked answer or with probabilities that do not sum to 1±0.02 or whose `choice` is not the argmax.

Key resolution: `JEV_RA_API_KEY` → `TYPESAFE_API_KEY` → `OPENROUTER_API_KEY`. A key starting `sk-or-` selects OpenRouter unless `JEV_RA_ENDPOINT`/`JEV_RA_MODEL` say otherwise.

## Browser core (`jev_ra/browser/`)

One `Session` = one CDP target attached through browser-harness. Viewport 1280×900 (jev-ultrafast used 1120×780 and the Olive Young sort bar fell outside it). Focus emulation on so background tabs keep rendering. `BU_CDP_URL` (dedicated automation Chrome on a non-default profile) is passed through; `jev-ra doctor` explains how to start one.

`observe()` runs `snapshot.js` in one `Runtime.evaluate` and returns a `Page`:

```
url, title, w, h
text            visible text only, ≤ 6000 chars, DOM order
elements[]      {ref:"e12", node, role, label, value?, checked?, selected?, expanded?, rect}
actions[]       {id:"e12", kind: click|fill|select, node, label, value?, current_value?}  (+ scroll_down/scroll_up/wait)
marker          semantic fingerprint (url, scroll, viewport, title, text, actions minus geometry, safe field values)
page_key        identity + field state used by act-time guards
guards{node}    per-element identity/role/name/value/state/href/scope-text snapshot
omitted         count of controls beyond the 250 cap
```

`act(action, page, text=None)` re-checks freshness immediately before input: for click/select the target's guard must equal the observed one; otherwise the page marker must match. Geometry is re-resolved and hit-tested at act time; a covered control raises `StalePage`. Inputs are trusted CDP events (`Input.dispatchMouseEvent`, `Input.insertText`, key presses), never JS clicks. After fill into a combobox, wait for visible `[role=option]` ≤ 200 ms; other inputs wait 2 frames or 50 ms. `scroll` is a wheel event of ±560 px. `wait` sleeps 100 ms then re-observes. `press(key)` for Enter/Escape/Tab is new in jev-ra.

Model output never becomes a selector, coordinates, or JavaScript. Every executed target is resolved from an observed node id.

## Decision (`jev_ra/decide/`)

One request per step. Questions (all in the same request):

| id | type | what |
|---|---|---|
| `operation` | choice | CLICK / TYPE_TEXT / SELECT (only if targets exist) + SCROLL_DOWN / SCROLL_UP / WAIT (only if offered) + DONE / BLOCKED. Instructions = `NEXT_ACTION` |
| `click_target`, `type_text_target`, `select_target` | choice | one per offered operation; criteria = `"[e12] role label · value"` strings. Instructions = `TARGET` |
| `value_for_field` | choice | only when `values` were supplied and TYPE_TEXT is offered: criteria = one entry per provided value (`"name: preview"`) + `"none"`. Binds field↔value in the same pass |
| `prev_ok` | noul | "Did the previous action have its intended effect on this page?" Only when history is non-empty |
| `goal_achieved` | noul | "Is every requirement of the goal visibly satisfied on this page?" |

`NEXT_ACTION` and `TARGET` instruction texts are taken verbatim from jev-ultrafast `questions.py`; they were measured there. Do not reword without a benchmark.

State sent: `{page: {url, title, text}, elements: [...], recent_actions: last 10 {action, kind, text, page_changed}, goal, values_available: [names]}`. Never the full file bodies; never the screenshot.

Verdict rules:
- `operation.choice` must be an offered option, its target must be an offered index; else one corrective re-ask with the invalid combo removed, then escalate `invalid_decision`.
- Deterministic verification overrides `prev_ok`: after each act, compare url/title/text/field values before vs after. `page_changed = marker differs`. `prev_ok` is only a tie-breaker for loop detection.
- Loop detection: 3 consecutive non-wait actions with `page_changed == False` → escalate `stuck_loop`. Same (operation,target) chosen 3× in a row → `stuck_loop`.
- `DONE` requires `goal_achieved >= 0.6` in the same answer set, else treated as low confidence → one more step, then escalate `unverified_done`.
- Budgets: `max_steps` default 40, `max_decisions` 80, wall clock `timeout_s` 120.

## Values and text (`jev_ra/text.py`)

TYPE_TEXT needs a string. Order:
1. `values` supplied by the host: Jev's `value_for_field` picks one (or `none`). Picked → type it, mark the value used.
2. Nothing fits and a text helper is configured (`JEV_RA_TEXT_MODEL`, OpenAI-compatible, same contract as jev-ultrafast: JSON `{"text": ...}`, must parse, ≤ 2000 chars) → call it, record latency.
3. Otherwise → escalate `needs_value` with the field label, role, current value and the goal. The host supplies `values` and calls again.

The default install has no text model. That is the point.

## Agent loop (`jev_ra/agent.py`)

```
run(goal, values={}, max_steps=40) -> Result
  observe → (repeat) decide → freshness check → act → post-act wait → observe → verify → status
```
`Result`: `{status: done|blocked|escalate|budget, reason, url, title, steps: [{n, operation, target_label, text?, probability, confidence, latency_ms, page_changed, url}], decisions, text_calls, elapsed_ms, cost, final_page: {text, elements} }`.

Escalation payload adds `candidates`: the top 8 `operation`/target pairs by probability with labels, plus `page.text` (≤ 3000 chars) so the host can decide without another observe.

Single-step API: `act(instruction)` = one decide+act with `goal = instruction`; `click(ref)`, `type(ref, text)`, `select(ref, option)`, `scroll(dir)`, `press(key)`, `wait()` = direct, no Jev call.

## Extraction (`jev_ra/extract.py`)

No model. `extract(mode="text"|"elements"|"links"|"tables"|"main")` returns structured JSON from the DOM: visible text with headings kept as `#`, links `{text, href}`, tables as rows of cells, `main` = the largest visible text block's container as markdown-ish text. The host LLM turns that into the schema it wants. Cap 20 000 chars, note truncation.

## MCP server (`jev_ra/mcp_server.py`)

`MCPServer("jev-ra")`, stdio. One `Session` per server process, lazily opened, reused across calls; `browser_close` ends it. Tools (names are the contract; keep them stable):

| tool | args | returns |
|---|---|---|
| `browser_open` | `url` | page summary (url, title, text ≤ 1500, element count) |
| `browser_run` | `goal`, `values?`, `max_steps?` | `Result` (see above) |
| `browser_act` | `instruction` | one step result |
| `browser_observe` | `max_elements?` | element table `[ref] role label · value` + text ≤ 3000 |
| `browser_extract` | `mode` | extraction JSON |
| `browser_click` / `browser_type` / `browser_select` / `browser_scroll` / `browser_press` / `browser_wait` | `ref`, `text`/`option`/`direction`/`key` | page summary after the action |
| `browser_screenshot` | | `Image` (JPEG, viewport) |
| `browser_close` | | ok |

Every tool response includes `elapsed_ms` and, when Jev was called, `decisions` and `cost`. Errors raise `ToolError` with a one-line reason; a `StalePage` inside `browser_run` is retried internally (re-observe, re-decide) up to 3× before escalating `stale`.

## CLI (`jev_ra/cli.py`)

```
jev-ra run URL "goal" [--value name=text ...] [--max-steps N] [--json]
jev-ra open URL | observe | extract [--mode m] | act "instruction" | click REF | type REF TEXT | select REF OPTION
jev-ra scroll down|up | press KEY | screenshot [PATH] | close
jev-ra mcp                          start the stdio server
jev-ra install claude [--scope user|project|local] | codex     shell out to `claude mcp add` / `codex mcp add`; print the command if the binary is missing
jev-ra doctor                       key, endpoint, chrome connection, one live decision with latency
jev-ra bench [--live]               offline fixtures always; --live runs Wikipedia + Flights and prints ms/decisions/cost
```
Stateful subcommands (`open`…`close`) share a session through browser-harness's daemon and a target id kept in `$XDG_STATE_HOME/jev-ra/session.json`.

Install commands to emit:
```
claude mcp add jev-ra -s <scope> -e OPENROUTER_API_KEY=<from env> -- jev-ra mcp
codex  mcp add jev-ra --env OPENROUTER_API_KEY=<from env> -- jev-ra mcp
```
Never print the key; pass it through from the environment the user already has, and say which variable was used.

## Package layout

```
jev_ra/
  __init__.py        __version__, Agent, Session
  config.py          env + config.json (XDG) → Config(endpoint, model, api_key, text_model*, viewport, budgets)
  browser/
    session.py       Session: open/observe/act/press/screenshot/close, freshness guards, waits
    snapshot.js      adapted from jev-ultrafast (header keeps the MIT notice)
    actions.py       action-space builder: elements, per-operation targets, controls
  decide/
    client.py        decide(): httpx POST, validation, JevError hierarchy
    questions.py     NEXT_ACTION, TARGET, PREV_OK, GOAL_ACHIEVED, VALUE_FOR_FIELD (data only)
    policy.py        build_questions(page, goal, history, values) / read_answers() → Decision
  text.py            value binding + optional helper
  agent.py           the loop, verification, loop detection, escalation, Result
  extract.py         DOM → text/links/tables/main
  mcp_server.py      MCPServer + tools
  cli.py             argparse, session state file, install/doctor/bench
  bench/             offline fixture pages (HTML) + live task definitions
tests/
  fixtures/*.html    local pages for browser tests (served by http.server on 127.0.0.1)
  test_*.py
scripts/check_guards.py   real-browser guard checks, no model calls (port of jev-ultrafast's)
```

Invariants tests pin:
- No Jev call without a valid key; no network in unit tests (`decide` faked; `urllib`/`httpx` patched in `test_client`).
- Criteria sent to Jev are strings only; every `choice` answer is validated against the offered ids.
- An action is executed only if the guard captured at observe time still matches at act time.
- Three no-change actions → `stuck_loop`; `DONE` without `goal_achieved >= 0.6` → not done.
- `browser_run` never types without either a host value or a configured helper; otherwise `needs_value`.
- `extract` output never exceeds 20 000 chars and reports truncation.
- Browser tests are marked `browser` and skipped when no Chrome is reachable; CI runs them with a headless Chrome and `BU_CDP_URL`.

## Non-goals for v0.1

Shadow roots, iframes, canvas, file upload, pop-up windows, multi-tab workflows, auth flows, CAPTCHA, stealth. Say so in the README.

## Open questions (do not block)

- Whether OpenRouter's `session_id` improves anything; send it, measure later.
- `press(key)` inside a combobox may race the suggestion wait; keep the same 200 ms cap.
- Whether the 250-control cap needs the jev-browser style chunk-and-shortlist for very long pages; escalate `too_many_controls` for now.
