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

Measured twice on 2026-09-18. First on main `03973c6` (raw rows:
`docs/benchmarks/2026-09-18-v0.1/corpus-3runs.jsonl`): 97 / 120 = 81 %. Then on main `f581761`,
after the fixes below (raw rows: `docs/benchmarks/2026-09-18-v0.1/corpus-3runs-f581761.jsonl`):

| family | pass / 15 |
|---|---|
| search_read | 15 |
| forms | 15 |
| auth | 15 |
| docs_spa | 14 |
| ecommerce | 12 |
| news | 12 |
| portal | 10 |
| booking | 9 |
| **all** | **102 / 120 = 85 %** |

What the 18 failing attempts on `f581761` were: `blocked` on a page the run could not progress
on (9: Coupang, Reuters and gov.kr on all 3 runs each; gov.kr answers every request from this
machine with a device ban after a day of corpus runs, Reuters and Coupang serve a wall at open);
`stuck_loop` on two booking sites (6: the Google Flights one-way search and the Trainline home
search); the Seoul notice check on 2 runs that opened 입찰공고, a 공고 list reachable from 서울소식
but not the `realmnews` list the check names; one React docs search whose page did not show
`useEffect`.

Between the two measurements: the first run's verify-spec failures (an MDN url compared
case-sensitively, `What's New` typeset with a curly apostrophe, a BBC article measured only inside
the viewport, the Amazon url case) were fixed, two impossible tasks were replaced in `8f0c388` by
tasks the same pages can answer, and the paint, scroll, wait and press paths were corrected one root
cause at a time (`af4247a..f581761`). GitHub's secondary rate limit, which blocked
`github_search_repo` for the lanes that fixed it, had lifted by the second run: 3 / 3.

The 0.1.0 bar is this measurement, published. The 0.2 bar is 90 % on the corpus as it stands
today, re-measured on a tagged commit. The two booking loops and the Seoul check are the open items.

## The same corpus, browser-use on the other side

 runs browser-use 0.13.10 (`flash_mode=True`, gemini-3-flash via OpenRouter,
`use_vision=False`, the fastest configuration in the recorded baseline) on the same 40 tasks and judges
every final page with the same `corpus.check` specs. One run per task on 2026-09-22 (raw rows:
`docs/benchmarks/2026-09-18-v0.1/browser-use-corpus-1run.jsonl`). browser-use closes its tab inside
`agent.run()`, so its page is judged from the text it extracted itself plus its final answer, which
favours it: a FAIL here is a FAIL by its own account.

| family | jev-ra (3 runs) | browser-use (1 run) |
|---|---|---|
| auth | 15 / 15 | 5 / 5 |
| booking | 9 / 15 | 2 / 5 |
| docs_spa | 14 / 15 | 4 / 5 |
| ecommerce | 12 / 15 | 5 / 5 |
| forms | 15 / 15 | 3 / 5 |
| news | 12 / 15 | 4 / 5 |
| portal | 10 / 15 | 2 / 5 |
| search_read | 15 / 15 | 4 / 5 |
| **all** | **102 / 120 = 85 %** | **29 / 40 = 72 %** |

Wall time on passing tasks, median: jev-ra 3.1 s, browser-use 19.4 s
(p90 5.7 s vs 35.3 s).

The difference that matters most is not in the totals. Two tasks hold back a value on purpose
(`httpbin_form_missing_value`, `file_upload_picker`): browser-use invented the missing input and
submitted; jev-ra escalated `needs_value` both times. One task cannot be done at all
(`canvas_drawing`, a canvas with no controls): browser-use reported success; jev-ra escalated
`blocked`. An agent that fills in a customer name it was never given, or says it drew on a canvas
it cannot see, is not a pass, whatever the page says afterwards.

Method notes, so the number can be trusted: 21 of the first pass's rows failed at browser-use's
`BrowserStartEvent` after 19 back-to-back sessions on one shared Chrome, a harness artefact, not an
agent failure; those tasks were rerun with a fresh Chrome per task and the reruns replace the broken
rows. The port 9333 first chosen for that Chrome was held by Docker on 127.0.0.1, so Chrome bound
IPv6 only; 9444 was used.

## The public benchmarks

jev-ra also runs on the task sets the field cites, through one adapter, judged by the harnesses
those benchmarks publish rather than by `corpus.check`. Method, exact commands, the pinned upstream
commits, what had to be worked around to run each judge at all, and where the trajectories are:
[`bench/public/README.md`](../bench/public/README.md).

| benchmark | before | after four fixes | judged by | scale |
|---|---|---|---|---|
| Online-Mind2Web | 3 / 10 = 30 % | 3 / 10 and 2 / 10 | WebJudge (o4-mini), the benchmark's own | 10 tasks, a smoke |
| WebVoyager | 3 / 10 and 0 / 10 | 4 / 10 and 3 / 10 | `evaluation/auto_eval.py`, the benchmark's own, on gpt-4o | 10 tasks, twice |

Ten tasks is a smoke, not a score: every pass is the same ten tasks, and two passes of the same
build differ by one to three of them, which is more than the gap between most leaderboard entries.
The published bars are 90.53 % on Online-Mind2Web (ABP + Claude Opus 4.6, human-evaluated, 285 of
300) and a saturated 99.19 % on WebVoyager.

