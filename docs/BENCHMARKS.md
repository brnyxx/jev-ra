# Benchmarks

Everything here was measured on one machine on 2026-09-18. No number is estimated. A run that
finishes without doing the task counts as a failure, not as a time.

## Method

- **Machine and browser**: one dedicated Chrome 153 on a non-default profile, remote debugging on
  `http://127.0.0.1:9222`, 1280×900 viewport. Both sides drive the same browser.
- **Route**: every model call goes through OpenRouter. jev-ra uses `typesafe/jev-1.13`; browser-use
  uses the driver model named in each column.
- **browser-use**: 0.13.10, `use_vision=False`, `max_steps=25`, 240 s timeout per task. Wall time is
  measured around `agent.run()` and includes the CDP connect.
- **jev-ra**: `jev-ra bench --live --runs 5`. Wall time is measured around `Agent.run()` and includes
  the first navigation.
- **Verification**: every run is checked against the page it left behind, not against the agent's own
  opinion. Wikipedia = the article URL; Flights = a submitted one-way search whose results page names
  both cities, the date, a duration and a price, in whatever language it came back in; Olive Young =
  `prdSort=02` in the URL or the 신상품순 tab marked active; search = a page containing the year and a
  URL to cite; form fill = the confirmation carrying every typed value. Predicates:
  [`jev_ra/bench/verify.py`](../jev_ra/bench/verify.py).
- **Acceptance for v0.1**: ≥ 3× the `flash_mode` column on every task that has one, with every run
  verified and zero text-model calls.

## Results, 5 runs per task

| task | jev-ra median | p90 | success | steps | decisions | cost | browser-use `flash_mode` | ratio |
|---|---|---|---|---|---|---|---|---|
| Wikipedia: open the Gödel incompleteness article | **2,714 ms** | 3,179 ms | 5/5 | 2 | 3 | $0.00075 | 23,058 ms | **8.50×** |
| Google Flights ZRH→LON one-way 2026-09-20 | **8,888 ms** | 10,573 ms | 5/5 | 11 | 14 | $0.00317 | 66,414 ms | **7.47×** |
| Olive Young category: sort by 신상품순 | **3,806 ms** | 4,858 ms | 5/5 | 2 | 4 | $0.00204 | 15,071 ms | **3.96×** |
| Search: what year was Python 3.12 released, with a citation | **2,416 ms** | 2,571 ms | 5/5 | 3 | 4 | $0.00035 | no row | - |
| Local checkout form, values supplied by the host | **2,191 ms** | 2,338 ms | 5/5 | 4 | 5 | $0.00049 | no row | - |

Text-model calls across all 25 runs: **0**.

Offline, decisions scripted and no network at all, 5 runs each:

| fixture task | median | p90 | steps |
|---|---|---|---|
| form fill (type, type, select, submit) | 916 ms | 1,037 ms | 4 |
| catalog sort (scroll, click) | 470 ms | 490 ms | 2 |

Raw rows: [`2026-09-18-v0.1/`](benchmarks/2026-09-18-v0.1/).

## browser-use re-run through the same harness, 5 runs

The same script, the same Chrome, the same day, five runs per task
([raw rows](benchmarks/2026-09-18-v0.1/results_google_gemini-3-flash-preview_flash.jsonl)):

| task | browser-use `flash_mode` median | p90 | fastest | slowest | jev-ra median | ratio |
|---|---|---|---|---|---|---|
| Wikipedia | 24,618 ms | 35,635 ms | 15,759 ms | 35,635 ms | 2,714 ms | 9.07× |
| Google Flights | 73,842 ms | 83,086 ms | 49,914 ms | 83,086 ms | 8,888 ms | 8.31× |
| Olive Young sort | 27,617 ms | 70,840 ms | 17,647 ms | 70,840 ms | 3,806 ms | 7.26× |

Completion here is browser-use's own `is_done`, not our predicates, so these rows are generous to it.
The ratios in the results table above deliberately use the **single recorded run** instead, which is
faster for browser-use on every task and therefore the more conservative comparison.

## The recorded browser-use baseline

One run per cell, the original measurement
([raw rows](benchmarks/2026-09-18-browser-use-baseline/)):

| task | gemini-3-flash | gemini-3-flash `flash_mode` | gpt-5-mini |
|---|---|---|---|
| Wikipedia | 46,461 ms · 5 steps | 23,058 ms · 4 steps | 100,399 ms · 11 steps |
| Google Flights | 63,565 ms · 11 steps | 66,414 ms · 11 steps | 238,045 ms · 25 steps, budget hit |
| Olive Young sort | 17,493 ms · 3 steps | 15,071 ms · 3 steps | timeout at 240 s |

claude-sonnet-5 could not drive browser-use through OpenRouter at all: its structured-output schema
was rejected with `compiled grammar is too large`. Its row is kept in the raw data and excluded from
every ratio. The gpt-5-mini Flights row hit the step budget and its final URL is not a verified
one-way search. The `flash_mode` column is the one the ratios use, because it is browser-use's own
fast mode and therefore the fairest comparison.

## Where the time goes

