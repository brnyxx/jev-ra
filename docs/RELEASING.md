# Releasing jev-ra

The maintainer's runbook for a release, written for 0.1.0. Everything here comes from
`.github/workflows/release.yml`, `pyproject.toml`, `npm/package.json` and
`scripts/check_versions.py`; when those files change, change this one with them.

## One-time PyPI token

The `pypi` job publishes with `pypa/gh-action-pypi-publish@release/v1` authenticated by the
repository secret `PYPI_API_TOKEN`, an API token from the maintainer's PyPI account scoped to the
`jev-ra` project (the same token `~/.pypirc` holds for `twine`). `skip-existing: true` makes a
re-run of the job on a tag whose files are already on PyPI succeed instead of failing on the
duplicate. Set the secret once:

```sh
gh secret set PYPI_API_TOKEN --repo brnyxx/jev-ra < token-file
```

Trusted publishing (OIDC) was the first design and failed every 0.1.x and 0.2.0 run with
`invalid-publisher`; the values it would need on pypi.org are kept here in case it is revisited:

| form field | value |
|---|---|
| PyPI Project Name | `jev-ra` |
| Owner | `brnyxx` |
| Repository name | `jev-ra` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

`Workflow name` is the **file name** in `.github/workflows/` (`release.yml`), not the workflow's
`name:` (`release`); PyPI matches the file name that appears in the OIDC claim. `Environment name`
is the `environment:` value the `pypi` job declares, also `pypi`.

## One-time npm account and token

The `npm` job publishes `npm/` with:

```sh
npm publish --provenance --access public
```

authenticated by `NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}` and running in the GitHub environment
`npm`. The package must be published from the maintainer's own npm account: `npm/package.json`
names the author as Brian Kim and points the package at `github.com/brnyxx/jev-ra`. Set
`NPM_TOKEN` (a repository or `npm` environment secret) to a token created on that account.

When the account has two-factor authentication on, `npm publish` asks for a one-time password:
the maintainer answers with the code from the account's authenticator app after `npm login`. A CI
runner cannot answer an interactive prompt, so `NPM_TOKEN` must be a token that publishes without
an OTP challenge (npm's automation token). If the `npm` job stops at the OTP prompt, rotate the
token and re-run the job, as below.

A dead token does not say so: `npm publish` answers `404 Not Found - PUT
https://registry.npmjs.org/jev-ra` and `'jev-ra@0.1.0' is not in this registry` (seen on the first
0.1.0 run, 2026-09-21). Check the token with `npm whoami`; `E401` means it is expired or revoked.
Create a new one and set the secret again. The package page on npmjs.com keeps showing the 0.0.1
placeholder README until a publish succeeds; the README that ships is `npm/README.md`.

## Enable the publish jobs

The publish jobs also require two repository variables (Settings > Secrets and variables > Actions
> Variables), otherwise the tag only builds:

| variable | value | gates |
|---|---|---|
| `PYPI_TRUSTED` | `true` | the `pypi` job |
| `NPM_PUBLISH` | `true` | the `npm` job |

## Measure before the bump

Every number the release notes, the README or the site quote comes from a file committed with the
release. Before bumping, run the recorded tasks on the release head and on the previous tag, back to
back on one machine, and keep both JSON payloads:

```sh
uv run jev-ra bench --live --runs 5 --json > docs/benchmarks/<date>-v<version>/bench-live-5runs.json
```

The payload names the decision route (`route`: provider, endpoint, model) and, per task, every
decision's round trip (`decision_ms`: n, median, p90, min, max and each value). Quote per-decision
latency only from these, with the route and date next to it, and compare two routes only when they
were measured in the same window.

## Bump the version

`scripts/check_versions.py` compares four places, and they must all agree before the tag is
pushed:

| file | what carries the version |
|---|---|
| `pyproject.toml` | `[project] version` |
| `npm/package.json` | `version` |
| `npm/bin/jev-ra.js` | `export const PINNED = "..."`, the `uvx jev-ra@<version>` the launcher runs |
| `jev_ra/__init__.py` | `__version__` |

Edit all four to the new version, then run the check twice:

```sh
uv run --no-project python scripts/check_versions.py
uv run --no-project python scripts/check_versions.py --tag v0.1.0
```

Each must print `version 0.1.0 agrees in pyproject.toml, npm/package.json, npm/bin/jev-ra.js,
jev_ra/__init__.py`. Commit the bump, then tag and push:

```sh
git tag v0.1.0
git push origin v0.1.0
```

The tag format is `v<version>`; `release.yml` triggers on `v*`. The `build` job re-runs the same
comparison as `scripts/check_versions.py --tag "$GITHUB_REF_NAME"` and stops the release if the
tag and the four files disagree.

## What the tag runs

The `build` job checks the versions, runs `uv build`, smoke-tests the wheel with
`uvx --from dist/*.whl jev-ra --version`, runs the npm launcher tests (`node --test
"test/*.test.mjs"` and `npm pack --dry-run` in `npm/`) and uploads the `dist` artifact. Only then
do the two independent publish jobs run, each gated by its variable:

| job | environment | publishes |
|---|---|---|
| `pypi` | `pypi` | the built wheel and sdist with `PYPI_API_TOKEN` |
| `npm` | `npm` | the launcher via `npm publish --provenance --access public` |

`workflow_dispatch` also runs `build`, but both publish jobs require a `refs/tags/v*` ref, so a
manual dispatch cannot publish.

## Post-release smoke

From any machine, with `OPENROUTER_API_KEY` or `TYPESAFE_API_KEY` exported and a Chrome reachable:

```sh
uvx jev-ra@0.1.0 doctor
npx -y jev-ra@0.1.0 doctor
```

Each prints the key, the route, Chrome and one live decision; the last line is
`decision: DONE in <n> ms via <model>`. The `npx` run exercises the npm launcher, which contains no
jev-ra code and runs the same pinned Python package through `uvx`.

## If the `pypi` job fails

`403` with `Invalid or non-existent authentication information` means `PYPI_API_TOKEN` is missing,
revoked or scoped to another project; set it again from the maintainer's account. Until it works,
upload what CI built rather than a local build, so the files on PyPI are the ones the run tested:

```sh
gh run download <run id> --dir /tmp/jev-ra-release        # the `dist` artifact of the tag's run
uv run --with twine twine check /tmp/jev-ra-release/dist/*
uv run --with twine twine upload --non-interactive /tmp/jev-ra-release/dist/*
```

`twine` reads the API token from `~/.pypirc` (`username = __token__`). The `npm` job is not
affected. Re-running `pypi` after a manual upload is safe: `skip-existing` passes over the files
already there.

## If PyPI succeeds and npm fails

The `pypi` and `npm` jobs share only the `build` job; neither depends on the other, so a failed
`npm` job leaves the PyPI release in place.

1. Read the `npm` job log. The usual causes are a missing or expired `NPM_TOKEN`, a token from an
   account that cannot publish `jev-ra`, or an OTP challenge the runner could not answer.
2. Fix the cause: create the token on the maintainer's npm account and set it as the repository or
   `npm` environment secret.
3. On the failed run for that tag, use "Re-run failed jobs". The ref is still `refs/tags/v0.1.0`,
   so the publish conditions and the `build` artifacts still apply, and only the failed job runs
   again.
4. Do not bump the version, move the tag, or re-run `pypi`: 0.1.0 already exists on PyPI and a
   second upload is rejected. `npm view jev-ra version` says what npm has; if it already answers
   `0.1.0`, the publish went through and nothing needs re-running.

If the `build` job itself fails, the tag triggered no publish; fix the build, delete the tag, and
push it again on the fixed commit.
