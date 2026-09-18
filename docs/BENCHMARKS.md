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
