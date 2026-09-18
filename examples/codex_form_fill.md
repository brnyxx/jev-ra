# Codex: fill a form without letting a model invent the values

## Setup, once

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra install codex
```

That runs `codex mcp add jev-ra --env OPENROUTER_API_KEY="$OPENROUTER_API_KEY" -- uvx jev-ra mcp`.

## Ask

> Use jev-ra to place the test order on http://localhost:8000/checkout for Ada Lovelace,
> ada@example.com, express shipping.

## What Codex does

```
browser_open(url="http://localhost:8000/checkout")
browser_run(
  goal="Place an order for Ada Lovelace at ada@example.com with express shipping.",
  values={"name": "Ada Lovelace", "email": "ada@example.com"}
)
```

The `values` are the point. Jev decides *which* field each value belongs in, in the same round trip
that picks the field, and jev-ra types exactly the string you supplied. Nothing is generated.

```json
{
  "status": "done",
  "reason": "goal_achieved",
  "steps": [
    {"n": 1, "operation": "TYPE_TEXT", "target_label": "Full name", "text": "Ada Lovelace", "page_changed": true},
    {"n": 2, "operation": "TYPE_TEXT", "target_label": "Email", "text": "ada@example.com", "page_changed": true},
    {"n": 3, "operation": "SELECT", "target_label": "Shipping → Express", "page_changed": true},
    {"n": 4, "operation": "CLICK", "target_label": "Place order", "page_changed": true}
  ],
  "decisions": 5,
  "text_calls": 0,
  "elapsed_ms": 2140
}
```

## If you forget a value

The run stops instead of guessing:

```json
{
  "status": "escalate",
  "reason": "needs_value",
  "detail": {
    "field": {"ref": "e2", "label": "Email", "role": "textbox", "current_value": ""},
    "goal": "Place an order for Ada Lovelace with express shipping.",
    "reason": "no supplied value fits this field"
  }
}
```

Call `browser_run` again with the missing value in `values`. Nothing was typed in the meantime.

## Checking the result yourself

```
browser_extract(mode="text")     # the confirmation page as text
browser_screenshot()             # the viewport as a JPEG
browser_close()
```

## Things worth knowing

- Every executed target resolves from a node id jev-ra observed. A value you supply is the only text
  that reaches the page.
- If the page moves under the decision — a re-render, a replaced button — the action is refused with
  `StalePage` and retried from a fresh observation rather than clicking whatever is now in that spot.
- `password`, `file` and `hidden` inputs are never observed, so they never appear as targets and
  their values never leave the browser.
