# Changelog

## 0.2.8 - 2026-09-23

0.2.8 is 0.2.6 with the install fix below. The human-check handoff that 0.2.7 shipped (the
`needs_human` reason, `resume`, per-host navigation pacing and the refusal/error wall kinds) is held
back for a later release, so 0.2.8 behaves on a check page as 0.2.6 did.

### Fixed
- `uvx jev-ra install claude` (and `npx -y jev-ra install claude`) registered the `jev-ra` that uvx
  or npx had put on PATH for that one run, a copy in their cache, by name; Claude Code then found no
  `jev-ra` to start. An entry point in the uv or npx cache is now skipped, so the command registered
  is `uvx jev-ra mcp` (or `npx -y jev-ra mcp`), as AGENTS.md says, and an installed entry point is
  registered by its full path so a later PATH does not matter. The server itself is unchanged;
  anyone who installed with 0.2.x can run the install again, or check with `claude mcp list`.

## 0.2.6 - 2026-09-23

### Changed
- The next decision is asked from the first reading that shows a step's effect, while the page is
  still proving it has stopped moving, and the first decision of a run is asked while the opened
  page finishes loading. An early answer is used only when the settled page asks the same request,
  character for character, so no decision changes; the proof and the load are still waited for.
  Runs send a few more decision requests than before (the ones whose page moved on are discarded
  and counted as speculations).
  Measured against 0.2.5 on one machine, alternating: Wikipedia 4.1-4.2 s against 4.3-5.3 s,
  Google Flights 9.4-10.2 s against 11.7-12.8 s, form fill 1.4-1.5 s against 1.7-1.8 s
  (docs/BENCHMARKS.md, 0.2.6).
- A settle that ends without proof hands over the reading it ended on instead of reading the page
  again.
- `jev-ra bench --json` names the decision route (`route`: provider, endpoint, model) and keeps
  every decision's round trip per task (`decision_ms`: n, median, p90, min, max and each value).
  RELEASING.md says to commit that payload for the release head and the previous tag. The first
  saved set: 275 decisions on the TypeSafe direct route, median 269 ms, p90 320 ms.

