# jev-ra for agents

You are a coding agent (Claude Code, Codex, Cursor, Cline, Devin, or any MCP client). This file tells you how to install jev-ra for the user, how to drive a browser with it, and when to take over. Read it fully once; then follow the section for your host.

jev-ra gives you a real Chrome through an MCP server. You send a goal; TypeSafe Jev picks the operation and the element for each step in ~300 ms; you get back a result or an escalation with candidates. You do the planning, you supply any text that must be typed, and you read the page through `browser_extract`. There is no second LLM inside jev-ra.

## Install for the user

Prerequisites: Python 3.12+ and `uv` (or Node 20+ for the npm launcher), Chrome/Chromium/Edge installed, and an API key in the environment: `OPENROUTER_API_KEY` (recommended, no TypeSafe account needed) or `TYPESAFE_API_KEY`.

Never print the key. Never write it into a file inside the repository. If it is missing, ask the user to export it and stop.

### Claude Code

```sh
uvx jev-ra install claude --scope user
uvx jev-ra doctor
```

`install` runs `claude mcp add jev-ra -s user -e OPENROUTER_API_KEY=... -- uvx jev-ra mcp` for the user, passing the key through from the environment. Restart Claude Code or open `/mcp` to confirm `jev-ra` is connected. If `claude` is not on PATH, `install` prints the exact command for the user to run.

### Codex

```sh
uvx jev-ra install codex
uvx jev-ra doctor
```

Codex asks the user to trust the new MCP server once (`/mcp` inside Codex). Do not try to bypass that prompt.

### npm launcher (no Python setup)

```sh
npx -y jev-ra install claude     # or: install codex
npx -y jev-ra doctor
```

The npm package is a launcher: it finds `uv`, offers to install it if it is missing (`--yes` skips
the question, `--no-install` refuses and exits 2), and runs `uvx --from jev-ra==<its version> jev-ra`
with every other argument passed through. The MCP server it registers is still `uvx jev-ra mcp`.

### Any other MCP client

Add this server definition to the client's MCP configuration:

```json
{ "mcpServers": { "jev-ra": { "command": "uvx", "args": ["jev-ra", "mcp"], "env": { "OPENROUTER_API_KEY": "${OPENROUTER_API_KEY}" } } } }
```

### Verify

`uvx jev-ra doctor` must end with a `decision: DONE in <n> ms via <model>` line: that is one live decision and its latency. If it prints `key: missing`, `chrome: unreachable`, or `decision: failed`, fix that first; the line names the next step. `--json` gives the same report as a payload. jev-ra launches its own Chrome on a dedicated profile if none is reachable; set `BU_CDP_URL=http://127.0.0.1:9222` to use one you started yourself.

## Drive the browser

Tools, in the order you usually need them:

| tool | when |
|---|---|
| `browser_search(query, goal, max_pages=3)` | you need to find something on the web. Returns ranked pages with extracted text and an `answers_goal` score each |
| `browser_open(url)` | you know the page |
| `browser_run(goal, values={}, max_steps=40)` | a multi-step task on the current page: sort, filter, fill, submit, paginate. Put every string that must be typed into `values` |
| `browser_extract(mode="text"\|"main"\|"links"\|"tables"\|"elements")` | read the page. You structure the result yourself |
| `browser_observe()` | see the element table (`[e12] button "Search"`) when you want to act step by step |
| `browser_act(instruction)` | one Jev-decided step for a narrow instruction |
| `browser_click(ref)`, `browser_type(ref, text)`, `browser_select(ref, option)`, `browser_scroll(direction)`, `browser_press(key)`, `browser_wait()` | direct steps, no Jev call |
| `browser_screenshot()` | only when text is not enough |
| `browser_close()` | when the task is over |

Rules that keep it fast and safe:

1. Give `browser_run` one concrete goal with a visible end state ("sort the list by newest, stop when the sort is applied"), not a vague one ("look around").
2. Put every value in `values`. jev-ra will not invent names, emails, dates or search strings; without a matching value it escalates `needs_value`.
3. Read with `browser_extract`, not with screenshots. Text is faster and you can quote it.
4. Do not ask for more than `max_steps` you need; 10-20 covers most tasks.
5. Never send the user's credentials in a goal. Login walls escalate; the user handles them in the browser jev-ra opened.

## When it escalates

`browser_run` returns `status: "escalate"` with `reason` and `candidates` (top operation/element pairs with labels and probabilities) and `page.text`. Handle by reason:

| reason | do |
|---|---|
| `needs_value` | supply the missing string in `values` and call `browser_run` again with the same goal |
| `stuck_loop` | the page is not changing. Read `page.text`, pick a candidate, use `browser_click(ref)` once, then continue with `browser_run` |
| `unverified_done` | Jev thinks it is done but could not verify. Check with `browser_extract`; if the end state is there, treat as done |
| `provider_error` | the decision provider would not answer (rejected key, dead connection). Check the key and the route with `jev-ra doctor`; do not retry the goal |
| `stale` | the page kept changing under it (animations, live feeds). Call `browser_wait()` then retry once |
| `budget` | steps or time ran out. Narrow the goal or split it |
| `too_many_controls` | more than 250 controls in view. Scroll or open the relevant section first, then retry |
| `blocked` | nothing on the page can progress (login, captcha, empty results). Tell the user what you see; do not retry blindly |
| `blocked_by_site` | the site served a wall instead of a page. Tell the user the site blocks automation; retrying from the same network will not help |
| `invalid_decision` | the model answered with something that is not on the page, twice. Re-observe and drive the step yourself with `browser_click` |

Report escalations to the user in one sentence with what you tried; do not loop more than twice on the same reason.

## Example session

```
browser_search(query="python 3.12 release date", goal="the exact release date with a citation")
→ 3 pages, best answers_goal 0.97: docs.python.org ... "Python 3.12.0 was released on October 2, 2023"

browser_open("https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100010014")
browser_run(goal="Sort the product list by 신상품순 (newest first). Stop when the sort is applied.")
→ 2 steps in 3.8 s; escalates unverified_done, and browser_extract confirms the sort is applied
browser_extract(mode="text")
→ product names, brands, prices; structure them for the user
```

## Cost

One Jev decision is about $0.00025 through OpenRouter, measured 2026-09-18: the whole Google Flights flow is 14 decisions for $0.0032, and a search with a citation is 4 decisions for $0.00035. Every tool response carries `decisions` and `cost`, and `--json` on any CLI command shows the same per-step latencies.
