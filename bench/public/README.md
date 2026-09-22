# jev-ra on the public benchmarks

Two benchmarks the field cites, run through one adapter, judged by the harnesses their own authors
publish, with every trajectory kept. Nothing here is a claim about jev-ra that a judge did not make.

Everything below was measured on 2026-09-22, on one macOS desktop, against the live web. **Ten
tasks each is a smoke, not a score.** It is enough to prove that the submission layouts are right
and that the judges accept them; it is not enough to compare against a 300-task leaderboard entry,
and the numbers are reported here only so that the method has something attached to it.

Every table below reports **before** and **after**: the first pass, and a rerun of the same twenty
tasks with the same judges after four jev-ra fixes the first pass had traced - a post-input settle
that timed out, a browser that spoke the machine's language, no final answer on a question-shaped
task, and a site wall read as a task that failed. `REPORT.md` in the repository root has the fixes
and what each of them moved.

## What is here

| file | what it does |
|---|---|
| `adapter.py` | `start(url)`, `step(instruction)`, `run(task, max_steps)` on top of `jev_ra.Agent`, with a screenshot per landed step |
| `om2w.py` | Online-Mind2Web: runs tasks, writes the v2 submission layout, runs WebJudge |
| `webvoyager.py` | WebVoyager: runs tasks, writes what `evaluation/auto_eval.py` reads, runs it |
| `webjudge_runner.py` | drives WebJudge in one process (see *What had to be worked around*) |
| `vendor.py` | fetches both upstream repositories at a pinned commit into `vendor/` |

`vendor/`, `data/` and `runs/` are gitignored. No benchmark data and no trajectory is committed.

## Running it

```sh
export OPENROUTER_API_KEY=sk-or-...
# The language every session asks sites for. jev-ra defaults to en-US and sends it both to a Chrome
# it launched (--lang, --accept-lang) and to one it attached to (setLocaleOverride, Accept-Language).
export JEV_RA_LOCALE=en-US
# jev-ra never invents a field value. Without a text helper, every task that has to type
# something escalates `needs_value` instead of doing it.
export JEV_RA_TEXT_MODEL=openai/gpt-4o-mini
export JEV_RA_TEXT_BASE_URL=https://openrouter.ai/api/v1
export JEV_RA_TEXT_API_KEY="$OPENROUTER_API_KEY"

# A Chrome of your own. The language flags are jev-ra's own now, and are repeated here only so the
# browser and the session agree from the first request. If another jev-ra session is already
# holding a browser, give this one its own daemon with BH_RUNTIME_DIR, or `Session()` refuses.
chrome --remote-debugging-port=9222 --user-data-dir="$(mktemp -d)" \
  --window-size=1280,900 --lang=en-US --accept-lang=en-US,en about:blank &
export BU_CDP_URL=http://127.0.0.1:9222
export BH_RUNTIME_DIR="$(mktemp -d)"

uv run python -m bench.public.om2w --tasks 10 --out bench/public/runs/om2w-$(date +%F) --judge
uv run python -m bench.public.webvoyager --tasks 10 --out bench/public/runs/webvoyager-$(date +%F) --judge
```

`--judge-only --out <dir>` re-judges a directory without running anything. `--task-id` runs one
named task. `--level easy|medium|hard` narrows Online-Mind2Web. Ten tasks are drawn one difficulty
at a time (Online-Mind2Web) or one site at a time (WebVoyager), so the same ten come back on the
next run and a smoke is not all easy or all Allrecipes.

### Where the tasks come from

Online-Mind2Web's 300 tasks live in a **gated** Hugging Face dataset. With `HF_TOKEN` in the
environment the runner downloads that file. Without one it falls back to a public mirror pinned to
one commit - the copy the ABP submission published - and says so in a warning. That mirror carries
the 2026-01-02 task revision; the gated file has had one revision since (6 tasks, 2026-05-15), so
a number measured from the mirror is not measured on the leaderboard's exact task set. The runs
below used the mirror.

WebVoyager's 643 tasks are in its own repository, fetched at the pinned commit.

| repository | commit |
|---|---|
| `OSU-NLP-Group/Online-Mind2Web` | `f0d805ee0e9e0b3ea70911e45e5264b72968f3dc` |
| `MinorJerry/WebVoyager` | `5a7896738c10bfb8b9edccce6bb0e0411f8ae569` |
| task-file mirror `theredsix/abp-online-mind2web-results` | `c30614d7e1ddf345b7ed5cc8591da8f72b7ca065` |

