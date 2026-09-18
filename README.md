# jev-ra

jev-ra is a fast browser-use layer for CLI coding agents. Claude Code, Codex, or any
MCP client hands it a goal; TypeSafe Jev, a System One decision model, picks the
operation and the target element for every step in one round trip; the host agent
plans, supplies text values, reads what the page says, and takes over when jev-ra
escalates. No second LLM runs inside the loop.

One Python package, three faces on one browser core: an MCP server (`jev-ra mcp`),
a CLI (`jev-ra run|open|act|observe|extract|...`), and a Python API (`jev_ra.Agent`).

Work in progress. See `docs/DESIGN.md`.
