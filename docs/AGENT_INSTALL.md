# Installing jev-ra in your agent

One page per host. Every command here is real; `uv run jev-ra --help` and
[docs/USAGE.md](USAGE.md) are generated from the same code.

Before anything: export a key. `OPENROUTER_API_KEY` is the easy one (no TypeSafe account needed);
`TYPESAFE_API_KEY` works too and is a little faster per decision.

```sh
export OPENROUTER_API_KEY=sk-or-...
```

jev-ra never prints the key. `install` forwards it from the variable you exported.

## Give the agent its own copy of the guide

Every agent below works better with [AGENTS.md](../AGENTS.md) in its context. `jev-ra skill` prints
it, so you can drop it wherever your host keeps instructions:

```sh
mkdir -p .claude/skills/jev-ra && uvx jev-ra skill > .claude/skills/jev-ra/SKILL.md   # Claude Code
uvx jev-ra skill > AGENTS.md                                                          # Codex, Cursor
uvx jev-ra skill > .clinerules                                                        # Cline
```

## Claude Code

```sh
uvx jev-ra install claude --scope user
uvx jev-ra doctor
```

`--scope` picks where it is stored: `user` (every project), `project` (checked in, shared with the
team), `local` (this checkout only). Restart Claude Code, then `/mcp` should list `jev-ra`.

Paste-in prompt:

> Use the jev-ra MCP server to open https://en.wikipedia.org/wiki/Main_Page and find the article
> about Gödel's incompleteness theorems. Supply the search text through `values`; do not let it guess.

## Codex

```sh
uvx jev-ra install codex
uvx jev-ra doctor
```

Codex asks you to trust the new MCP server once. Paste-in prompt:

> Use jev-ra to open the checkout page at http://localhost:8000/checkout and place a test order for
> Ada Lovelace, ada@example.com, express shipping. Pass every value through `values`.

## Cursor

Cursor reads `.cursor/mcp.json` in the project, or the global one in `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "jev-ra": {
      "command": "uvx",
      "args": ["jev-ra", "mcp"],
      "env": { "OPENROUTER_API_KEY": "${env:OPENROUTER_API_KEY}" }
    }
  }
}
```

Paste-in prompt:

> With jev-ra, search for the Python 3.12 release date and give me the page that says it.

## Cline

Cline keeps its servers in `cline_mcp_settings.json` (Settings → MCP Servers → Configure):

```json
{
  "mcpServers": {
    "jev-ra": {
      "command": "uvx",
      "args": ["jev-ra", "mcp"],
      "env": { "OPENROUTER_API_KEY": "sk-or-..." },
      "disabled": false
    }
  }
}
```

## Devin and other MCP clients

Any client that speaks MCP over stdio can run the same command:

```json
{ "mcpServers": { "jev-ra": { "command": "uvx", "args": ["jev-ra", "mcp"] } } }
```

The server inherits the environment it is started in, so the key can come from there instead of the
config file.

## Without Python

The npm launcher finds `uv`, offering to install it the first time, and then runs the same thing:

```sh
npx -y jev-ra install claude
npx -y jev-ra doctor
```

## Checking it worked

`uvx jev-ra doctor` ends with a line like:

```
decision: DONE in 314 ms via typesafe/jev-1.13
```

If it says `key: missing`, `chrome: unreachable` or `decision: failed`, the same line names the next
step. jev-ra launches its own Chrome on a dedicated profile when none is reachable; set
`BU_CDP_URL=http://127.0.0.1:9222` to use one you started yourself.

## The first thing to ask for

Start with something that has a visible end state, and supply any text that must be typed:

> Open https://en.wikipedia.org/wiki/Main_Page and open the article on Gödel's incompleteness
> theorems. Use `values={"search_query": "Godel incompleteness theorems"}`.

If the run comes back `escalate` with `needs_value`, that is jev-ra refusing to invent a string.
Supply it and call again. See [AGENTS.md](../AGENTS.md) for the full escalation table.
