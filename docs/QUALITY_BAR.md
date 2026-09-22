# The quality bar

What "finished" means for jev-ra, as checks. A release is cut only when every row is green, and
the row names the command that proves it. Rows without a command yet are debt, listed at the end.

## Correctness

| check | proves | command |
|---|---|---|
| corpus ≥ 95 % on possible tasks, 3 runs, tagged commit | it does the job on real sites | `uv run jev-ra corpus run --runs 3` |
| every `expect = escalate:*` task escalates with that reason 3/3 | it refuses instead of guessing | same run, `failures by reason` empty for those |
| no invented input: zero TYPE_TEXT with text not in `values` across the corpus | the core contract | `scripts/check_no_invented_input.py corpus/results/<date>.jsonl` |
| browser-use on the same corpus, same judge, published next to ours | the comparison is honest | `scripts/bu_corpus.py` |
| offline fixture bench: every fixture passes | regressions are caught without the web | `uv run jev-ra bench` |

## Robustness

| check | proves | command |
|---|---|---|
| Chrome killed mid-session: next `browser_open` succeeds, `browser_close` succeeds | recovery | `tests/test_mcp_recovery.py` |
| SIGTERM to the MCP server: no Chrome or daemon left that it started | no orphans | `tests/test_mcp_lifecycle.py` |
| 100 tool calls in a row on one server: RSS growth < 50 MB, tabs = 1 | no leaks | `scripts/soak.py --calls 100` |
| two clients, concurrent tool calls: no StalePage from the race, second gets `busy` | serialised | `tests/test_mcp_concurrency.py` |
| every CDP/HTTP call bounded; `browser_run` returns within `max_steps` x step budget + 10 s | no hang | `tests/test_budgets.py` |
| `javascript:`, `file:`, `data:` refused at open; `file:` only with opt-in | no local read | `tests/test_session_open_schemes.py` |
| cold start on a fresh Linux box with only the key set: `doctor` and `search` green | first run works | CI job `cold-start`, `CLEAN_INSTALL.md` |

## Error surface

| check | proves | command |
|---|---|---|
| every tool error carries a message and a `next_step`; none is `Error executing tool X` | actionable | `tests/test_mcp_errors.py` parametrised over every error class |
| every escalation reason in code appears in README, USAGE, AGENTS.md and the four translations | docs match | `tests/test_docs_consistency.py` |
| key never in stdout, stderr, logs, `--json`, error text, install argv display | secrets | `tests/test_redaction.py` |

## Observability

| check | proves | command |
|---|---|---|
| every result has `run_id`, per-step ms, decisions, cost | billable and debuggable | `tests/test_result_shape.py` |
| `JEV_RA_LOG_LEVEL=DEBUG` explains a `stuck_loop` (which choices repeated) | post-mortem | `tests/test_logging.py` |
| `jev-ra trace <run_id>` renders the run's steps as the site's demo does | shareable | `tests/test_trace.py` |

## Performance

| check | proves | command |
|---|---|---|
| three recorded tasks, 5-run median: ≤ 1.5 / 5.0 / 2.0 s | the next 2x | `uv run jev-ra bench --live --runs 5` |
| corpus wall per decision, median ≤ 0.7 s | waits are earned | corpus rows |
| decision request size: element table ≤ 250 rows, state ≤ 12 KB | payload bounded | `tests/test_state_size.py` |
| Python overhead per step ≤ 5 % of step wall | no language rewrite needed | `uv run jev-ra profile` |

## Delivery

| check | proves | command |
|---|---|---|
| `uvx jev-ra@<tag> doctor` and `npx -y jev-ra@<tag> doctor` green within 10 min of the tag | release works | release.yml smoke job after publish |
| PyPI trusted publishing succeeds (no token upload) | automated | release.yml `pypi` job |
| sdist < 400 KB, wheel < 150 KB | lean | `tests/test_packaging.py` |
| CI green on 3.12/3.13/3.14 x ubuntu, plus macOS cold start | platforms | `ci.yml` matrix |
| Windows: `doctor` green on a windows-latest runner | claimed platforms are tested | `ci.yml` job `windows` |
| every public function has a docstring; ruff D rules on | reads as a product | `uv run ruff check .` |
| coverage ≥ 90 % without a browser, ≥ 95 % with one | tests mean something | `uv run pytest -q` |

## Product

| check | proves | command |
|---|---|---|
| landing page: demo replays a real run, four languages, no dead link | first impression | `scripts/check_site.py` |
| README install commands verified in CI against the published package | docs are true | release smoke job |
| `jev-ra serve`: HTTP+SSE, API key, per-key quota, structured logs | sellable | `tests/test_serve.py` |
| named profiles keep a login across runs | login once | `tests/test_profiles.py` |
| container image: `docker run jev-ra doctor` green | hosted | `Dockerfile`, CI job `image` |

## Debt (no command yet)

- `scripts/check_no_invented_input.py`, `scripts/soak.py`, `jev-ra trace`, `jev-ra serve`,
  profiles, Dockerfile, Windows job, macOS cold-start job, `scripts/check_site.py`.
