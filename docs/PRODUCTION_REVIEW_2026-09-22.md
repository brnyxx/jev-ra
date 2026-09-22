# Production review, 2026-09-22 (0.1.3)

Two passes on the published 0.1.3: a cold real-user run from an empty HOME against PyPI and npm,
and a read-only code audit. Everything below was observed, not inferred; the command or file is
named.

## Verdict

Usable today as one developer's daily driver. Not yet something a team can depend on. What
separates the two is not a missing feature; it is recovery after a failure and being able to
explain a run afterwards. The four items marked blocker are each tens of lines.

## What worked, observed

| check | result |
|---|---|
| cold first run, empty HOME, `uvx --from jev-ra==0.1.3 jev-ra doctor` | Chrome launched on its own profile, decision DONE in 621 ms, 28 s wall including the uv install |
| `run` Wikipedia with a value | done, goal_achieved, 2 steps, 4 decisions, 8.7 s, $0.0011, nothing on stderr |
| `search` "python 3.12 release date" | 3 pages in 3.2 s, python.org first |
| `run` on a form with no value supplied | escalate needs_value in 1.2 s with the field as first candidate |
| `run` on github.com/login | escalate needs_value, the username field first |
| TypeSafe direct route with `TYPESAFE_API_KEY` | DONE in 665 ms via jev-1.13.0 |
| MCP server stdout | only JSON-RPC lines; stderr empty; no key in either |
| two `doctor` at once on one profile | both reuse the same Chrome |
| the API key on disk after all runs | none; the only `sk-or-` matches are the prefix check in config.py and the README example |
| bad `mode` to browser_extract | clean ToolError naming the five modes |

## Blockers

1. **Chrome death is permanent for the MCP server.** After `pkill` of the launched Chrome, every
   tool answers `Chrome refused ...: no close frame received` including `browser_open`, and
   `browser_close` raises `UnexpectedToolError` and keeps the dead session. Cause, two places:
   `chrome.ensure()` writes `BU_CDP_URL` into `os.environ` after a launch and then trusts it
   forever without an `alive()` check (jev_ra/browser/chrome.py:263-284); `Browser.close()`
   sets `self.session = None` only after `session.close()` succeeds (jev_ra/mcp_server.py:81-88).
   Fix: probe a configured url the same way a remembered port is probed and drop it when dead;
   `close()` in `try/finally`; on `ChromeError` from any tool, drop the session so the next
   `browser_open` starts over.
2. **`browser_open` and `browser_close` run outside `guarded`.** `Session()` construction errors
   (no Chrome, daemon blocked, HOME too long) reach the client as `Error executing tool
   browser_open` with the message discarded by the SDK's `UnexpectedToolError`. Fix: wrap
   `browser.open()` and `browser.close()` in `guarded` (jev_ra/mcp_server.py:135-140, 247-253).
3. **No URL scheme check.** `browser_open("file:///...")` reads a local file and `build_state`
   posts its text to the decision endpoint (verified with a fake credentials file). `javascript:`
   URLs hang `open()` for 19 s before a timeout. Fix: allow `http`, `https`, `about:blank` at
   `Session.open()`; refuse the rest with a `JevRaError`; `JEV_RA_ALLOW_FILE_URLS=1` opts in.
4. **MCP tools run concurrently on one Session.** mcp 2.1.1 dispatches sync tool bodies through
   `anyio.to_thread`; two observers were measured on the shared session at once. `Session` has no
   lock and four pieces of shared state; a client that times out and retries gets two runs on one
   browser. Fix: one `threading.RLock` on `Browser`, held for every tool body.

## Should fix

5. `browser_search` on the shared MCP session blocks images for the rest of the session
   (jev_ra/search.py:143-155 vs the warning at jev_ra/browser/session.py:124-127) and navigates
   the user's tab to the SERP. Run it on its own target.
6. A provider failure (401, network) escalates as `budget` (jev_ra/agent.py:130-135), and
   AGENTS.md tells the host to narrow the goal and retry. Add a `provider_error` reason and say
   "check the key, do not retry". Real budget exhaustion returns `status: "budget"`, which
   AGENTS.md lists as if it were an escalation reason.
7. Nothing reaps what jev-ra starts. `launch()` drops the `Popen` with `start_new_session=True`;
   `mcp_server.main()` has no `finally` and no SIGTERM handler. On this machine: 8
   browser-harness daemons (five 3 days old), 11 Chromes, a 678 MB profile with no size cap. Add
   `finally: browser.close()`, a SIGTERM handler, and `jev-ra clean`.
8. The MCP server pins root logging at WARNING (jev_ra/mcp_server.py:260) with no override, so the
   lines that explain a `stuck_loop` never appear. No run id reaches the caller although
   `DecisionClient.session_id` exists. Add `JEV_RA_LOG_LEVEL` and put the session id in `Result`.
9. `ref` drift: direct tools re-observe and match `e12` in the new observation, not the one the
   caller saw (jev_ra/agent.py:276-279). Return a `page_key` from observe and let direct tools
   check it.
10. `browser_press` bypasses the focus check that `submit()` does for decided presses
    (jev_ra/agent.py:271-274).
11. `install` passes the key in the child argv and the agent stores it in plain text; SECURITY.md
    should say so. `subprocess.run` there has no timeout.
12. No caps on `max_pages`, `max_elements`, or `values` size at the tool boundary.
13. `Session.__init__` leaks a target when a later CDP call fails (jev_ra/browser/session.py:229-243).
14. `ValueBinder.close()` is never called; `Page.navigate` is in the retry list and can fire twice.
15. CI sets `BU_CDP_URL` at job level, so `launch`/`wait_for_port`/`ready` never run against a
    real browser in CI, and only on ubuntu.
16. Packaging: sdist is 3 MB, 73 % brand assets; browser-harness pins five deps with `==`, so a
    shared `pip install` next to another MCP package may not resolve; the npm launcher re-checks
    `uv` on a PATH that has not changed after installing it, and spawns bare `uvx` rather than
    the path it found.

## Also observed

- A run that reaches a page with only anchor links can walk off-site: the recovery run on
  example.com followed "Learn more" into IANA and RFC pages and ended `stuck_loop` after 11
  decisions. The loop detector worked; a same-origin preference for CLICK would have ended it
  sooner.
- `browser_search` returned the same python.org URL three times. Deduplicate by URL.
