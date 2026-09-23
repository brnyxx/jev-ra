import re
import sys
from pathlib import Path

sp = Path(__file__).parent
out = Path(sys.argv[1])
svg = (sp / "zebra-trace.svg").read_text()
tx, ty, sx, sy = map(float, re.search(r"translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+),([-\d.]+)\)", svg).groups())
raw_paths = re.findall(r'<path d="([^"]+)"', svg)
W, H = map(float, re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups())
INK, PAPER, AMBER, WHITE = "#0B0F14", "#F6F4EF", "#FFB703", "#FFFFFF"
EYE = 9
FRAME = 6


def subpaths(d):
    toks = re.findall(r"[MmLlCcZz]|-?\d+(?:\.\d+)?", d)
    i, cur, cmd, pts, res = 0, None, None, [], []
    while i < len(toks):
        t = toks[i]
        if t in "MmLlCcZz":
            cmd = t
            i += 1
            if cmd in "Zz" and pts:
                res.append(pts)
                pts = []
            continue
        nums = []
        while i < len(toks) and toks[i] not in "MmLlCcZz":
            nums.append(float(toks[i]))
            i += 1
        step = {"M": 2, "m": 2, "l": 2, "c": 6}.get(cmd, 2)
        for k in range(0, len(nums), step):
            x, y = nums[k + step - 2], nums[k + step - 1]
            cur = (x, y) if cmd == "M" or cur is None else (cur[0] + x, cur[1] + y)
            pts.append(cur)
    if pts:
        res.append(pts)
    return res


def to_user(p):
    return (tx + sx * p[0], ty + sy * p[1])


# centers of the three title-bar dots (holes 1-3 of the frame path)
dots = []
for sub in subpaths(raw_paths[FRAME])[1:4]:
    pts = [to_user(p) for p in sub]
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area *= 0.5
    cx, cy = cx / (6 * area), cy / (6 * area)
    r = max(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x, y in pts)
    dots.append((cx, cy, r))

# The traced holes differ by a few units; the logo wants three identical circles on one baseline.
dots.sort()
_y = sum(d[1] for d in dots) / 3
_r = sum(d[2] for d in dots) / 3
_x0, _x2 = dots[0][0], dots[2][0]
dots = [(_x0 + (_x2 - _x0) * i / 2, _y, _r) for i in range(3)]


def figure(fill, accent, scale, dx, dy):
    body = "".join(f'<path fill="{accent if i == EYE else fill}" d="{d}"/>' for i, d in enumerate(raw_paths))
    marks = "".join(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r * 1.18:.1f}" fill="{accent}"/>' for cx, cy, r in dots)
    return (
        f'<g transform="translate({dx} {dy}) scale({scale})">'
        f'<g transform="translate({tx},{ty}) scale({sx},{sy})">{body}</g>{marks}</g>'
    )


FONT = "ui-sans-serif, -apple-system, 'Inter', 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

s = 860 / W
(out / "mark-dark.svg").write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024" role="img" aria-label="jev-ra">'
    f"{figure(PAPER, AMBER, s, (1024 - W * s) / 2, (1024 - H * s) / 2)}</svg>\n"
)
(out / "mark.svg").write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024" role="img" aria-label="jev-ra">'
    f"{figure(INK, AMBER, s, (1024 - W * s) / 2, (1024 - H * s) / 2)}</svg>\n"
)
s2 = 660 / W
(out / "mark-tile.svg").write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024" role="img" aria-label="jev-ra">'
    f'<rect width="1024" height="1024" rx="224" fill="{INK}"/>'
    f"{figure(PAPER, AMBER, s2, (1024 - W * s2) / 2, (1024 - H * s2) / 2)}</svg>\n"
)
s3 = 150 / H
(out / "logo.svg").write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 160" width="700" height="160" role="img" aria-label="jev-ra">'
    f"{figure(INK, AMBER, s3, 10, 5)}"
    f'<text x="216" y="114" font-family="{FONT}" font-size="100" font-weight="800" letter-spacing="-5" fill="{INK}">jev<tspan fill="{AMBER}">-</tspan>ra</text></svg>\n'
)
s4 = 440 / W
hero = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 800" width="1600" height="800" role="img" aria-label="jev-ra: browser use for coding agents, 4 to 8.5 times faster than browser-use">
  <defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{INK}"/><stop offset="1" stop-color="#151B24"/></linearGradient></defs>
  <rect width="1600" height="800" fill="url(#bg)"/>
  {figure(PAPER, AMBER, s4, 1120, 200)}
  <g font-family="{FONT}" fill="{PAPER}">
    <text x="120" y="150" font-size="56" font-weight="800" letter-spacing="-2">jev<tspan fill="{AMBER}">-</tspan>ra</text>
    <text x="120" y="290" font-size="72" font-weight="800" letter-spacing="-3">Browser use for coding agents.</text>
    <text x="120" y="376" font-size="72" font-weight="800" letter-spacing="-3" fill="{AMBER}">4-8.5x faster than browser-use.</text>
    <text x="120" y="440" font-size="28" fill="#B8BCC4">Jev decides every step in ~300 ms.</text>
    <text x="120" y="478" font-size="28" fill="#B8BCC4">Your agent plans, reads the page, and takes over when it matters.</text>
  </g>
  <g font-family="{FONT}">
    <g transform="translate(120 540)"><rect width="250" height="110" rx="16" fill="{PAPER}" fill-opacity="0.06" stroke="{PAPER}" stroke-opacity="0.12"/><text x="24" y="58" font-size="48" font-weight="800" fill="{PAPER}">8.5x</text><text x="24" y="90" font-size="19" fill="#B8BCC4">Wikipedia lookup</text></g>
    <g transform="translate(394 540)"><rect width="250" height="110" rx="16" fill="{PAPER}" fill-opacity="0.06" stroke="{PAPER}" stroke-opacity="0.12"/><text x="24" y="58" font-size="48" font-weight="800" fill="{PAPER}">7.5x</text><text x="24" y="90" font-size="19" fill="#B8BCC4">Google Flights search</text></g>
    <g transform="translate(668 540)"><rect width="250" height="110" rx="16" fill="{PAPER}" fill-opacity="0.06" stroke="{PAPER}" stroke-opacity="0.12"/><text x="24" y="58" font-size="48" font-weight="800" fill="{PAPER}">4.0x</text><text x="24" y="90" font-size="19" fill="#B8BCC4">E-commerce sort</text></g>
  </g>
  <g transform="translate(120 692)" font-family="{MONO}"><rect width="600" height="58" rx="29" fill="{AMBER}"/><text x="30" y="38" font-size="25" font-weight="700" fill="{INK}">$ uvx jev-ra install claude</text></g>
  <text x="1480" y="770" text-anchor="end" font-family="{FONT}" font-size="18" fill="#6B7280">jev-ra medians vs browser-use 0.13 flash_mode · same machine, Chrome and OpenRouter key · 2026-09-18</text>
</svg>
'''
(out / "hero.svg").write_text(hero)
print("wrote mark.svg mark-dark.svg mark-tile.svg logo.svg hero.svg")
