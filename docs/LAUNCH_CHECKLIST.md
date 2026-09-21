# Launch checklist

Everything here must be true before the repository goes public.

## Product
- [ ] `uvx jev-ra install claude` on a clean machine with only `OPENROUTER_API_KEY` set: first `browser_search` works (after the PyPI release)
- [x] `npx -y jev-ra install codex` same: `npx -y jev-ra@0.1.1 doctor` ends in `decision: DONE in 662 ms` (2026-09-21; 0.1.0's launcher was silent, fixed in 0.1.1)
- [x] `jev-ra doctor` explains every failure it can detect in one line with a next step
- [x] `jev-ra bench --live --runs 5`: all tasks PASS ≥ 3x vs browser-use flash_mode, zero text-model calls (docs/BENCHMARKS.md, 2026-09-18)
- [x] corpus measured and published: 102/120 = 85 % on 2026-09-18 (main f581761) (docs/BENCHMARKS.md). ≥ 90 % is the 0.2 bar, not a 0.1.0 gate

## Repository
- [x] README: hero, three numbers with date and method, GIF, 3-line install per agent, how it works, limits, FAQ
- [x] README ko/ja/zh-CN in sync (`scripts/check_i18n.py`, CI)
- [x] docs/BENCHMARKS.md reproducible in one command; raw rows committed
- [ ] LICENSE (MIT), THIRD_PARTY_NOTICES.md (browser-harness, jev-ultrafast snapshot.js, mcp, httpx)
- [ ] CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, issue templates, PR template
- [ ] CI green on 3.12 / 3.13 / 3.14 with headless Chrome; coverage ≥ 85 %; type check clean (local: ruff, format, ty, pytest, coverage 89 %; Actions runs on first push)
- [ ] No secrets, no absolute local paths, no personal data in fixtures (grep for `/Users/`, `sk-or-`, `apikey_`) - run before push
- [ ] `git log` has no attribution trailers, no WIP commits
- [x] Tags: `v0.1.0` (8b2b3ca) and `v0.1.1` (b1b1207); CHANGELOG entries

## Maintainer actions before the tag (see docs/RELEASING.md)
- [ ] PyPI: trusted publisher for `jev-ra` (owner `brnyxx`, repo `jev-ra`, workflow `release.yml`, environment `pypi`). Both 0.1.x runs failed with `invalid-publisher`; 0.1.0 and 0.1.1 were uploaded with the API token instead (docs/RELEASING.md, fallback)
- [x] npm: token in the `NPM_TOKEN` secret; repository variables `PYPI_TRUSTED=true`, `NPM_PUBLISH=true` (2026-09-21)
- [ ] Rotate the OpenRouter key that one worker session echoed into its local transcript on 2026-09-18

## Distribution
- [x] PyPI: 0.1.0 and 0.1.1 published (API token upload of the CI-built artifact; trusted publishing still to fix)
- [x] npm: 0.1.0 and 0.1.1 published from `release.yml` with provenance (sigstore log entries in the run logs)
- [x] GitHub releases v0.1.0 and v0.1.1 with wheel and sdist attached
- [x] Repository set to public; topics: `browser-automation`, `mcp`, `claude-code`, `codex`, `typesafe`, `jev`, `web-agent`
- [x] GitHub Pages enabled from the `pages.yml` workflow; landing page loads, demo replays, language option works

## Announcement (drafts in docs/launch/)
- [ ] Show HN post
- [ ] X thread
- [ ] PR to `Anil-matcha/awesome-jev-by-typesafe`
- [ ] Post in browser-use Discord `#showcase`, r/ClaudeAI, r/LocalLLaMA
- [ ] TypeSafe team ping (they list community projects)
