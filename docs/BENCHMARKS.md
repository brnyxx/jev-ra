# Benchmarks

Everything here was measured on one machine on 2026-09-18. No number is estimated, and a task that
does not finish is reported as a failure rather than as a time.

## Method

- **Machine and browser**: one dedicated Chrome 153 on a non-default profile, remote debugging on
  `http://127.0.0.1:9222`, 1280×900 viewport. Both sides drive the same browser.
- **Route**: every model call goes through OpenRouter. jev-ra uses `typesafe/jev-1.13`; browser-use
  uses the driver model named in each column.
- **browser-use**: 0.13.10, `use_vision=False`, `max_steps=25`, 240 s timeout per task, one run per
  cell, wall time measured around `agent.run()` including the CDP connect.
  Script and raw rows: [`2026-09-18-browser-use-baseline/`](benchmarks/2026-09-18-browser-use-baseline/).
- **jev-ra**: `jev-ra bench --live`, one run per task, wall time measured around `Agent.run()`
  including the first navigation.
- **Acceptance for v0.1**: ≥ 3× the `flash_mode` column on every task, with zero text-model calls.

## The browser-use baseline

| task | gemini-3-flash | gemini-3-flash `flash_mode` | gpt-5-mini |
|---|---|---|---|
| Wikipedia: open the Gödel incompleteness article | 46,461 ms · 5 steps | 23,058 ms · 4 steps | 100,399 ms · 11 steps |
| Google Flights ZRH→LON one-way 2026-09-20 | 63,565 ms · 11 steps | 66,414 ms · 11 steps | 238,045 ms · 25 steps, budget hit |
| Olive Young category: sort by 신상품순 | 17,493 ms · 3 steps | 15,071 ms · 3 steps | timeout at 240 s |

claude-sonnet-5 could not drive browser-use through OpenRouter at all: its structured-output schema
was rejected with `compiled grammar is too large`. Its row is kept in the raw data and excluded from
every ratio. The gpt-5-mini Flights row hit the step budget and its final URL is not a verified
one-way search.

## Where jev-ra stands

| task | jev-ra | steps | decisions | text calls | ratio vs `flash_mode` | verdict |
|---|---|---|---|---|---|---|
| Wikipedia | 2,205 ms | 2 | 4 | 0 | 10.5× | PASS |
| Google Flights | `blocked` after 1,908 ms | 2 | 3 | 0 | - | FAIL |
| Olive Young sort | `blocked` after 1,902 ms | 0 | 1 | 0 | - | FAIL |

Both failures are capability, not speed. Jev returns `BLOCKED` on those two pages rather than
running slowly, so the ratio column is meaningless for them and is left empty.

Offline, with the decisions scripted and no network at all:

| fixture task | time | steps |
|---|---|---|
| form fill (type, type, select, submit) | 134 ms | 4 |
| catalog sort (scroll, click) | 82 ms | 2 |

## Cost and latency per call

| measurement | value |
|---|---|
| one Jev decision, OpenRouter | 274-508 ms observed across runs |
| Wikipedia task, end to end | $0.000874 for 4 decisions |
| text-model calls in every run above | 0 |

## Reproducing

```sh
export OPENROUTER_API_KEY=sk-or-...
export BU_CDP_URL=http://127.0.0.1:9222     # or let jev-ra launch its own Chrome
uvx jev-ra bench          # offline fixtures, no network, no key needed
uvx jev-ra bench --live   # the three tasks above, with the ratio table and PASS/FAIL
```

The browser-use side needs its own environment, because browser-use is not a dependency of jev-ra:

```sh
uv run --with browser-use==0.13.10 python docs/benchmarks/2026-09-18-browser-use-baseline/bench.py
```

## Recording a side-by-side video

```sh
uv run python scripts/record_bench.py wikipedia --out docs/recordings
uv run python scripts/render_side_by_side.py docs/recordings/wikipedia/jev-ra --out assets/demo/wikipedia
```

`render_side_by_side.py` accepts several recording directories and lays them out as columns with a
running clock each, at 1× speed. It writes a GIF always, and an MP4 as well when ffmpeg is on PATH.
