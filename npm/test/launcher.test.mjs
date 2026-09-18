import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { INSTALL_HINT, PINNED, findUv, main, splitArgs, uvxArgs } from "../bin/jev-ra.js";

const here = dirname(fileURLToPath(import.meta.url));
const launcher = join(here, "..", "bin", "jev-ra.js");

test("every argument is passed through to uvx untouched", () => {
  assert.deepEqual(uvxArgs(["run", "https://example.com", "do a thing", "--json"]), [
    "--from",
    `jev-ra==${PINNED}`,
    "jev-ra",
    "run",
    "https://example.com",
    "do a thing",
    "--json",
  ]);
});

test("an empty argument list still names the entry point", () => {
  assert.deepEqual(uvxArgs([]), ["--from", `jev-ra==${PINNED}`, "jev-ra"]);
});

test("JEV_RA_FROM replaces the pin, for a local wheel or a fork", () => {
  assert.deepEqual(uvxArgs(["--version"], PINNED, "./dist/jev_ra-0.1.0-py3-none-any.whl"), [
    "--from",
    "./dist/jev_ra-0.1.0-py3-none-any.whl",
    "jev-ra",
    "--version",
  ]);
});

test("the launcher's own flags never reach the Python side", () => {
  const split = splitArgs(["doctor", "--yes", "--json", "--no-install"]);
  assert.deepEqual(split.args, ["doctor", "--json"]);
  assert.equal(split.assumeYes, true);
  assert.equal(split.allowInstall, false);
});

test("findUv reports what the platform lookup found", () => {
  assert.equal(findUv(() => "/opt/homebrew/bin/uv"), "/opt/homebrew/bin/uv");
  assert.equal(findUv(() => null), null);
});

test("without uv and with --no-install it prints the hint and exits 2", () => {
  const finished = spawnSync(process.execPath, [launcher, "--version", "--no-install"], {
    encoding: "utf8",
    env: { ...process.env, PATH: join(here, "empty-path") },
  });
  assert.equal(finished.status, 2);
  assert.equal(finished.stdout, "");
  assert.match(finished.stderr, /uv, which is not on PATH/);
});

test("with uv present the arguments reach the Python entry point", () => {
  const wheel = join(here, "..", "..", "dist");
  const finished = spawnSync(process.execPath, [launcher, "--version"], {
    encoding: "utf8",
    env: { ...process.env, JEV_RA_FROM: join(wheel, "jev_ra-0.1.0-py3-none-any.whl") },
  });
  if (finished.status === 2) return; // uv is not installed on this machine
  assert.equal(finished.status, 0);
  assert.match(finished.stdout, /^jev-ra \d+\.\d+\.\d+/);
});

test("the hint names every supported way to install uv", () => {
  assert.match(INSTALL_HINT, /astral\.sh\/uv\/install\.sh/);
  assert.match(INSTALL_HINT, /install\.ps1/);
  assert.match(INSTALL_HINT, /brew install uv/);
});

test("the pinned version matches the Python package", () => {
  const pyproject = readFileSync(join(here, "..", "..", "pyproject.toml"), "utf8");
  const version = pyproject.match(/^version = "([^"]+)"/m)[1];
  const packaged = JSON.parse(readFileSync(join(here, "..", "package.json"), "utf8")).version;
  assert.equal(PINNED, version);
  assert.equal(packaged, version);
});

test("main returns 2 when uv cannot be found and installing is refused", async () => {
  const previous = process.env.PATH;
  process.env.PATH = join(here, "empty-path");
  try {
    assert.equal(await main(["--version", "--no-install"]), 2);
  } finally {
    process.env.PATH = previous;
  }
});
