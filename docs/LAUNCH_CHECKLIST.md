# Launch checklist

Everything here must be true before the repository goes public.

## Product
- [ ] `uvx jev-ra install claude` on a clean machine with only `OPENROUTER_API_KEY` set: first `browser_search` works
- [ ] `npx -y jev-ra install codex` same
- [ ] `jev-ra doctor` explains every failure it can detect in one line with a next step
- [ ] `jev-ra bench --live --runs 5`: all tasks PASS ≥ 3x vs browser-use flash_mode, zero text-model calls
- [ ] corpus pass rate ≥ 90 % (Phase 5), every failure an expected escalation

## Repository
- [ ] README: hero, three numbers with date and method, GIF, 3-line install per agent, how it works, limits, FAQ
- [ ] README.ko.md in sync
- [ ] docs/BENCHMARKS.md reproducible in one command; raw rows committed
- [ ] LICENSE (MIT), THIRD_PARTY_NOTICES.md (browser-harness, jev-ultrafast snapshot.js, mcp, httpx)
- [ ] CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, issue templates, PR template
- [ ] CI green on 3.12 / 3.13 / 3.14 with headless Chrome; coverage ≥ 85 %; type check clean
- [ ] No secrets, no absolute local paths, no personal data in fixtures (grep for `/Users/`, `sk-or-`, `apikey_`)
- [ ] `git log` has no attribution trailers, no WIP commits
- [ ] Tags: `v0.1.0` on the release commit; CHANGELOG entry

## Distribution
- [ ] PyPI: real 0.1.0 replaces the 0.0.1 placeholder (trusted publishing configured)
- [ ] npm: real 0.1.0 replaces the 0.0.1 placeholder; `npm pkg fix` warnings gone; provenance on
- [ ] GitHub release with wheel, sdist, and the demo MP4 attached
- [ ] Repository set to public; topics: `browser-automation`, `mcp`, `claude-code`, `codex`, `typesafe`, `jev`, `web-agent`
- [ ] GitHub Pages enabled from the `pages.yml` workflow; landing page loads with the video

## Announcement (drafts in docs/launch/)
- [ ] Show HN post
- [ ] X thread
- [ ] PR to `Anil-matcha/awesome-jev-by-typesafe`
- [ ] Post in browser-use Discord `#showcase`, r/ClaudeAI, r/LocalLLaMA
- [ ] TypeSafe team ping (they list community projects)