## The numbers

### Scores to beat

| system | Online-Mind2Web | judged by | tasks |
|---|---|---|---|
| ABP + Claude Opus 4.6 | **90.53 %** | human evaluators | 285 of 300, impossible tasks excluded (86.00 % over all 300) |
| Hark Handoff | 95.3 % | leaderboard's `auto_o4-mini` sheet | 300 |
| ACT-2 (GPT-5.4) | 92.3 % | leaderboard's `auto_o4-mini` sheet | 300 |
| Browser Use (gpt-4o) | 26 % | leaderboard's `auto_o4-mini` sheet | 300 |
| **jev-ra 0.1.3** | **30 % (3/10)** | WebJudge (o4-mini), unmodified prompts | **10, a smoke** |
| **jev-ra, after the four fixes** | **30 % and 20 % (3/10, 2/10)** | the same WebJudge, same ten tasks | **10, twice** |

WebVoyager is saturated - the field reports up to 99.19 % - so it is a regression gate here, not a
score. Each pass is ten tasks run back to back, and its own evaluator scored them:

| WebVoyager | pass A | pass B |
|---|---|---|
| before the fixes | **3 / 10** | **0 / 10** |
| after the fixes | **4 / 10** | **3 / 10** |

On ten live tasks the spread between two passes of the same agent is larger than the gap between
most leaderboard entries, which is still the single most important thing this page has to say about
a ten-task number: before the fixes two passes differed by three tasks, after them by one.

### What the Online-Mind2Web runs actually did

What ended each run, by jev-ra's own status:

| outcome | before | after A | after B | what it means |
|---|---|---|---|---|
| `blocked` | 5 | 4 | 3 | the model saw no supported operation that would progress |
| `stuck_loop` | 2 | 2 | 2 | three steps in a row moved nothing |
| `done` | 1 | 3 | 3 | jev-ra verified the goal on the page |
| `blocked_by_site` | 0 | 1 | 1 | the host refused the browser instead of serving a page |
| `unverified_done` | 0 | 0 | 1 | DONE the model could not confirm on the page |
| `needs_value` | 1 | 0 | 0 | a field wanted a value the text helper could not write |
| `provider_error` | 1 | 0 | 0 | the decision endpoint timed out mid-run |

Before the fixes, two of the five `blocked` runs never saw a website at all: carvana.com answered
with Cloudflare's *Sorry, you have been blocked* and marriott.com with Akamai's *Access Denied*,
both on the first request, both in 0 steps, and both were reported as the task being impossible.
carvana refused both reruns the same way and is now reported as `blocked_by_site` in 0 steps and
0 decisions. marriott served the real site to both reruns, so its refusal is not in these numbers
and could not be re-measured. That failure class is what `docs/ROADMAP_COMMERCIAL.md` Track B names.

The judge and jev-ra disagree in both directions, and the disagreement did not settle down:

| task | before | after A | after B |
|---|---|---|---|
| `ade4c09ad3fdb1607209750924cd232f` | `done`, **PASS** | `done`, **PASS** | `done`, **PASS** |
| `4091bdd3fa64a5b0d912bc08eaf9c824` | `blocked`, **PASS** | `done`, FAIL | `done`, FAIL |
| `046138801a05ddf56ad94e8672942496` | `provider_error`, **PASS** | `blocked`, FAIL | `unverified_done`, FAIL |
| `fb7b4f784cfde003e2548fdf4e8d6b4f` | not published | `done`, **PASS** | `done`, **PASS** |
| `561693d6eec7bbfba3fefe9e4b26decb` | not published | `stuck_loop`, **PASS** | `stuck_loop`, FAIL |

`4091bdd3` is the clearest single case on this page: WebJudge passed the run that gave up on the
MTA maps page and failed both runs that reached the same page, verified the goal on it and wrote
out the list of Brooklyn maps as a final answer. Nothing about the judge was changed between them.

### What the WebVoyager runs did

Four passes over the same ten sites, two before the fixes and two after:

