# Changelog

## Unreleased

### Added
- Jev decisions client with strict answer validation: every choice must be an offered option and the
  argmax of probabilities that sum to 1 ± 0.02, on both the TypeSafe and OpenRouter routes.
- Browser core on browser-harness: one CDP target at 1280×900, trusted input only, act-time identity
  guards, and a semantic page marker for deterministic change detection. Open shadow roots and
  same-origin iframes are flattened into the same element list; a cross-origin iframe is reported as
  one opaque element.
- A dedicated automation Chrome is found, launched on its own profile and reused automatically;
  `BU_CDP_URL` still wins.
- One-round-trip decision policy: operation, per-operation target, host value binding, `prev_ok` and
  `goal_achieved` in a single request.
- Agent loop with deterministic verification, loop detection, budgets and an escalation contract that
  hands back the top eight candidates and the page text.
- DOM extraction for `text`, `elements`, `links`, `tables` and `main`, capped at 20,000 characters,
  with a session-scoped cache that a navigation or an action invalidates.
- `jev-ra search`: one SERP, Jev ranks the results, the best pages are read in parallel tabs with
  images, fonts and media blocked, and scored against the goal.
- MCP stdio server with fourteen `browser_*` tools, and a CLI covering `run`, `search`, the stateful
  `open`…`close` commands, `install`, `doctor` and `bench`.
- `jev-ra bench` with offline fixture tasks, `--live` for the three recorded tasks, and the ratio
  table against the browser-use baseline in `docs/benchmarks/`.
- `scripts/record_bench.py` and `scripts/render_side_by_side.py` render timestamped runs into a
  side-by-side GIF and MP4.

### Fixed before the tag
- A first run on a machine that has never run jev-ra: the cold profile's first navigation gets its own
  30 s budget, a launched Chrome is used only once a target answers, and `doctor` says why when it
  cannot reach a browser (a HOME too long for the daemon socket, or no Chrome installed).
- A headless launch (no display) no longer announces `HeadlessChrome`; DuckDuckGo answered that with a
  bot challenge. `jev-ra search` accepts `--goal` as well as the positional goal.
- Enter is sent only to the field that was observed; a field that lost focus is a stale page, not a
  form submitted by accident. Off-centre pointer points must land on the element itself. Only an
  observed node id is written into a page expression. Provider error strings are redacted before
  they reach the caller.
- A covered viewport is not counted as painted by a link below the fold; an unconfident DONE waits for
  the page to finish loading; repeated scrolls are reading, not a loop; scroll and wait freshness
  answer to the document, not to every word on it; a control that blinks in is not the panel a click
  opened; a supplied value with no field is asked again on a fresh reading.

### Known gaps
- The real-site corpus passes 102 of 120 attempts (85%). The 0.2 bar is 90%. The failures are stuck
  loops on two booking sites, three sites that serve a wall to this machine after a day of runs, and
  one check stricter than its goal. `docs/BENCHMARKS.md` lists every row.
- The npm launcher runs only after 0.1.0 is on PyPI. Windows is untested.
