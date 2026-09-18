# Site assets

`icons/` holds the brand marks the landing page (`docs/index.html`) inlines as an SVG sprite: GitHub, npm, PyPI, Python, Google Chrome, OpenAI, Claude, Model Context Protocol, OpenRouter, Cursor, Node.js, uv. They come from [Simple Icons](https://simpleicons.org/) 16.31.0, released under CC0 1.0. The marks themselves belong to their owners; the page uses them to say "works with" and nothing more.

Refresh: `curl -o icons/<slug>.svg https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/<slug>.svg`, then rebuild the sprite (the maintainer's `build_site.py` reads `<path d>` and `<title>` from each file).