| task | before A | before B | after A | after B |
|---|---|---|---|---|
| Allrecipes--0 | `blocked`, FAIL | `blocked`, FAIL | `blocked`, FAIL | `blocked`, FAIL |
| Amazon--0 | `done`, FAIL | `done`, FAIL | `blocked`, FAIL | `done`, FAIL |
| Apple--0 | `blocked`, **PASS** | `provider_error`, FAIL | `done`, **PASS** | `blocked`, **PASS** |
| ArXiv--0 | `ChromeError`, FAIL | `ChromeError`, FAIL | `done`, **PASS** | `done`, **PASS** |
| BBC News--0 | `blocked`, FAIL | `blocked`, FAIL | `blocked`, FAIL | `blocked`, FAIL |
| Booking--33 | `blocked`, **PASS** | `blocked`, FAIL | `done`, **PASS** | `blocked`, FAIL |
| Cambridge Dictionary--0 | `stuck_loop`, FAIL | `blocked`, FAIL | `blocked`, FAIL | `blocked`, FAIL |
| Coursera--0 | `done`, **PASS** | `stuck_loop`, FAIL | `done`, **PASS** | `stuck_loop`, FAIL |
| ESPN--0 | `blocked`, FAIL | `blocked`, FAIL | `blocked`, FAIL | `blocked`, **PASS** |
| GitHub--0 | `needs_value`, FAIL | `done`, FAIL | `done`, FAIL | `done`, FAIL |
| | **3 / 10** | **0 / 10** | **4 / 10** | **3 / 10** |

`ArXiv--0` is the one row that moved for a reason and stayed moved: it failed both earlier passes
with `ChromeError: Runtime.evaluate timed out after 5s` and passes both reruns. Its Enter step now
takes 69 s of settle on arxiv.org's listing, which is exactly the wait the 5 s budget cut short.

Everything else still says what it said before. Four of the twenty reruns ended `done` and the
evaluator agreed with three of them; three of its seven PASSes went to runs that had given up. A
run can verify its goal and still not have done what the task asked, and a run that stopped can
still have left the answer on screen.

### Cost and wall, measured

| measurement | Online-Mind2Web, before | after A | after B | WebVoyager, before | after A | after B |
|---|---|---|---|---|---|---|
| jev-ra cost, whole pass | **$0.0122** | **$0.0103** | **$0.0117** | **$0.0078**, **$0.0074** | **$0.0099** | **$0.0119** |
| wall, whole pass | 178 s | 150 s | 175 s | 113 s, 114 s | 180 s | 163 s |
| decisions / steps | 91 / 76 | 77 / 63 | 83 / 63 | see `summary.jsonl` | 63 / 42 | 71 / 56 |
| text-helper calls | 2 | 7 | 6 | 5 (first pass) | 9 | 7 |
| screenshots written | 96 | 83 | 83 | 53, 43 | 55 | 66 |

Two of those columns moved for a reason and not by chance. The WebVoyager wall went **up** by about
50 s a pass because `ArXiv--0` now waits out a settle it used to die in: one task spends 69 s where
it used to spend 5 s and then end the run. And the text-helper calls went up because a question-
shaped goal now asks for a final answer as well as for field values - one extra call on the 4 of 10
Online-Mind2Web tasks and the 1 of 10 WebVoyager tasks that read as questions, including on a task
that ended on a wall, where the helper is asked about a page that cannot answer and says so.

**The judges' own cost is not measured.** Neither harness records the usage its calls report, and
this lane does not patch them to. What is exact is the call count: WebJudge makes one key-point
call, one call per screenshot, and one verdict call per task (96 screenshots over the ten tasks);
the WebVoyager evaluator makes one call per task with its last 15 screenshots attached. A 300-task
Online-Mind2Web pass at this rate costs jev-ra about **$0.37** in decisions; the judge is the larger
bill and is unmeasured. The brief's figure of about $5 for a WebVoyager pass is the field's, not
ours: we have not run 643 tasks.

### Where the trajectories are

Under `bench/public/runs/`, gitignored, one directory per pass:

```
om2w-2026-09-22/<task_id>/result.json        # the v2 submission document
om2w-2026-09-22/<task_id>/trajectory/*.jpg   # one frame per step
om2w-2026-09-22/summary.jsonl                # one row per task: status, cost, run_id, page seen
om2w-2026-09-22-judge/...                    # WebJudge's own results file, one JSON per line
om2w-2026-09-22-judge.log                    # what the judge printed
om2w-2026-09-22-fixed/, -fixed-b/            # the two reruns, same ten tasks, and their -judge dirs

webvoyager-2026-09-22/task<id>/interact_messages.json
webvoyager-2026-09-22/task<id>/screenshot<n>.png
webvoyager-2026-09-22/skipped.json           # the time-sensitive tasks held back, with the date each named
webvoyager-2026-09-22-b/...                  # the second pass over the same ten
webvoyager-2026-09-22-fixed/, -fixed-b/      # the two reruns
```

