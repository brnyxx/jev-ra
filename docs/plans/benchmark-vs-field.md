# Benchmark plan: jev-ra against the field

Goal: show, with raw rows anyone can rerun, whether jev-ra is the fastest and most accurate browser
control available to a coding agent, against browser-use and against commercial browser agents that
can be driven through an API. Written 2026-09-23. Nothing in this plan is measured yet.

## Where we stand

- Recorded tasks (5 simple real-site tasks): jev-ra 4.9x-5.7x faster than browser-use 0.13
  flash_mode, all verified (docs/BENCHMARKS.md, 0.2.5). Olive Young is 2.66x, under our 3x bar.
- Corpus (83 tasks, page-state specs): 213 / 249 on 0.2.4. On the 40 tasks run by both, jev-ra
  passed 102 / 120 (85 %, median 3.1 s) and browser-use passed 29 / 40 (72 %, median 19.4 s).
- Public: Online-Mind2Web 3 / 10. The field's public scores on the same benchmark are far higher,
  as listed on the Steel.dev leaderboard (self- or team-reported unless marked otherwise):
  - Browser Use Cloud (bu-max): 97.0 %
  - GPT-5.4 native computer use: 93.0 %
  - Gemini 2.5 Computer Use: 69.0 % (independent)
  - Stagehand + Gemini 2.5 CU: 65.0 % (independent)
  - OpenAI Operator: 61.3 %

  Judges differ between these rows, so they do not compare cleanly with each other or with ours.
- Speed claims in the field are not like-for-like either. Browser Use reports about 20 steps a
  minute and about 68 s per trajectory, measured as model inference time only (browser-use.com,
  2025-10-08). It also reports about 14 tasks an hour on its own 100-task set (BU Bench V1).

So jev-ra is ahead on speed for the tasks it completes, and far behind on accuracy for hard,
long-horizon tasks. A benchmark that shows only the first half would not survive a reader who knows
the leaderboard.

## Contestants

These can all be run from a script on the same machine in the same hour:

| contestant | how it is driven | configuration |
|---|---|---|
| jev-ra | MCP/CLI, local Chrome | release under test, TypeSafe direct and OpenRouter routes both |
| browser-use OSS | Python, local Chrome | 0.13 flash_mode + gemini-3-flash (our existing baseline), and its default |
| Browser Use Cloud | REST API v2, their browsers | default hosted model |
| OpenAI computer use | Responses API `computer` tool, local Chrome via Playwright | GPT-5.4 |
| Gemini computer use | Gemini API computer-use tool, local Chrome via Playwright | current computer-use model |
| Stagehand v3 agent | Node SDK, Browserbase or local | its fastest documented model |

Consumer agent browsers (ChatGPT Atlas, Comet) have no API, cannot be timed or verified by a script,
and are left out. The report says so.

## Task sets

1. The corpus: 83 tasks with page-state verify specs. These are objective and have no judge; this is
   the primary set for accuracy and speed.
2. Online-Mind2Web, stratified sample of 60 (20 easy, 20 medium, 20 hard) judged by WebJudge
   (o4-mini), the judge the benchmark ships. This set is the field's common reference.
3. The 5 recorded tasks, for continuity with every table published so far.

## Rules

- Same machine, same network, same time window. Contestants interleave per task, not per tool, so a
  site's bad minute hits everyone.
- 3 runs per task per contestant on the corpus and recorded sets; 1 run on Online-Mind2Web (cost).
- Each contestant runs in its fastest documented configuration. That configuration is written next
  to every number.
- Reported per contestant:
  - pass rate
  - median wall time over passed runs only, with the count it is taken over (so a fast failure never
    counts as speed)
  - median steps
  - cost per task
  - time to first action
- Cloud contestants run on their own browsers; their times include their network, and the report
  says so.
- Raw rows for every run go under `docs/benchmarks/<date>-field/`: trajectories where the tool
  exposes them, and the judge's reasoning for Online-Mind2Web.
- No headline claim without its row. "Fastest" is written only for the sets and the tools where the
  table shows it.

## What it needs before it can run

- API keys and a budget:
  - OpenAI: GPT-5.4 computer use, and o4-mini for WebJudge
  - Gemini
  - Browser Use Cloud
  - Browserbase, if Stagehand runs there
  - OpenRouter credits, to measure both jev-ra routes in the same window

  Cost per contestant is not estimated yet; it has to be measured on a 5-task dry run first.
- An adapter per contestant under `bench/field/`, each a thin script that takes (url, goal, values)
  and returns (final url, final text, steps, seconds, cost), so our page-state specs verify every
  tool's end state the same way.
- A dry run on 5 corpus tasks to price the full run.

## What to fix first

Accuracy on long-horizon tasks is the gap that decides whether "best" can be claimed. The parked
decision-quality work (`fix/decisions`, `fix/decisions-2`: state evidence, hybrid helper) and the
Online-Mind2Web failure analysis come before the full field run. Speed work (Olive Young, 3x bar)
continues in parallel.
