# Show HN draft

**Title:** Show HN: jev-ra – browser use for coding agents, 3-5x faster than browser-use

**Body:**

I got tired of watching Claude Code spend 2-3 seconds per click when it drives a browser. Every step went through a full LLM call: screenshot or DOM dump in, JSON action out.

jev-ra moves the per-step decision to TypeSafe's Jev, a "System One" model that only answers typed questions (pick one of these elements, is the goal done, did the last action work) in ~300 ms and never generates text. The coding agent you already run does the planning, supplies form values, reads the extracted page, and takes over when jev-ra escalates. There is no second LLM in the loop.

Numbers, same Chrome, same key, one run each (medians over 5 runs in the repo):
- Wikipedia lookup: 4.3 s vs 23.1 s for browser-use in flash_mode (5.4x)
- Google Flights one-way search, verified: 17.2 s vs 66.4 s (3.9x)
- E-commerce sort: 5.3 s vs 15.1 s (2.8x)

It is an MCP server + CLI. `uvx jev-ra install claude` or `npx -y jev-ra install codex`. Works with an OpenRouter key; no TypeSafe account needed.

What it does not do yet: cross-origin iframes, canvas, file uploads, captchas. Those escalate to your agent with a reason instead of guessing.

Code: https://github.com/brnyxx/jev-ra - the snapshot logic started from browser-use's own jev-ultrafast demo (MIT); credit in the README.
