# Security

## Reporting

Please report a vulnerability through GitHub's private advisory form on this repository rather than
a public issue. A first response should take a few days.

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
