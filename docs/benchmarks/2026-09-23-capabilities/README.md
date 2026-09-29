# Capability matrix, 2026-09-23

Thirty-one kinds of web interaction, each on a local fixture page under `tests/fixtures/sites/`, listed with its goal,
its plan and the page check that proves it in `tests/fixtures/capabilities.toml`. `capabilities.py` runs the catalog
scripted (the plan answers every question; does the mechanism work at all) or live (the model decides; does it pick
the mechanism), and writes one row per run. A run counts only when the page check holds and the run ended the way
the entry accepts: `done`, or for a pattern jev-ra does not carry out, the escalation that says so.

- `scripted-before.jsonl` - main at `cb2ce51`, the final catalog and fixtures, one run each: **12 / 31**
- `scripted-after.jsonl` - this branch rebased on `cb2ce51`, the same catalog, one run each: **31 / 31**
- `live-before.jsonl` - the lane's base `7816fec`, the first catalog, three runs each through the TypeSafe direct
  route: **31 / 93**. Several entries changed after it was taken: the feed, load-more and pop-up pages were made
  more realistic, and the drag, right-click, hover-only and cross-origin frame entries now expect an escalation
  instead of `done`.

The live column after the fixes comes from the three-run check each fix was measured with before it was committed,
on the branch before its rebase; the numbers are the ones quoted in each commit message. Those raw rows were kept in
a scratch directory that was cleared before they were copied here, and the key file for the live route went with
it, so they are not in this folder and were not re-measured after the rebase.

| pattern | scripted main | scripted branch | live before | live after | what is left |
|---|---|---|---|---|---|
| same-origin iframe form | pass | pass | 3/3 | not re-run | |
| cross-origin payment frame | pass | pass | 0/3 | not re-run | not supported: the escalation names the frame and its host in `detail.frames` |
| web-component form | fail: slotted name | pass | 3/3 | 3/3 | before, the button was pressed as "button" |
| web-component search, Enter | fail | pass | 0/3 | 3/3 | |
| rich-text editor | pass | pass | 2/3 | 0/3 | decision: DONE at 0.53-0.59 under the 0.6 bar; main measures the same |
| chat composer, Enter | fail | pass | 0/3 | 3/3 | |
| ARIA listbox | pass | pass | 3/3 | not re-run | |
| `<select multiple>` | fail | pass | 0/3 | 2/3 | decision: asked alone, SELECT leads BLOCKED by 0.45 to 0.42 |
| radio cards and a switch | fail | pass | 0/3 | 3/3 | |
| file upload | fail | pass | 0/3 | 3/3 | escalates `needs_file`; no file is chosen |
| alert | fail: hangs | pass | 3/3 | not re-run | |
| confirm | fail: hangs | pass | 0/3 | 3/3 | |
| prompt | fail: hangs | pass | 0/3 | 0/3 | the folder is made 3/3; decision: DONE under the bar |
| stacked modals | pass | pass | 3/3 | not re-run | |
| Escape closes a palette | fail | pass | 1/3 | 3/3 | |
| infinite scroll | fail | pass | 1/3 | 0/3 | decision: BLOCKED at the end of a feed still loading, where WAIT fits |
| load more | fail | pass | 0/3 | 2/3 | |
| virtualized list | fail | pass | 0/3 | 3/3 | |
| inner scroll container | fail | pass | 0/3 | 3/3 | |
| sign-in pop-up | fail | pass | 0/3 | 0/3 | signs in 3/3; decision: DONE at about 0.37 on "Signed in as Ada Lovelace." |
| tabs and accordion | pass | pass | 3/3 | not re-run | |
| client-side table | pass | pass | 0/3 | 2/3 | decision: Page 2 pressed before sorting, which returns to page 1 |
| native date, time, number | fail | pass | 0/3 | 3/3 | |
| native range and colour | fail | pass | 0/3 | 1/3 | decision: the size value paired with the colour field, refused as `needs_value` |
| ARIA slider | fail | pass | 0/3 | 3/3 | |
| native validation | pass | pass | 3/3 | not re-run | |
| inline validation | pass | pass | 3/3 | not re-run | |
| download link | fail: not reported | pass | 0/3 | 3/3 | |
| hover-only row actions | pass | pass | 0/3 | 3/3 | not supported: `blocked`; the entry now expects it |
| right-click menu | pass | pass | 3/3 | 3/3 | not supported: `blocked` |
| drag and drop | pass | pass | 0/3 | 3/3 | not supported: `blocked` or `stuck_loop`; the entry now expects it |

"not re-run" marks an entry that was not measured live after the fixes. Reproduce with:

```sh
uv run python docs/benchmarks/2026-09-23-capabilities/capabilities.py scripted out.jsonl
TYPESAFE_API_KEY=... uv run python docs/benchmarks/2026-09-23-capabilities/capabilities.py live out.jsonl --runs 3
```

The runner points the test browser's downloads at a folder of its own, so a run never saves into the Downloads
folder of whoever runs it.
