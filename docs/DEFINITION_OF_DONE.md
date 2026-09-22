# Definition of done for the next release

Agreed 2026-09-22: no tag and no release discussion until every row below is green on `main`.
Each row names the check; a row is green only when the check has been run and its output is in
the PR or the commit that closes it.

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

Measured on main `371d417` (CI green: test x3, image, macos, windows, cold-start).

| gate | state | measured |
|---|---|---|
| lint, format, types | green | CI |
| generated docs | green | CI |
| tests without a browser | green | 731 passed, 91.3 % |
| tests with a browser | red, close | 881 passed, 94.19 % (bar 95 %) |
| CI | green | `371d417` |
| real-site corpus | red | 201/219 possible tasks = 91.8 % (bar 95 %), `12f49f1` 3 runs |
| head-to-head | green | docs/BENCHMARKS.md, browser-use 29/40 = 72 % at 19.4 s vs 102/120 = 85 % at 3.1 s |
| recorded tasks | not measured | needs a quiet machine, 5 runs |
| recovery, live | green | docs/PRODUCTION_REVIEW_2026-09-22.md sequence, 22.5 s relaunch |
| public benchmarks | red | 10 + 10 judged only; Online-Mind2Web 3/10 |
| quality bar | red | Debt rows remain in docs/QUALITY_BAR.md |

What remains, in the order it pays off:

1. **Decision quality** (lane `fix/decisions`, paused at `dc5938f` with the late-route fixture written and the snapshot naming each link's address; the wait itself is not wired). Three mechanisms: a link click waited out by the address (nhk), href-less anchors offered as controls (JMA), a date picker driven as a grid (Google Flights). Then the state carries the last step's effect and each candidate's evidence, measured on the corpus and the public twenty; then `JEV_RA_HYBRID` as an experiment with its cost. This is the gate that moves the corpus from 91.8 % to 95 %.
2. **Corpus hygiene**: `gov_kr_search` url to plus.gov.kr; oliveyoung's bot check recorded as the eighth wall in corpus/egress.md; seven walled sites need a `JEV_RA_PROXY` egress to be measured at all.
3. **Public benchmarks at full size**: Online-Mind2Web all 300 through WebJudge, trajectories published; WebVoyager as the regression gate.
4. **Recorded tasks**: `uv run jev-ra bench --live --runs 5` on a quiet machine, against 1.5 / 5.0 / 2.0 s.
5. **Browser coverage** from 94.2 % to 95 %, and the quality-bar Debt rows (soak.py, check_no_invented_input.py, the rest of that table).
6. A fragile test noted by the speed lane: `test_a_target_whose_setup_fails_is_closed_again` assumes nothing listens on 9222.

Browser tests skip silently when no Chrome answers on 9222; a local pass without one is not a pass. Start one as ci.yml does and run with `JEV_RA_REQUIRE_BROWSER=1`.
