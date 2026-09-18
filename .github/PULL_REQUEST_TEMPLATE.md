## What this changes

<!-- One or two sentences. What was wrong or missing, and what the change does about it. -->

## Why

<!-- Link the issue if there is one. If the change affects behaviour on real sites, say which. -->

## Checklist

- [ ] `uv run ruff check .` passes
- [ ] `uv run ty check` passes
- [ ] `uv run pytest -q` passes with `BU_CDP_URL` set, so the browser-marked tests really ran
- [ ] New behaviour has a test; a bug fix has the test that reproduces it, written first
- [ ] No new runtime dependency, or the pull request says why one is needed
- [ ] Model output still never becomes a selector, coordinates, or JavaScript
- [ ] `docs/USAGE.md` regenerated if a tool signature or CLI flag changed
      (`uv run python scripts/gen_usage.py`)
- [ ] Commit messages are English, conventional prefix, imperative, under 72 characters, no trailers

## If this touches the decision path

`NEXT_ACTION` and `TARGET` were measured. Changing them, the budgets, the wait caps or the loop
detector needs numbers:

- [ ] `uv run jev-ra bench --live --runs 5` before and after, both pasted below