`summary.jsonl` carries the `run_id` of every attempt, so `uv run jev-ra trace <run_id>` replays
any of them step by step.

## The judges, and what had to be worked around

Both judges are the ones the benchmarks publish. Their prompts, their score thresholds and their
label extraction are untouched. Four things had to be worked around to run them at all, and all
four are visible in the code:

1. **WebJudge's worker pool cannot start on macOS.** `src/run.py` hands each
   `multiprocessing.Process` the live `OpenaiEngine`; macOS spawns rather than forks, so the
   arguments are pickled, and an OpenAI client holds an `_thread.RLock`. `webjudge_runner.py`
   calls the repository's own `auto_eval` in one process instead.
2. **WebJudge's 512-token ceiling is the whole budget for a reasoning model.** `OpenaiEngine`
   fixes `max_new_tokens=512`, and the benchmark asks for o4-mini. Measured on one key-point call:
   394 completion tokens, 320 of them reasoning. A task that needs a little more comes back with no
   content and the judge dies on `NoneType.replace`. The ceiling is raised to 4096 and an empty
   answer becomes an empty string, which the repository's own extractor scores as a failure.
3. **The output filename carries the model name**, and an OpenRouter model name has a slash in it,
   so the directory that slash implies is created before the harness opens the file.
4. **WebVoyager's evaluator names `gpt-4-vision-preview`**, which OpenAI has retired. The same
   prompt, the same 15 screenshots and the same verdict rule run on `gpt-4o`.

Both judges are reached over OpenRouter by setting `OPENAI_BASE_URL`; neither harness is edited to
do it.

## What jev-ra hands the judge, and what it does not

- **One sentence on a question, nothing on an instruction.** A goal that reads as a question - it
  ends in `?`, or opens with what, which, how many, when, who or find the - now gets one sentence
  from jev-ra's configured text helper, taken from the page the run finished on. It is carried in
  `agent_final_answer` and on the submission's `TASK_COMPLETE; ANSWER:` line, and in the `ANSWER`
  the WebVoyager evaluator reads. An instruction never asks for one, and without a text helper the
  field stays `null` and the run's payload says which of the two it was. WebJudge does not read
  that field at all, so on Online-Mind2Web this changes what the submission says and not what the
  judge scores; on these twenty tasks 5 read as questions, so it is a small surface either way.
- **No thoughts.** Every step's `thought` is `null`, present and explicit, because jev-ra's
  decision is a probability over an enumerated action space, not a sentence.
- **Refs, not coordinates.** jev-ra deliberately never sends the model geometry, so a step's target
  is rendered in the schema's selector slot as `[data-jev-ref='e12']`, which is jev-ra's own
  observation ref. It is not a DOM attribute. The judges read the action strings as text.
- **SUCCESS or FAILED is measured, not claimed.** A step is `SUCCESS` when jev-ra's own
  deterministic check saw the page change - marker, url, title, text or field state - and `FAILED`
  when it did not. `WAIT` carries no status, as the schema says it should not.
- **One screenshot per landed step, and never one out.** The adapter photographs through a session
  that sits between the agent and Chrome: an action that returns marks a frame due, the observation
  that settles takes it, and an action that raised marks nothing.

## Known limits of these numbers

- Ten tasks. The run-to-run spread on live sites is larger than the difference between most
  leaderboard entries, and it is what most of the movement between any two passes here is.
- Site walls. carvana.com refused the browser outright from this address in every pass. It is now
  reported as `blocked_by_site` rather than as a task that failed, which is a truer row and not a
  passed task: the wall class itself is untouched.
- The address, not the language. uniqlo.com answered `https://www.uniqlo.com/` with
  `https://www.uniqlo.com/kr/ko/` on every pass, and does so whether the session asks for `en-US`
  or `ja-JP`, so its Korean pages are this machine's address and not its `Accept-Language`. The
  locale fix moved flightaware.com to English and did not move uniqlo.
- The mirror is one task revision behind the gated file. No `HF_TOKEN` was in the environment for
  any pass on this page, before or after, so every one of them used the pinned mirror.
- The judges' cost is unmeasured, as above.

## Reproducing the CI smoke

`.github/workflows/public-bench.yml` runs three tasks of each on demand
(`workflow_dispatch`), with a key from repository secrets, and uploads every trajectory. It never
runs on a push. Its numbers are lower than the ones here and are not published: it drives a
headless Chrome from a datacentre address, which many of these sites wall on sight. It proves the
path, not the score.
