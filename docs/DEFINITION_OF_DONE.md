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