The reruns followed four fixes the first pass had traced: a post-input settle on the plain call
budget (which failed `ArXiv--0` twice and now passes it twice), a browser that asked sites for the
machine's language, no final answer on a question-shaped task, and a site wall reported as a task
that failed. Only the settle moved a judged verdict and held it across both passes; carvana.com
still refuses the browser from this address and is now reported as `blocked_by_site` rather than
as an impossible task - the wall class `ROADMAP_COMMERCIAL.md` Track B names is unchanged.

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

## The corpus at 0.2.3, and what run-to-run noise looks like

Measured 2026-09-22 through the TypeSafe direct route (OpenRouter was out of credits), three runs
each, same eighty specs with the Flights date now written as `{today+30}`. Raw rows:
[`2026-09-22-v0.2/`](benchmarks/2026-09-22-v0.2/).

| tree | passed / 240 | possible tasks (walled sites excluded) |
|---|---|---|
| main `f26087c` (0.2.2 + the date placeholder) | 207 = 86.2 % | 207 / 234 = 88.5 % |
| candidate `1f87f60` (+ late-route wait, href-less anchors, date picker, route content) | 202 = 84.2 % | 202 / 234 = 86.3 % |

The five-task gap is not the code. The eight tasks that differed were rerun five times each on
both trees: amazon, hackernews, tailwind 5/5 on both; the two httpbin form tasks went 0/5 on main
and 5/5 on the candidate (httpbin.org answers with an error page for minutes at a time, which the
run reads as `blocked`); nhk 0/5 on both; react 2/5 against 1/5. So a single three-run pass moves
by about ±5 of 240 on site weather alone, and a change is only read as a gain or a loss when a
per-task rerun agrees. The three mechanisms in the candidate hold on their fixtures (late route
3/3, href-less anchors 2/2, date grid 2/2) and cost nothing on the corpus; the state-evidence
change tried in the same lane (`416273c` on `fix/decisions`) was left out because it turned
hackernews_page_two from 3/3 into 0/3 on every rerun.

Every row now also records the status the site answered its document with (`http_status`) and
whether the run hit a site error page (`site_error`), and the per-task table carries a `site`
column counting those attempts.

## 0.2.4: site weather, and the same machine for the speed check

Measured 2026-09-23 through the TypeSafe direct route (OpenRouter out of credits); decisions took
495-604 ms there. The 0.1 table was measured through OpenRouter on 2026-09-18 at 274-508 ms per
decision, on a different day and machine load, so the two routes have not been compared under the
same conditions and the gap is not attributed to either. Raw rows: [`2026-09-23-v0.2.4/`](benchmarks/2026-09-23-v0.2.4/).

Corpus, three runs, 83 tasks (the three httpbin forms now also run against httpbingo.org): 213 / 249.
On the 80 tasks shared with 0.2.3: 204 / 240 against 207 / 240, inside the ±5 run-to-run noise;
the one row the new site-error path produced is booking.com answering HTTP 502 twice, reported as
`blocked_by_site` instead of being decided on.

Recorded tasks, five runs each, 0.2.3 and this release back to back on the same machine:

| task | 0.2.3 | 0.2.4 |
|---|---|---|
| Wikipedia | 4,661 ms | 4,291 ms |
| Olive Young sort | 6,694 ms | 5,884 ms |
| Search with a citation | 2,250 ms | 2,267 ms |
| Form fill | 1,558 ms | 1,559 ms |
| Google Flights | 0/5 | 0/5 |

The release is not slower than the one before it. Google Flights fails on both and is open.

## 0.2.5: Google Flights and NHK pass again

Measured 2026-09-23 on the same machine and the same TypeSafe direct route as 0.2.4 (`jev-ra doctor`:
DONE in 575 ms via jev-1.13.0). Raw rows: [`2026-09-23-v0.2.5/`](benchmarks/2026-09-23-v0.2.5/).

Recorded tasks, five runs each, 0.2.4 and this release back to back:

| task | 0.2.4 | 0.2.5 |
|---|---|---|
| Wikipedia | 5/5, 5,015 ms | 5/5, 4,681 ms |
| Google Flights | 0/5 | 5/5, 11,603 ms |
| Olive Young sort | 5/5, 7,006 ms | 5/5, 5,675 ms |
| Search with a citation | 5/5, 2,858 ms | 5/5, 2,491 ms |
| Form fill | 5/5, 1,923 ms | 5/5, 1,707 ms |

Google Flights is 5.7x faster than browser-use flash_mode's 66,414 ms and Wikipedia 4.9x faster than
its 23,058 ms. Olive Young is 2.66x faster than its 15,071 ms, under the 3x bar on both trees (0.2.4:
2.15x). Decisions here took about 575 ms against 274-508 ms in the 0.1 OpenRouter runs, but those
were measured on another day under another load, so the shortfall is not pinned on the route. The first pass of this
release had Olive Young at 2/5. Two alternating corpus passes of `oliveyoung_sort_newest` came out
10/10 on both trees (median 5,457 ms against 5,689 ms), and the back-to-back bench came out 5/5 on
both, so that pass is counted as the site's minute, not the release.

`ja_nhk_society_section`, five runs: 4/5, median 2,022 ms. The one miss ended on a URL without
`genre/society`. In the 0.2.3 corpus passes it was 0/5 on both trees.

