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

### Known gaps
- Google Flights and the Olive Young sort task return `blocked`. Jev declines to act on them rather
  than running slowly; both are open.
