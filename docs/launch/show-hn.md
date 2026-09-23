# Show HN draft

**Title:** Show HN: jev-ra – browser use for coding agents, 4-8.5x faster than browser-use

**Body:**

I got tired of watching Claude Code spend 2-3 seconds per click when it drives a browser. Every step went through a full LLM call: screenshot or DOM dump in, JSON action out.

jev-ra moves the per-step decision to TypeSafe's Jev, a "System One" model that only answers typed questions (pick one of these elements, is the goal done, did the last action work) in ~300 ms and never generates text. The coding agent you already run does the planning, supplies form values, reads the extracted page, and takes over when jev-ra escalates. There is no second LLM in the loop.

Numbers, same Chrome, same key, medians of 5 runs each (2026-09-18), against browser-use 0.13 in flash_mode with gemini-3-flash:
- Wikipedia lookup: 2.7 s vs 23.1 s (8.5x)
- Google Flights one-way search, verified against the results page: 8.9 s vs 66.4 s (7.5x)
- E-commerce sort: 3.8 s vs 15.1 s (4.0x)
Against browser-use 0.13 flash_mode's recorded runs, our medians over 5 verified runs are 8.5x / 7.5x / 4.0x faster (same machine, same Chrome, same OpenRouter key, 2026-09-18). Raw rows and the method are in docs/BENCHMARKS.md, and an 83-task real-site corpus is published there too: 213 of 249 runs passed on 0.2.4.

It is an MCP server + CLI. `uvx jev-ra install claude` or `npx -y jev-ra install codex`. Works with an OpenRouter key; no TypeSafe account needed.

What it does not do yet: cross-origin iframes, canvas, file uploads, captchas. Those escalate to your agent with a reason instead of guessing.

Code: https://github.com/brnyxx/jev-ra - the snapshot logic started from browser-use's own jev-ultrafast demo (MIT); credit in the README.
