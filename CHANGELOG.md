# Changelog

## Unreleased

### Added
- Jev decisions client with strict answer validation: every choice must be an offered option and
  the argmax of probabilities that sum to 1 ± 0.02, on both the TypeSafe and OpenRouter routes.
- Browser core on browser-harness: one CDP target at 1280×900, trusted input only, act-time
  identity guards, and a semantic page marker for deterministic change detection.
- One-round-trip decision policy: operation, per-operation target, host value binding, `prev_ok`
  and `goal_achieved` in a single request.
- Agent loop with deterministic verification, loop detection, budgets and an escalation contract
  that hands back the top eight candidates and the page text.
- DOM extraction for `text`, `elements`, `links`, `tables` and `main`, capped at 20,000 characters.
- MCP stdio server with thirteen `browser_*` tools, and a CLI covering `run`, the stateful
  `open`…`close` commands, `install`, `doctor` and `bench`.
- `jev-ra bench` with offline fixture tasks, `--live` for the three recorded tasks, and the
  browser-use baseline rows in `docs/benchmarks/`.

### Known gaps
- Google Flights and the Olive Young sort task return `blocked`: their controls live in shadow
  roots and iframes, which v0.1 does not traverse.
