# X thread draft

1/ Coding agents drive browsers slowly because every click is an LLM call. jev-ra moves that decision to a 300 ms model. 4-8.5x faster than browser-use on three recorded tasks, same Chrome, same key.

2/ How: TypeSafe Jev answers typed questions for each step - which element, did the last action work, is the goal done - in about 300 ms. Your Claude Code or Codex plans, supplies the text to type, reads the page, and gets control back when jev-ra cannot continue. No second LLM.

3/ Medians of 5 runs vs browser-use flash_mode: Wikipedia 2.7 s vs 23.1 s. Google Flights 8.9 s vs 66.4 s. E-commerce sort 3.8 s vs 15.1 s. One command reproduces the table; raw rows are in the repo.

4/ Install: `uvx jev-ra install claude` or `npx -y jev-ra install codex`. OpenRouter key works; no TypeSafe account needed.

5/ Limits: cross-origin iframes, canvas, uploads and captchas return an escalation with a reason. A 40-task real-site corpus passes 85 % on the second measurement; the rest is published too. MIT, uses browser-use's jev-ultrafast snapshot approach with credit. github.com/brnyxx/jev-ra
