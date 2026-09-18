# Support

## Where to ask

| you want to | go to |
|---|---|
| ask how to do something, or share what you built | [Discussions](https://github.com/brnyxx/jev-ra/discussions) |
| report something jev-ra did wrong | [Issues → Bug report](https://github.com/brnyxx/jev-ra/issues/new?template=bug.yml) |
| ask for something jev-ra cannot do yet | [Issues → Feature request](https://github.com/brnyxx/jev-ra/issues/new?template=feature.yml) |
| report a vulnerability | a [private advisory](https://github.com/brnyxx/jev-ra/security/advisories/new), never an issue. See [SECURITY.md](SECURITY.md) |

## Before you open an issue

Run `jev-ra doctor` and paste the output. It never prints your key, and it answers most of what a
maintainer would ask first: which key variable was found, which route and model, whether Chrome was
reachable and which one, and whether a live decision came back and how fast.

If a task went wrong, add `--json` to the command and paste the result. The escalation `reason`, the
`candidates` and the step list say more than a description of what you saw.

## Read first

- [README](README.md) — what it is, the numbers, the limits
- [docs/USAGE.md](docs/USAGE.md) — every MCP tool and CLI command, generated from the code
- [AGENTS.md](AGENTS.md) — the guide written for coding agents themselves
- [docs/BENCHMARKS.md](docs/BENCHMARKS.md) — how the numbers were measured and how to reproduce them

## Response times

This is a small project maintained in the open. Issues usually get a first response within a week;
security reports are looked at first.
