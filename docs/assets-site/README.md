# Site assets

Everything the landing page (`docs/index.html`) loads besides `assets/`. GitHub Pages serves this directory as `assets-site/`.

| file | what |
|---|---|
| `icons/` | brand marks inlined into the page as an SVG sprite: GitHub, npm, PyPI, Python, Google Chrome, OpenAI, Claude, Model Context Protocol, OpenRouter, Cursor, Node.js, uv. From [Simple Icons](https://simpleicons.org/) 16.31.0, CC0 1.0. The marks belong to their owners; the page uses them to say "works with" and nothing more |
| `i18n.js` | page copy in Korean, Japanese and Simplified Chinese, keyed by CSS selector. English is the page itself. The language option in the nav applies a locale, remembers it in `localStorage`, honours `?lang=`, and tells the demo through the `jevra-locale` event |
| `demo.js` | the landing demo: a recorded run replayed as SVG in the page. No video, no framework, no build step. Terminal copy and captions follow the page locale |
| `demo-run.json` | the run the demo replays. A verbatim copy of `docs/benchmarks/2026-09-18-v0.1/demo-run-flights.json` (raw `jev-ra run --json` output of the Google Flights task). Step order, clicked labels, typed values and every millisecond come from here |

Refresh the demo after a new run: record with `uv run jev-ra run https://www.google.com/travel/flights "<goal>" --value origin=Zurich --value destination=London --value departure_date=2026-09-20 --json > docs/benchmarks/<date>/demo-run-flights.json`, copy it over `demo-run.json`, and update the control map in `demo.js` (`CTRL`) if the step sequence changed.
