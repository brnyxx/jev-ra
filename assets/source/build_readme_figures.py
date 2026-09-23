"""The landing page's two animated figures as standalone SVG files a README can show.

GitHub strips inline <svg> from a README but renders an SVG file behind <img>, CSS animation
included. The architecture diagram is lifted from docs/index.html as it is; the step pipeline is
redrawn from the page's node texts, icons and timings. Re-run after editing the page:

    python3 assets/source/build_readme_figures.py
"""

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = (ROOT / "docs" / "index.html").read_text()
OUT = ROOT / "assets"

INK, SLATE, PAPER, AMBER, CYAN, MUTED, DIM = "#070A0F", "#0E141D", "#F6F4EF", "#FFB703", "#3DE8FF", "#AEB6C2", "#6B7482"
SANS = "ui-sans-serif,-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
STILL = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"


def symbols(names):
    """The page's logo symbols the figure refers to, copied as they are."""
    found = []
    for name in names:
        match = re.search(rf'<symbol id="{name}".*?</symbol>', PAGE, re.S)
        if match:
            found.append(match.group(0))
    return "".join(found)


def architecture():
    body = re.search(r'<div class="arch">\s*<svg viewBox="0 0 1100 430"[^>]*>(.*?)</svg>', PAGE, re.S).group(1)
    body = re.sub(r"<!--.*?-->", "", body)
    used = sorted(set(re.findall(r'href="#(i-[a-z]+)"', body)))
    style = (
        f"text{{fill:{PAPER};font-size:14px;font-family:{SANS}}}"
        ".box{fill:rgba(14,20,29,.9);stroke:rgba(246,244,239,.18);stroke-width:1.2}"
        ".core{fill:rgba(255,183,3,.04);stroke:rgba(255,183,3,.55)}"
        ".inner{fill:rgba(4,7,11,.7);stroke:rgba(246,244,239,.14)}"
        ".h{font-weight:700;font-size:16px}"
        f".s{{fill:{MUTED};font-size:12px}}"
        f".m{{fill:{DIM};font-size:11.5px;font-family:{MONO}}}"
        f".lbl{{fill:{AMBER};font-size:11.5px;font-family:{MONO}}}"
        ".wire{fill:none;stroke:rgba(246,244,239,.22);stroke-width:1.6}"
        f".flow{{fill:none;stroke:{AMBER};stroke-width:2;stroke-dasharray:6 10;animation:dash 1.6s linear infinite}}"
        f".flow.back{{animation-direction:reverse;stroke:{CYAN}}}"
        "@keyframes dash{to{stroke-dashoffset:-32}}"
        f".logo{{fill:{PAPER}}}" + STILL
    )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 430" width="1100" height="430" role="img" '
        'aria-label="jev-ra architecture: your agent talks to jev-ra over MCP; jev-ra drives Chrome over the '
        'DevTools Protocol and asks TypeSafe Jev over HTTPS once per step">'
        f"<style>{style}</style><defs>{symbols(used)}</defs>"
        f'<rect width="1100" height="430" rx="10" fill="{INK}"/>{body}</svg>\n'
    )
    (OUT / "readme-architecture.svg").write_text(svg)


def nodes():
    pipe = PAGE[PAGE.index('<div class="pipe"') : PAGE.index('<div class="bars"')] + "</div>"
    found = []
    for node in re.findall(r'<div class="node">(.*?)</div>\s*(?=<div class="node">|</div>\s*$)', pipe, re.S):
        icon = re.search(r'<svg class="pi"[^>]*>(.*?)</svg>', node, re.S).group(1)
        title = re.search(r"<h3>(.*?)</h3>", node, re.S).group(1)
        timing = re.search(r'class="ms">(.*?)<', node, re.S).group(1)
        found.append((icon, html.unescape(title), html.unescape(timing)))
    return found


CAPTIONS = (
    ("one snapshot.js call:", "text + every control"),
    ("one Jev request,", "five typed questions"),
    ("guard re-checked,", "trusted Input event"),
    ("before vs after diffed,", "loops detected"),
    ("DONE only when verified,", "else a reason + candidates"),
)


