# Releasing jev-ra

The maintainer's runbook for a release, written for 0.1.0. Everything here comes from
`.github/workflows/release.yml`, `pyproject.toml`, `npm/package.json` and
`scripts/check_versions.py`; when those files change, change this one with them.

## One-time PyPI trusted publisher

There is no PyPI token to store. The `pypi` job publishes with
`pypa/gh-action-pypi-publish@release/v1` and `permissions: id-token: write`, so PyPI trusts the
GitHub Actions OIDC claims instead. Enter these values once in the `jev-ra` project's publishing
settings on pypi.org (a pending publisher before the first upload):

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
| `pypi` | `pypi` | the built wheel and sdist via trusted publishing |
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