### Docs
- Every figure the README, the site and the notes quote was traced to a committed row: the hero
  showed another project's ratios and now shows jev-ra's own (8.5x / 7.5x / 4.0x against
  browser-use's recorded runs, 2026-09-18); the per-step bar reads 1.4 s from the measured values;
  the 0.2.4 corpus file is the real three-run pass; comparisons across days or routes say so.
- Every race on the landing page opens with a lightning strike on jev-ra's lane, and jev-ra's meter
  is a laser that fires again for each run it finishes. The measured times and 4x playback are
  unchanged.
- `docs/plans/benchmark-vs-field.md`: how jev-ra will be measured against browser-use and the
  commercial browser agents.

## 0.2.5 - 2026-09-23

### Fixed
- A field that opens an editor of its own when pressed (Google Flights' origin and destination) is
  typed into that editor. Focus that the press moved onto another text field is where the value goes;
  focus that did not move still goes to the observed field, so a swallowed click never types into
  whatever held focus before. Google Flights ended in `stuck_loop` 0/5 on both 0.2.3 and 0.2.4.
- A link's click carries the address it leads to, so the late-route wait added in 0.2.3 actually runs:
  a site that pushes the new address a moment after the click (NHK's section links) is read after the
  route, not on the hover menu the pointer opened.
- The recorded Flights spec reads Zurich the way Google spells it (Zürich).

### Site
- The landing page opens on a race: the same job for both tools, played at 4x from the times
  measured on 2026-09-18 (jev-ra's 5-run medians, browser-use's recorded runs), in four languages. Switching language keeps the race, and the scripts carry a version so a
  cached copy is not reused.
- The recorded demo breaks its lines at the width they render, so Japanese, Chinese and Korean stay
  inside the terminal; its Google page, cursor labels and step log follow the page's language; the
  calendar starts its weeks on Sunday and the date click lands on the 20th.
- The page title, description, accessibility labels, copy buttons, units and the remaining labels are
  translated in Korean, Japanese and Chinese.
- The README shows the landing page's step and architecture figures, animated, and carries accuracy
  on real sites, what a site's error page does and where the changelog is, in four languages.

## 0.2.4 - 2026-09-23

### Changed
- A site's error answer is no longer read as the page. The observation carries the document's
  `http_status`; a 5xx, a 429 or a short page that says it is an error is waited out for two seconds
  and reloaded once, and a site still answering with an error is reported as `blocked_by_site`
  (`detail.wall = "http <status>"`), never as a plain `blocked`.
- Corpus rows record `http_status` and `site_error`, the summary shows a `site` column, and
  `scripts/soak.py` counts site errors, so a failure on the site's bad minute is told apart from a
  product failure.
- The three httpbin form tasks also run against httpbingo.org, so the forms family does not depend
  on one host.
- The recorded Google Flights task asks for a departure a month ahead instead of a day that has
  passed.

## 0.2.3 - 2026-09-22

### Changed
- A click on a link whose router pushes the address late is waited out by the address, and the
  route counts as arrived only when the page's title, text or controls changed with it.
- An `<a>` without `href` that carries a role, a tabindex, a handler or a pointer cursor is offered
  as a control; ordinary pages gain no controls from this.
- A date picker is driven from its calendar cells: once a click opened a grid of dates, the cells
  are offered first and the opener is not clicked again.
- A corpus spec may write a date as `{today+N}`, so a booking task never asks for a day the site's
  picker no longer offers.
- `docs/BENCHMARKS.md` records the corpus at this release on both trees, three runs each, and what
  run-to-run noise on live sites looks like.

## 0.2.2 - 2026-09-22

### Added
- `scripts/check_no_invented_input.py` fails a corpus results file in which any typed string was
  not one of the task's values; `scripts/soak.py` runs one task many times on one session and
  reports pass count, median and p95 seconds, decisions and the reasons seen; `scripts/check_site.py`
  says whether a corpus site is reachable, walled, and how many controls it shows.

### Changed
- Every row of `docs/QUALITY_BAR.md` names the check that proves it; the Debt list is empty.
- The corpus names the address gov.kr now serves (plus.gov.kr; still walled, 3/3), and
  `corpus/egress.md` records oliveyoung's bot check as the eighth wall.
- Browser-backed test coverage is 95.6 % (925 tests); a target whose setup fails is closed whatever
  listens on 9222.

## 0.2.1 - 2026-09-22

### Changed
- The release workflow publishes to PyPI with the maintainer's API token (`PYPI_API_TOKEN`), and a
  re-run of the job skips files that are already there. Trusted publishing failed every run with
  `invalid-publisher`; `docs/RELEASING.md` keeps its values in case it is revisited.
- The suggestion-list and proxy tests read what CI reads: the settled state with the prefetch off,
  and a caller flag that the Linux sandbox flag cannot shadow.
- `docs/DEFINITION_OF_DONE.md` says where every gate stands on this release and what remains, in
  the order it pays off.

## 0.2.0 - 2026-09-22

Nine lanes landed on top of 0.1.3, measured on the eighty-task corpus and on the public
benchmarks. Numbers and raw runs are in `docs/BENCHMARKS.md`; what still stands between this
release and the product bar is in `docs/DEFINITION_OF_DONE.md`.

### Added
- `jev-ra serve` exposes the same fourteen tools over HTTP and SSE; `jev-ra trace <run_id>` renders
  a run; `jev-ra profile` prints where a run's time went; `jev-ra clean` stops what jev-ra started
  and empties its profile.
- Named profiles keep their cookies (`--profile`), and a run id and a log level an operator can set
  (`JEV_RA_RUN_ID`, `JEV_RA_LOG_LEVEL`).
- `JEV_RA_LOCALE` reaches the launched Chrome and an attached one; `JEV_RA_PROXY` puts the browser
  behind an egress, and `corpus/egress.md` records what the seven walled sites answered through it.
- Two escalation reasons: `provider_error` when the decision provider will not answer, and
  `blocked_by_site` when a site serves a wall instead of a page, at the first request as well.
- A question-shaped goal ends with a one-line final answer.
- A container image (`Dockerfile`), and CI jobs for the image, macOS, Windows and a cold start
  against a real Chrome.
- `bench/public/`: an act/observe adapter any harness can drive, with Online-Mind2Web and
  WebVoyager runners judged by the benchmarks' own harnesses; `scripts/bu_corpus.py` runs
  browser-use on the same corpus under the same verify specs.
- Forty more corpus tasks, every verify spec reviewed against the goal it proves.

### Changed
- The page is settled by mutation rather than by budget, the observation after an action rides the
  action's own round trip, and the next decision is prefetched while the page settles.
- The state names what the last step opened; a control that opened a panel is shown as expanded
  with the panel first; a control whose suggestions are open is not offered again while they are
  up; links off the current site are offered last unless the goal names a site.
- A consent wall is accepted before anything else is tried; a hash route counts as a navigation;
  a link that asks for a new tab is followed in the tab this run drives.
- The MCP server runs one tool at a time on the shared session, caps tool arguments at the edge,
  closes its browser on SIGTERM and on exit, and exits instead of hanging when terminated.
- Only web schemes are opened; `file:` needs an opt-in.
- The sdist carries the package, not the brand assets (3.2 MB to 248 KB, the 0.1.3 and 0.2.0 sdists
  on PyPI).

### Fixed
- A dead session is dropped so the next open starts over; a remembered CDP url is probed before it
  is trusted; a target is closed when its setup fails.
- The post-input settle waits as long as any other evaluate, and stillness is measured on a timer
  as well as on animation frames, so a background target on Linux is not read too early.
- A page that mentions a captcha is not a page that serves one.
- `browser_search` lists each url once and leaves the session as it found it.
- A direct press goes through the same focus check as a decided one; a ref names the observation
  it came from; `doctor` reports Chrome before it asks for a key.

## 0.1.3 - 2026-09-22

### Added
- Every MCP tool declares the four annotation hints (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`). Clients use them to decide what to confirm with the user, and
  some directories reject tools that leave any unset. No tool is destructive; observe, extract,
  screenshot and wait are read-only; the tools that act on a live site are open-world. `docs/USAGE.md`
  shows the hints per tool.

## 0.1.2 - 2026-09-21

### Changed
- The npm package page carries the same header as the repository: logo, badges, the hero, and links
  to the site, the reference and the benchmarks. Its homepage is the site. The four READMEs link
  the site too. No code change.

## 0.1.1 - 2026-09-21

### Fixed
- The npm launcher did nothing when run the way npm runs it. `node_modules/.bin/jev-ra` is a
  symlink, so the "am I the entry point" check compared the link's path with the file's and never
  matched; `npx jev-ra ...` exited 0 without output. The check now compares real paths. 0.1.0 on
  npm is affected; PyPI 0.1.0 is not.

## 0.1.0 - 2026-09-21

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
