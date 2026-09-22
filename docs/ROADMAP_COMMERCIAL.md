# From open-source 0.1 to a product people pay for

Written 2026-09-22 against 0.1.3. Every number below is measured on this repo; the method and raw
rows are in `docs/BENCHMARKS.md` and `docs/benchmarks/`. Targets are set so that each one is
checked by a command in CI or by the corpus, never by a claim.

## Where 0.1.3 stands

| axis | jev-ra 0.1.3 | browser-use 0.13 flash | source |
|---|---|---|---|
| three recorded tasks, median wall | 2.7 / 8.9 / 3.8 s | 23.1 / 66.4 / 15.1 s | BENCHMARKS.md, 5 runs |
| real-site corpus, 40 tasks x 3 | 102 / 120 = 85 % | see below | corpus-3runs-f581761.jsonl |
| decision latency | 250-380 ms per step | one LLM call per step, 3-8 s | demo-run.json |
| cost per task | $0.0001-0.0033 | not measured | corpus rows |
| wall time per decision (all-in) | 1.14 s median | | corpus rows |

Where the 1.14 s per decision goes, from the recorded Flights run (10 steps, 12.0 s): decide
3.0 s, wait-for-page 3.7 s, act 1.0 s, snapshot 0.4 s. The model is a quarter of the time. The
next 2x is in how long jev-ra waits for a page to settle and how it verifies, not in Jev.

## What a paying customer needs that 0.1 does not have

Three things, in this order. Speed is already the headline; a buyer pays for the other two.

1. **It does not fail silently and it recovers.** 0.1.3 has four blockers
   (`docs/PRODUCTION_REVIEW_2026-09-22.md`): a dead Chrome is permanent for the MCP server, the
   two most common first errors reach the client with no message, `file://` is not refused, and
   tools run concurrently on one session with no lock.
2. **It is more reliable than the alternatives on real sites, and says so with numbers.** The
   corpus is the instrument. 85 % today; the bar for a product is 95 % on tasks that are
   possible, with every impossible task escalating for the right reason. browser-use's number on
   the same corpus, judged by the same specs, is the comparison that sells.
3. **It can be observed and billed.** Per-run id, per-step latency and cost, a log level that can
   be raised, a way to see why a run ended `stuck_loop` after the fact. Without this no team
   adopts it and no metered plan is possible.

## The program

Four tracks, run as parallel lanes, each with a measurable exit.

### Track A: hardening (0.1.4, this week)

Exit: the production review's blockers 1-4 and should-fix 5-8 closed, with a test for each that
fails on 0.1.3. A new CI job runs the cold-start path (no `BU_CDP_URL`) against a real Chrome.

- Session recovery: probe a remembered CDP url before trusting it; drop the session on
  `ChromeError`; `close()` always releases; SIGTERM handler; `jev-ra clean`.
- Error surface: `browser_open`/`browser_close` under `guarded`; every tool error carries
  `next_step`.
- Scheme allow-list at `Session.open()`; caps on `max_pages`, `max_elements`, `values`.
- One lock on the shared session; a run in progress refuses a second tool call with a clear
  reason instead of racing.
- `browser_search` on its own target; provider errors as `provider_error`, not `budget`.
- `JEV_RA_LOG_LEVEL`; `run_id` in every result; per-step timings already measured, exposed in the
  MCP payload.

### Track B: reliability to 95 % (0.2)

Exit: corpus ≥ 95 % on possible tasks over 3 runs on a tagged commit; the six needs_value and two
blocked tasks escalate correctly 3/3.

Known failure classes from the last run, in order of size:
- Sites that wall the machine after repeated runs (Coupang, Reuters, gov.kr): rotate a residential
  egress for the corpus runner, and add a `blocked_by_site` escalation reason so the product says
  "this site blocks automation" instead of "stuck".
- Booking loops (Google Flights one-way, Trainline): the model re-clicks a control that opened a
  panel it cannot see. Fix is in what jev-ra shows the model: mark the control as `expanded` and
  show the panel's controls first. Fixture-backed.
- Same-origin preference: a run that leaves the site is almost always wrong. Down-weight
  off-origin links unless the goal names another site.
- Verify-spec drift: two Seoul rows failed on a check tighter than the goal. Specs get reviewed
  with each corpus run, and the corpus grows to 80 tasks with a second language block (ja, zh).

### Track C: the next 2x (0.2)

Exit: three recorded tasks median ≤ 1.5 / 5 / 2 s; corpus median wall per decision ≤ 0.7 s; no
task regresses on pass rate.

- Settle detection by mutation, not by polling: `MutationObserver` + `requestAnimationFrame`
  quiescence instead of the fixed `PAINT_BUDGET_S` and `WAIT_SLEEP_S` loops. The 3.7 s of waits
  in the Flights run are mostly budget, not need.
- Speculative snapshot: take the post-action snapshot on the same CDP round trip as the action's
  verification, so act + observe is one message.
- Decision prefetch: while the page settles, send Jev the last observation with the pending
  action marked, so the next decision is ready when the page is (only when the page did not
  navigate).
- Element table diff: send Jev only the rows that changed since the last step when the page did
  not navigate. Smaller request, same answer.
- Measure every change on the corpus before merging. Speed that costs a task is rejected.

### Track D: product surface (0.2 to 0.3)

Exit: a hosted endpoint and a metered plan a customer can sign up for without talking to us.

- `jev-ra serve`: HTTP + SSE alongside stdio, API-key auth, per-key quotas, structured JSON logs,
  OpenTelemetry traces (run id = trace id).
- Session persistence: named profiles with cookies kept across runs so a logged-in site stays
  logged in; the login wall becomes a one-time human step.
- Hosted browsers: a container image with Chrome and the daemon, one browser per session, so the
  customer never installs Chrome.
- A results page per run: the timeline the site's demo already draws, generated from the
  run's own log, shareable by link.
- Pricing: per decision (we already know the cost to the cent), with a free tier the corpus
  runner itself can live on.

## What "much better than browser-use and other AI browsers" has to mean

Faster is proven and will widen (Track C). The claims a buyer will test are the other two:

- **Reliability on the same tasks, judged the same way.** `scripts/bu_corpus.py` runs
  browser-use on this corpus with jev-ra's verify specs. Its result goes in BENCHMARKS.md next to
  ours, every release. On the first run browser-use invented a customer name and submitted the
  httpbin order; jev-ra escalated `needs_value`. That difference is the product.
- **No invented input, ever.** jev-ra types only what the host supplied. Competitors' agents fill
  forms with guesses. This is a contract we can put in a sales deck and a test can hold.
- **Cost per task an order of magnitude lower**, because one Jev decision is $0.00025 and there
  is no planning LLM inside.

## Not in scope until the above is green

Vision, multi-tab orchestration, a recorder that turns a run into a replayable script, Windows.
Each is real demand; none of them matters if a Chrome crash still takes the server down.
