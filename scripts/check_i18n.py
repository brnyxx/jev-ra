"""Check that every translation still matches what it translates.

For the READMEs: structure, commands and numbers must agree; the prose is expected to differ. For
the landing page, whose copy lives in `docs/assets-site/i18n.js`, every key the page asks for has
to exist in all three locales, or the page falls back to English mid-sentence. Run with `--check`
in CI; without it, the same report is printed and the exit code still says whether it passed.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGLISH = ROOT / "README.md"
TRANSLATIONS = ("docs/i18n/README.ko.md", "docs/i18n/README.ja.md", "docs/i18n/README.zh-CN.md")
PAGE_COPY = ROOT / "docs" / "assets-site" / "i18n.js"
LOCALES = ("ko", "ja", "zh-CN")
# The table and the copy are javascript object literals in a file the browser loads as-is, so they
# are read by the engine that will read them for real rather than by a second parser here.
READ_KEYS_JS = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const cut = (marker, open, close) => {
  const at = src.indexOf(marker);
  if (at < 0) throw new Error("no " + marker + " in this file");
  const from = src.indexOf(open, at);
  let depth = 0, quote = null;
  for (let i = from; i < src.length; i++) {
    const c = src[i];
    if (quote) { if (c === "\\") i++; else if (c === quote) quote = null; continue; }
    if (c === '"' || c === "'" || c === "`") { quote = c; continue; }
    if (c === open) depth++;
    else if (c === close && !--depth) return src.slice(from, i + 1);
  }
  throw new Error("unbalanced " + marker);
};
const MAP = eval(cut("const MAP", "[", "]"));
const D = eval("(" + cut("const D", "{", "}") + ")");
const keys = MAP.map((pair) => pair[0]);
const missing = {};
for (const locale of process.argv.slice(2)) missing[locale] = keys.filter((k) => !(k in (D[locale] || {})));
console.log(JSON.stringify({ keys: keys.length, missing }));
"""
# Thousands separators, dollar amounts, and ratios written with the multiplication sign.
TIMES = "\u00d7"
NUMBER = re.compile(rf"\b\d{{1,3}}(?:,\d{{3}})+|\$\d+\.\d{{4,}}|\b\d+\.\d{{1,2}}{TIMES}")
MEASUREMENT = re.compile(rf"\d[\d,.]*\s?(?:ms|s|x|{TIMES}|%)(?![A-Za-z0-9])")


def headings(text):
    return re.findall(r"^## (.+)$", text, re.MULTILINE)


def commands(text):
    """Every shell line inside a fenced sh block, which must be identical in every language."""
    found = []
    for block in re.findall(r"```sh\n(.*?)```", text, re.DOTALL):
        for line in block.splitlines():
            stripped = line.split("#")[0].strip()
            if stripped:
                found.append(stripped)
    return found


def numbers(text):
    return sorted(set(NUMBER.findall(text)) | set(MEASUREMENT.findall(text)))


def compare(english, other):
    """Everything that must match between the English README and a translation."""
    problems = []
    if len(headings(english)) != len(headings(other)):
        problems.append(f"{len(headings(other))} sections against {len(headings(english))} in English")
    if commands(english) != commands(other):
        missing = [line for line in commands(english) if line not in commands(other)]
        extra = [line for line in commands(other) if line not in commands(english)]
        if missing:
            problems.append(f"missing commands: {missing}")
        if extra:
            problems.append(f"commands that are not in the English README: {extra}")
    if numbers(english) != numbers(other):
        missing = [item for item in numbers(english) if item not in numbers(other)]
        extra = [item for item in numbers(other) if item not in numbers(english)]
        if missing:
            problems.append(f"missing numbers: {missing}")
        if extra:
            problems.append(f"numbers that are not in the English README: {extra}")
    return problems


def page_copy(path=PAGE_COPY, locales=LOCALES):
    """Every landing-page key that a locale does not translate, or why the check could not run."""
    if not path.exists():
        return [f"{path.relative_to(ROOT)} is missing"]
    node = shutil.which("node")
    if node is None:
        return ["node is needed to read the landing page copy; install node or run this locally"]
    done = subprocess.run([node, "-e", READ_KEYS_JS, str(path), *locales], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        return [f"{path.relative_to(ROOT)}: {done.stderr.strip().splitlines()[-1] if done.stderr else 'unreadable'}"]
    read = json.loads(done.stdout)
    return [
        f"{locale} is missing {len(keys)} of {read['keys']} keys: {keys[:5]}"
        for locale, keys in read["missing"].items()
        if keys
    ]


def report(paths=TRANSLATIONS):
    """One (path, problems) pair per translation."""
    english = ENGLISH.read_text()
    return [(name, compare(english, (ROOT / name).read_text())) for name in paths]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="check_i18n", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="kept for symmetry; the exit code always says")
    parser.parse_args(argv)
    failed = False
    for name, problems in report():
        if problems:
            failed = True
            print(f"{name}:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
        else:
            print(f"{name}: in sync with README.md")
    problems = page_copy()
    if problems:
        failed = True
        print(f"{PAGE_COPY.relative_to(ROOT)}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
    else:
        print(f"{PAGE_COPY.relative_to(ROOT)}: every page key is translated in {', '.join(LOCALES)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
