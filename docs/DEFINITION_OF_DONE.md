# Definition of done for the next release

Agreed 2026-09-22: no tag and no release discussion until every row below is green on `main`.
Each row names the check; a row is green only when the check has been run and its output is in
the PR or the commit that closes it. 0.2.3, 0.2.4 and 0.2.5 were tagged as patch releases while
rows below were still red.

## Lanes landed

| lane | branch | state | closes |
|---|---|---|---|
| recovery | fix/recovery | on main (`12775c3..6681b06`) | review blockers 1, 2; should-fix 7, 13 |
| boundary | fix/boundary | on main (`f1a6307..f2f249d`) | blockers 3, 4; should-fix 5, 6, 10, 12 |
| observe | fix/observe | on main (`e819d39..c280f88`) | should-fix 8, 9, 15, 16; search dedupe |
| product | feat/serve | on main (`79e7d60..44513c4`) | Track D: serve, profiles, trace, image, windows/macos CI |
| reliability | fix/reliability | on main (`12f49f1`) | Track B: expanded controls first, same-origin, blocked_by_site, spec review, 80 tasks |
| speed | feat/speed | on main (`12f49f1`) | Track C: mutation settle, snapshot on the action round trip, prefetch, diff, profile |
| bench | feat/public-bench | on main (`12f49f1`) | Track E: Online-Mind2Web and WebVoyager adapters, standard judge, trajectories |
| bench-2 | fix/bench-2 | on main (`12f49f1`) | settle timeout, `JEV_RA_LOCALE`, final answer, blocked_by_site at step 0 |
| reliability-2 | fix/reliability-2 | on main (`12f49f1`) | open suggestions not re-offered, consent walls, hash routes, new-tab links, `JEV_RA_PROXY`, last step in the state |
| decisions | fix/decisions | in progress | late-route wait, href-less anchors, date picker as a list, gov.kr address, last-step effect and candidate evidence in the state, `JEV_RA_HYBRID` experiment |

## Gates on main after every lane lands

| gate | command | required |
|---|---|---|
| lint, format, types | `uv run ruff check . && uv run ruff format --check . && uv run ty check` | clean |
| generated docs | `uv run python scripts/gen_usage.py --check && uv run python scripts/check_i18n.py --check && uv run python scripts/check_demo_data.py --check` | clean |
| tests without a browser | `uv run pytest -q` | 0 failed, coverage ≥ 90 % |
| tests with a browser | `BU_CDP_URL=... uv run pytest -q` | 0 failed, coverage ≥ 95 % |
| CI | `.github/workflows/ci.yml` on the release commit | test x3, image, macos, windows, cold-start all green |
| real-site corpus | `uv run jev-ra corpus run --runs 3` on the release commit | ≥ 95 % on possible tasks; every escalate task 3/3 for its reason |
| head-to-head | `scripts/bu_corpus.py` on the same commit | published next to ours in BENCHMARKS.md |
| recorded tasks | `uv run jev-ra bench --live --runs 5` | ≤ 1.5 / 5.0 / 2.0 s median, all PASS |
| recovery, live | the stdio-client sequence in docs/PRODUCTION_REVIEW_2026-09-22.md | open, kill, open ok, close ok, file: refused |
| public benchmarks | `bench/public/` runners | Online-Mind2Web full 300 judged by WebJudge, trajectories published; WebVoyager as regression |
| quality bar | docs/QUALITY_BAR.md | no row left in "Debt" |

## Then, and only then

Release planning: version, changelog, PyPI trusted publisher fixed (no token upload), npm, GitHub
release, site, launch posts. Not before.

## Where things stand, 2026-09-22

The CI row was measured on main at 0.2.2 (CI green on `371d417`: test x3, image, macos, windows,
cold-start). The test rows were re-run on 0.2.5 (`354da08` plus documentation only) on 2026-09-23;
the corpus, head-to-head and recorded-task rows name their own release, date and route.

| gate | state | measured |
|---|---|---|
| lint, format, types | green | CI |
| generated docs | green | CI |
| tests without a browser | green | 784 passed, 169 skipped, 91.15 % |
| tests with a browser | green | 953 passed, 95.50 %, Chrome on 9377 with `JEV_RA_REQUIRE_BROWSER=1` |
| CI | green | `371d417` |
| real-site corpus | red | 213/231 possible tasks = 92.2 % on 0.2.4 (`2cf1e4d`), 3 runs via TypeSafe direct, 2026-09-23, the six walled tasks excluded; file_upload_picker and reddit_login_wall escalated 2/3 for their reason; run-to-run noise about ±5 of 240 (docs/BENCHMARKS.md) |
| head-to-head | amber | docs/BENCHMARKS.md, browser-use 29/40 = 72 % at 19.4 s (one run, 2026-09-22) vs jev-ra 102/120 = 85 % at 3.1 s (0.1 `f581761`, three runs, 2026-09-18): published side by side, but not on the same commit, day or run count |
| recorded tasks | amber | 0.2.5, 5 runs each: all five verified 5/5 back to back with 0.2.4; oliveyoung 2.66x under the 3x bar, jev-ra on the TypeSafe direct route on 2026-09-23 against browser-use's OpenRouter runs of 2026-09-18, which were not repeated (docs/BENCHMARKS.md, 0.2.5) |
| recovery, live | green | docs/PRODUCTION_REVIEW_2026-09-22.md sequence; the relaunch time is not recorded there |
| public benchmarks | red | 10 + 10 judged only; Online-Mind2Web 3/10 |
| quality bar | green | every row names its check; Debt is empty |

What remains, in the order it pays off:

1. **Decision quality**. The three mechanisms (late-route wait, href-less anchors, date grid) are on main as of 0.2.3 and hold on their fixtures; since 0.2.5 a link's click carries its address, so the wait runs on real pages: nhk went from 0/5 to 4/5 live and Google Flights from 0/5 to 5/5 (the field that opens an editor is typed into there). The state-evidence change and the `JEV_RA_HYBRID` helper sit on `fix/decisions` (`416273c`, `3f2f950`): the first makes hackernews_page_two read as BLOCKED on every rerun and is not merged until that is understood; the second depends on it. Measuring either on the public twenty needs OpenRouter credits (judges are o4-mini and gpt-4o).
2. **Walled sites**: gov.kr (now plus.gov.kr) and oliveyoung join the walls in corpus/egress.md; eight sites need a `JEV_RA_PROXY` egress to be measured at all.
3. **Public benchmarks at full size**: Online-Mind2Web all 300 through WebJudge, trajectories published; WebVoyager as the regression gate.
4. **Recorded tasks**: oliveyoung is 2.66x against the 3x bar. The 3x runs of 0.1 went through OpenRouter and these through TypeSafe direct, on different days, and the ratio divides into browser-use's runs of 2026-09-18, which were not repeated; run both routes and browser-use back to back on one machine before blaming either, then work on the task's own steps.

Browser tests skip silently when no Chrome answers on 9222; a local pass without one is not a pass. Start one as ci.yml does and run with `JEV_RA_REQUIRE_BROWSER=1`.
