"""Two renderings of one stored run: the step table a terminal prints, and a page to send someone."""

import json

from .profile import CATEGORIES, clip

LABEL_CHARS = 32
TEXT_CHARS = 20
COLUMNS = ("n", "operation", "target", "text", "p", "decide", "total", "page")


def rows(payload):
    """One row per step, in the order they were taken."""
    return [
        {
            "n": str(step.get("n", "")),
            "operation": step.get("operation", ""),
            "target": clip(step.get("target_label"), LABEL_CHARS),
            "text": clip(step.get("text"), TEXT_CHARS),
            "p": f"{step.get('probability') or 0:.2f}",
            "decide": f"{step.get('decide_ms') or 0}",
            "total": f"{step.get('total_ms') or 0}",
            "page": "changed" if step.get("page_changed") else "same",
        }
        for step in payload.get("steps", [])
    ]


def table(payload):
    """The run as lines a terminal prints: what it was, every step, and what it cost."""
    body = rows(payload)
    widths = {name: max(len(name), *(len(row[name]) for row in body)) if body else len(name) for name in COLUMNS}
    header = "  ".join(name.ljust(widths[name]) for name in COLUMNS)
    lines = [
        f"run {payload.get('run_id', '')} · {payload.get('status', '')} · {payload.get('reason', '')}",
        f"{payload.get('title', '')} — {payload.get('url', '')}".strip(" —"),
        "",
        header,
        "-" * len(header),
    ]
    lines += ["  ".join(row[name].ljust(widths[name]) for name in COLUMNS) for row in body]
    lines += [
        "",
        f"{len(body)} steps, {payload.get('decisions', 0)} decisions,"
        f" {len(payload.get('text_calls') or [])} text calls,"
        f" {payload.get('elapsed_ms', 0)} ms, ${payload.get('cost', 0.0):.6f}",
    ]
    detail = (payload.get("detail") or {}).get("error")
    if detail:
        lines.append(f"detail: {detail}")
    return lines


def embed(payload):
    """The run as a JSON literal no page content can break out of."""
    raw = json.dumps(payload, ensure_ascii=False)
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


TEMPLATE = """<!doctype html>
<title>jev-ra run {run_id}</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{ color-scheme: light dark; --ink: #10131a; --paper: #fbfbfd; --dim: #6b7280; --line: #e3e5ea;
  --amber: #b45309; --cyan: #0e7490; --good: #15803d; }}
@media (prefers-color-scheme: dark) {{ :root {{ --ink: #e8eaf0; --paper: #0d1117; --dim: #98a1b3;
  --line: #232833; --amber: #f0b429; --cyan: #22d3ee; --good: #4ade80; }} }}
body {{ margin: 0; padding: 2rem 1.25rem; background: var(--paper); color: var(--ink);
  font: 14px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace; }}
main {{ max-width: 60rem; margin: 0 auto; }}
h1 {{ font-size: 1.1rem; margin: 0 0 .25rem; }}
.dim {{ color: var(--dim); }}
.facts {{ display: flex; flex-wrap: wrap; gap: 1.25rem; margin: 1rem 0 1.5rem; }}
.facts div b {{ display: block; font-size: 1.25rem; font-weight: 600; }}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid var(--line); white-space: nowrap; }}
th {{ color: var(--dim); font-weight: 500; }}
td.op {{ color: var(--amber); }}
td.txt {{ color: var(--cyan); }}
td.num {{ text-align: right; }}
.bar {{ display: flex; height: 8px; min-width: 9rem; border-radius: 4px; overflow: hidden; background: var(--line); }}
.bar span {{ display: block; }}
.legend {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: .75rem 0 0; font-size: 12px; }}
.legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: .35rem; }}
footer {{ margin-top: 2rem; color: var(--dim); font-size: 12px; }}
</style>
<main>
  <h1 id="head"></h1>
  <p class="dim" id="where"></p>
  <div class="facts" id="facts"></div>
  <div class="scroll"><table><thead id="thead"></thead><tbody id="body"></tbody></table></div>
  <div class="legend" id="legend"></div>
  <footer id="foot"></footer>
</main>
<script>
const RUN = {run};
const CATEGORIES = {categories};
const COLOURS = ["#7c3aed", "#0891b2", "#b45309", "#be123c", "#0f766e", "#64748b"];
const COLUMNS = ["step", "operation", "target", "text", "p", "decide ms", "total ms", "page", "where the time went"];
const el = (tag, parent, text, cls) => {{
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  if (parent) parent.appendChild(node);
  return node;
}};
document.getElementById("head").textContent =
  "run " + RUN.run_id + " · " + RUN.status + " · " + RUN.reason;
document.getElementById("where").textContent = [RUN.title, RUN.url].filter(Boolean).join(" — ");
const facts = document.getElementById("facts");
for (const [label, value] of [
  ["steps", RUN.steps.length],
  ["decisions", RUN.decisions],
  ["wall", (RUN.elapsed_ms / 1000).toFixed(1) + " s"],
  ["cost", "$" + (RUN.cost || 0).toFixed(6)],
  ["text calls", (RUN.text_calls || []).length],
]) {{
  const cell = el("div", facts);
  el("b", cell, value);
  el("span", cell, label, "dim");
}}
const headRow = el("tr", document.getElementById("thead"));
for (const name of COLUMNS) el("th", headRow, name);
const body = document.getElementById("body");
for (const step of RUN.steps) {{
  const row = el("tr", body);
  el("td", row, step.n, "num");
  el("td", row, step.operation, "op");
  el("td", row, step.target_label || "");
  el("td", row, step.text || "", "txt");
  el("td", row, (step.probability || 0).toFixed(2), "num");
  el("td", row, step.decide_ms || 0, "num");
  el("td", row, step.total_ms || 0, "num");
  el("td", row, step.page_changed ? "changed" : "same", "dim");
  const bar = el("div", el("td", row), null, "bar");
  const total = step.total_ms || 1;
  CATEGORIES.forEach((name, index) => {{
    const part = step[name] || 0;
    if (!part) return;
    const piece = el("span", bar);
    piece.style.width = (100 * part / total) + "%";
    piece.style.background = COLOURS[index % COLOURS.length];
    piece.title = name.replace("_ms", "") + " " + part + " ms";
  }});
}}
const legend = document.getElementById("legend");
CATEGORIES.forEach((name, index) => {{
  const item = el("span", legend);
  el("i", item).style.background = COLOURS[index % COLOURS.length];
  item.appendChild(document.createTextNode(name.replace("_ms", "")));
}});
document.getElementById("foot").textContent =
  "jev-ra trace " + RUN.run_id + " · one Jev decision per step · nothing typed that was not supplied";
</script>
"""


def page(payload):
    """The whole run as one self-contained page: no script, style or font it has to fetch."""
    return TEMPLATE.format(
        run_id=payload.get("run_id", ""),
        run=embed(payload),
        categories=json.dumps(list(CATEGORIES)),
    )
