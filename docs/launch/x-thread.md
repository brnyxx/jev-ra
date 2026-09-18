# X thread draft

1/ Coding agents drive browsers slowly because every click is an LLM call. jev-ra fixes that: a zebra that steps out of the browser window. 3-5x faster than browser-use, measured. 🧵

2/ How: TypeSafe Jev decides each step in ~300 ms - which element, is it done, did the last action work - as typed answers, never text. Your Claude Code / Codex plans, supplies values, reads the page, takes over on escalation. No second LLM.

3/ Same Chrome, same key: Wikipedia 4.3 s vs 23.1 s. Google Flights 17.2 s vs 66.4 s. E-commerce sort 5.3 s vs 15.1 s. Medians over 5 runs in the repo, reproducible with one command.

4/ Install: `uvx jev-ra install claude` or `npx -y jev-ra install codex`. OpenRouter key works; no TypeSafe account needed.

5/ Honest limits: cross-origin iframes, canvas, uploads, captchas escalate instead of guessing. MIT. Built on browser-use's jev-ultrafast snapshot idea, credited. github.com/brnyxx/jev-ra
