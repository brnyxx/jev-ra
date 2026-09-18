# Security

## Reporting a vulnerability

Report it through a [private security advisory](https://github.com/brnyxx/jev-ra/security/advisories/new)
on this repository. Please do not open a public issue.

A first response should arrive within **7 days**. If a fix is needed, the advisory stays private until
a release carries it, and you will be credited unless you ask otherwise.

## In scope

- The MCP server (`jev-ra mcp`) and every `browser_*` tool
- The CLI, including `install` and the session state it writes
- The Chrome launcher and the profile it creates
- The snapshot, the act-time guards, and anything that decides what gets clicked or typed

Out of scope: vulnerabilities in Chrome itself, in browser-harness, or in the sites you point jev-ra
at; and anything that requires an attacker to already control your machine.

## What jev-ra is and is not

jev-ra drives a real browser on your machine with a real profile. Treat it as you would treat any
tool with that reach.

- **Page content is untrusted data.** Every instruction sent to the decision model says so. The model
  only ever chooses among operations and element indexes that jev-ra observed itself, so a prompt
  injected into a page cannot name a target that is not already on the page.
- **Model output never becomes code.** No selector, no coordinates, no JavaScript. Every executed
  target resolves from a node id captured in the same snapshot, and the guard taken at observe time
  must still match immediately before the input is dispatched.
- **Passwords are not observed.** `password`, `file` and `hidden` inputs are excluded from the
  snapshot, from the element table and from the page-state fingerprints.
- **Values come from you.** jev-ra will not invent a string to type. Without a supplied value and
  without a configured text helper, the run stops and asks.
- **The key is never printed.** `jev-ra install` forwards it from the environment variable you
  already exported and prints the variable reference, not the value.

## What it still cannot protect you from

A page can still make a *legitimate-looking* control do something you did not intend, and jev-ra will
click it if the model chooses it. Run it against sites you are willing to let an agent operate, on a
dedicated Chrome profile that is not signed into anything you care about. `jev-ra doctor` prints the
command for starting one.