def pipeline():
    parts = []
    width, top = 1100, 34
    step = width / 5
    for index, ((icon, title, timing), (line1, line2)) in enumerate(zip(nodes(), CAPTIONS)):
        cx = step * index + step / 2
        delay = index * 1.2
        parts.append(
            f'<g><rect class="dot" style="animation-delay:{delay}s" x="{cx - 36}" y="{top}" width="72" height="72" rx="6"/>'
            f'<svg x="{cx - 16}" y="{top + 20}" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="{AMBER}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{icon}</svg>'
            f'<text class="h" x="{cx}" y="{top + 106}">{html.escape(title)}</text>'
            f'<text class="ms" x="{cx}" y="{top + 128}">{html.escape(timing)}</text>'
            f'<text class="s" x="{cx}" y="{top + 152}">{html.escape(line1)}</text>'
            f'<text class="s" x="{cx}" y="{top + 169}">{html.escape(line2)}</text></g>'
        )
    bars = re.search(r'<div class="bars".*?</div>\s*</div>\s*</div>', PAGE, re.S).group(0)
    values = [re.sub(r"<[^>]+>", "", v) for v in re.findall(r'class="val">(.*?)</div>', bars)]
    seconds = [float(v.split()[0]) for v in values]
    legend = html.unescape(re.sub(r"<[^>]+>", "", re.search(r'<p class="legend">(.*?)</p>', PAGE[PAGE.index('<div class="bars"') :], re.S).group(1)))
    y = 250
    track_x, track_w = 250, 690
    rows = (
        ("browser-use", "flash_mode, gemini-3-flash", "bu", 1.0, values[0]),
        ("jev-ra", "Jev, one decision per step", "jr", seconds[1] / seconds[0], values[1]),
    )
    for row, (name, sub, cls, share, value) in enumerate(rows):
        ry = y + row * 58
        parts.append(
            f'<text class="bl" x="40" y="{ry + 16}">{name}</text><text class="m" x="40" y="{ry + 33}">{html.escape(sub)}</text>'
            f'<rect class="track" x="{track_x}" y="{ry}" width="{track_w}" height="24" rx="3"/>'
            f'<rect class="fill {cls}" x="{track_x}" y="{ry}" width="{track_w * share:.0f}" height="24" rx="3"/>'
            f'<text class="val" x="{width - 40}" y="{ry + 17}">{html.escape(value)}</text>'
        )
    words, lines = legend.split(), [""]
    for word in words:
        if len(lines[-1]) + len(word) + 1 > 128:
            lines.append("")
        lines[-1] = f"{lines[-1]} {word}".strip()
    for number, text in enumerate(lines):
        parts.append(f'<text class="m" x="40" y="{y + 138 + number * 17}">{html.escape(text)}</text>')
    style = (
        f"text{{fill:{PAPER};font-family:{SANS};text-anchor:middle}}"
        ".h{font-weight:700;font-size:17px}"
        f".ms{{fill:{AMBER};font-size:12px;font-family:{MONO}}}"
        f".s{{fill:{MUTED};font-size:12.5px}}"
        f".m{{fill:{DIM};font-size:11.5px;font-family:{MONO};text-anchor:start}}"
        ".bl{font-weight:700;font-size:15px;text-anchor:start}"
        f".val{{font-family:{MONO};font-size:14px;text-anchor:end}}"
        ".dot{fill:rgba(4,7,11,.9);stroke:rgba(246,244,239,.14);stroke-width:1.2;animation:light 6s linear infinite}"
        f"@keyframes light{{0%,4%{{stroke:rgba(246,244,239,.14)}}7%,18%{{stroke:{AMBER};stroke-width:2}}26%,100%{{stroke:rgba(246,244,239,.14)}}}}"
        ".line{stroke:rgba(255,183,3,.3);stroke-width:1}"
        f".pulse{{fill:{AMBER};animation:travel 6s linear infinite}}"
        f"@keyframes travel{{0%{{transform:translateX(0);opacity:0}}3%{{opacity:1}}92%{{transform:translateX({width - step:.0f}px);opacity:1}}100%{{transform:translateX({width - step:.0f}px);opacity:0}}}}"
        ".track{fill:rgba(4,7,11,.9);stroke:rgba(246,244,239,.12)}"
        ".fill{transform-box:fill-box;transform-origin:left;animation:grow 6s cubic-bezier(.2,.7,.2,1) infinite}"
        ".fill.bu{fill:#3a4250}.fill.jr{fill:#FFB703}"
        "@keyframes grow{0%{transform:scaleX(0)}80%{transform:scaleX(1)}92%{transform:scaleX(1);opacity:1}100%{transform:scaleX(1);opacity:0}}"
        + STILL
    )
    line = f'<line class="line" x1="{step / 2}" y1="{top + 36}" x2="{width - step / 2}" y2="{top + 36}"/>'
    pulse = f'<circle class="pulse" cx="{step / 2}" cy="{top + 36}" r="6"/>'
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 432" width="{width}" height="432" role="img" '
        'aria-label="How a step works: observe, decide, act, verify, finish or return; and wall time per step against browser-use">'
        f'<style>{style}</style><rect width="{width}" height="432" rx="10" fill="{INK}"/>'
        f"{line}{''.join(parts[:5])}{pulse}{''.join(parts[5:])}</svg>\n"
    )
    (OUT / "readme-step.svg").write_text(svg)


architecture()
pipeline()