`jev-ra bench --live --profile` times every step by category. Two runs of all five tasks,
2026-09-18, 52 s of wall clock in total:

| category | ms | share | what it is |
|---|---|---|---|
| wait | 15,917 | 30.6 % | the post-action settle: two frames, up to 200 ms for a combobox, then up to 600 ms waiting for two page markers to agree |
| decide | 11,428 | 22.0 % | the HTTP round trip to Jev |
| act | 2,839 | 5.5 % | CDP input: resolve, hit-test, dispatch |
| snapshot | 1,644 | 3.2 % | the one `Runtime.evaluate` that reads the page |
| actions | 0 | 0.0 % | Python building the action space and the question set |
| overhead | 11 | 0.0 % | everything else in Python, per step |
| outside steps | 20,116 | 38.7 % | the first navigation, the terminal decision that produces no step, and the search task, whose work is not step-shaped |

Every `Result.steps[i]` carries the same six fields, and they sum to that step's `total_ms`.

### The decision rule for a rewrite

**Rewrite a hot path in another language only if `overhead_ms + actions_ms` exceeds 10 % of wall time
on the corpus.** Measured here it is **0.02 %**: eleven milliseconds of Python across two full runs
of five tasks. A faster language would be optimising something that does not exist.

The levers that do exist, in the order they are worth pulling:

1. **Decision count.** Each decision is ~300-500 ms of `decide`, and every avoided round trip also
   avoids a `wait` and a `snapshot`. This is why the operation, the target and the value are settled
   in one request rather than three.
2. **Network.** The direct TypeSafe endpoint is roughly 140 ms per decision faster than OpenRouter by
   the upstream measurements; HTTP/2 keep-alive is already on, and the state sent is the element
   table and the visible text rather than the HTML.
3. **Wait caps.** `wait` is the largest measured category. The 600 ms quiescence budget is a ceiling,
   not a cost: it returns as soon as two markers agree. Lowering it trades reliability on
   single-page apps for latency, which is the trade that made Google Flights answer `BLOCKED`
   before.

## The real-site corpus, 3 runs per task

`corpus/sites.toml` holds 40 tasks across eight families (e-commerce, search and reading, booking,
forms, news, documentation SPAs, government portals, login walls), each with an `expect` and a
`verify` spec. `uv run jev-ra corpus run --runs 3` runs all of them against the live web.

Measured 2026-09-18 on main `03973c6` (raw rows: `docs/benchmarks/2026-09-18-v0.1/corpus-3runs.jsonl`):

| family | pass / 15 |
|---|---|
| auth | 15 |
| forms | 13 |
| portal | 13 |
| search_read | 12 |
| booking | 12 |
| ecommerce | 11 |
| news | 11 |
| docs_spa | 10 |
| **all** | **97 / 120 = 81 %** |

What the 23 failing attempts were: `blocked` on a page the run could not progress on (11: an
Olive Young category menu that opens on hover only, a Google Flights control that does not exist
before a search, gov.kr and GitHub on 2 of 3 runs each, Vercel docs once); verify specs stricter
than the page (10: an MDN url compared case-sensitively, `What's New` typeset with a curly
apostrophe, a BBC article whose visible text was measured only inside the viewport); one Amazon
search url check; one unverified done on Yonhap. The ten spec cases are fixed by commits after
`03973c6` (`e12e260`, `8081f5d`, `aea70e3`, `437027e`); the two impossible tasks were replaced in
`8f0c388` by tasks the same pages can answer. Neither is counted above: the table is the run as it
happened.

The 0.1.0 bar is this measurement, published. The 0.2 bar is 90 % on the corpus as it stands
today, re-measured on a tagged commit.

## Cost and latency per call

| measurement | value |
|---|---|
| one Jev decision, OpenRouter | 274-508 ms across runs |
| cheapest task end to end | $0.00035 (search, 4 decisions) |
| dearest task end to end | $0.00317 (Flights, 14 decisions) |
| text-model calls | 0 |

Cost scales with decisions, not with page size: the state sent is the element table and the visible
text, never the HTML.

## Reproducing

```sh
export OPENROUTER_API_KEY=sk-or-...
export BU_CDP_URL=http://127.0.0.1:9222     # or let jev-ra launch its own Chrome
uvx jev-ra bench                            # offline fixtures, no network, no key needed
uvx jev-ra bench --live --runs 5            # the table above, with PASS/FAIL per task
```

The browser-use side needs its own environment, because browser-use is not a dependency of jev-ra.
`jev-ra bench --live --runs 5 --baseline` builds one with `uv` and runs it; it copies the recorded
script into the output directory first, so the historical rows are never appended to.

## Recording a side-by-side video

```sh
uv run python scripts/record_bench.py wikipedia --out docs/recordings
uv run python scripts/render_side_by_side.py docs/recordings/wikipedia/jev-ra \
  --out assets/demo/wikipedia --fps 8 --width 480
```

`render_side_by_side.py` accepts several recording directories and lays them out as columns with a
running clock each, at 1× speed. It writes a GIF always, and an MP4 as well when ffmpeg is on PATH.
