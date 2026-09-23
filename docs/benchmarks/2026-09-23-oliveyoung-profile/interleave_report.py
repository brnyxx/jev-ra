import json
import statistics
import sys

rows = [json.loads(line) for line in open(sys.argv[1])]
tasks = []
for row in rows:
    if row["task"] not in tasks:
        tasks.append(row["task"])
sys.stdout.write(f"{'task':<16} {'main ok':>8} {'main median':>12} {'branch ok':>10} {'branch median':>14}\n")
for task in tasks:
    parts = []
    for tree in ("main", "branch"):
        mine = [r for r in rows if r["task"] == task and r["tree"] == tree]
        good = [r["ms"] for r in mine if r["ok"]]
        parts.append((f"{len(good)}/{len(mine)}", statistics.median(good) if good else None))
    sys.stdout.write(f"{task:<16} {parts[0][0]:>8} {parts[0][1]!s:>12} {parts[1][0]:>10} {parts[1][1]!s:>14}\n")
for task in tasks:
    per = {}
    for r in rows:
        if r["task"] == task:
            per.setdefault(r["round"], {})[r["tree"]] = r["ms"] if r["ok"] else None
    sys.stdout.write(f"{task}: " + " | ".join(f"r{k} main {v.get('main')} branch {v.get('branch')}" for k, v in sorted(per.items())) + "\n")
