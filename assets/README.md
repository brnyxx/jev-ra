# jev-ra brand assets

The name is the mascot: **jev-ra** reads as "zebra" in Korean (제브라). The mark is a zebra stepping out of a browser window: the window frame with its three title-bar dots says browser, the zebra says jev-ra, and the stripes carry the motion. Two amber touches only - the eye (Jev, the decision) and the three dots (the chrome the agent drives). The concept (`source/zebra-concept.png`) was traced to Bezier paths with potrace (`source/zebra-trace.svg`); the curves are kept as traced. Everything here is generated from that trace by `source/build_brand.py`, so mark, tile, lockup and hero share identical geometry.

## Files

| file | use |
|---|---|
| `mark.svg` | standalone mark (window + zebra), light background. README, docs |
| `mark-dark.svg`, `mark-dark-512.png` | same mark for dark grounds (paper figure, amber accents). Landing page hero |
| `mark-tile.svg` | app-icon tile: ink rounded square, paper head, amber eye. Favicon, social avatar, MCP icon |
| `mark-512.png`, `mark-tile-512.png`, `favicon-64.png` | rasters for places that cannot take SVG |
| `logo.svg` | horizontal lockup, mark + wordmark, light background. README header |
| `hero.svg`, `hero.png` | 1600×800 dark hero for the README top and the landing page, with the three headline ratios |
| `logo.png` | raster of the lockup |
| `source/` | concept PNG, potrace output, and the generator; edit the trace, re-run `python3 source/build_brand.py assets` |
| `demo/` | GIF/MP4 renders produced by `scripts/render_side_by_side.py` |

Re-render rasters after editing an SVG:

```sh
python3 source/build_brand.py .   # regenerate SVGs from source/zebra-trace.svg
rsvg-convert -w 1600 hero.svg -o hero.png
rsvg-convert -w 512 -h 512 mark.svg -o mark-512.png
rsvg-convert -w 512 -h 512 mark-tile.svg -o mark-tile-512.png
rsvg-convert -w 64 -h 64 mark-tile.svg -o favicon-64.png
```

## Palette

| token | hex | role |
|---|---|---|
| ink | `#0B0F14` | outlines, stripes, text on light |
| paper | `#F6F4EF` | mark fill on light, text on dark |
| amber | `#FFB703` | the eye, the three title-bar dots, the hyphen in the wordmark, the install pill, headline numbers |
| slate | `#151B24` | dark gradient end |
| muted | `#B8BCC4` / `#6B7280` | secondary copy on dark |

One accent only. Amber is the eye, the three title-bar dots, the hyphen in the wordmark, the install pill and the headline numbers; nothing else gets it.

## Rules

- The zebra always faces right and always steps out of the window's right edge. Never mirror the mark.
- On dark grounds the figure is paper; the eye and the three dots stay amber. One-colour version: eye and dots take the figure colour.
- The tile is for square slots only (favicons, avatars, app lists); everywhere else use the standalone head or the lockup.
- Minimum clear space around the lockup: the height of the wordmark's "j".
- Do not rotate, add gradients or drop shadows, outline the head, or place the mark over photographs.
- Wordmark is set in the system UI sans at weight 800 with tight tracking (`letter-spacing -5` at 96 px); the hyphen is amber.

## README chips

Use shields.io flat-square badges, in this order, one row:

```
PyPI version · npm version · Python 3.12+ · MIT · CI · MCP · Chrome DevTools Protocol · TypeSafe Jev · OpenRouter
```

Example (replace once published):

```md
[![PyPI](https://img.shields.io/pypi/v/jev-ra?style=flat-square&color=FFB703&labelColor=0B0F14)](https://pypi.org/project/jev-ra/)
[![npm](https://img.shields.io/npm/v/jev-ra?style=flat-square&color=FFB703&labelColor=0B0F14)](https://www.npmjs.com/package/jev-ra)
![Python](https://img.shields.io/badge/python-3.12%2B-0B0F14?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-0B0F14?style=flat-square)
![CI](https://img.shields.io/github/actions/workflow/status/brnyxx/jev-ra/ci.yml?style=flat-square&labelColor=0B0F14)
![MCP](https://img.shields.io/badge/MCP-server-0B0F14?style=flat-square)
![CDP](https://img.shields.io/badge/Chrome-DevTools%20Protocol-0B0F14?style=flat-square)
![Jev](https://img.shields.io/badge/TypeSafe-Jev-FFB703?style=flat-square&labelColor=0B0F14)
![OpenRouter](https://img.shields.io/badge/OpenRouter-ready-0B0F14?style=flat-square)
```

## Raster illustration (optional, generated)

For social cards or the landing page a painted mascot can sit next to the vector mark. Prompt used for image generation:

> Minimal flat-vector illustration of a stylised zebra in full gallop, facing right, built from bold geometric diagonal stripes only, cream (#F6F4EF) on near-black (#0B0F14), one stripe in amber (#FFB703), no outline, no eye detail, no text, no gradients, no shading, centered with generous margin, 1:1. Style: Swiss poster, Saul Bass, reductive.

Keep generated art out of the README header; the vector mark is the identity.
