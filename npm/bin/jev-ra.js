#!/usr/bin/env node
// A launcher, not a reimplementation: every argument goes to `uvx jev-ra@<pinned>`.
// uv builds and caches the Python environment, so there is nothing to install first.

import { execFileSync, spawnSync } from "node:child_process";
import { createInterface } from "node:readline";
import process from "node:process";

export const PINNED = "0.1.0";
export const INSTALL_HINT = [
  "jev-ra runs on uv, which is not on PATH.",
  "Install it with one of:",
  "  curl -LsSf https://astral.sh/uv/install.sh | sh     (macOS, Linux)",
  "  powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"   (Windows)",
  "  brew install uv",
  "then run this command again.",
].join("\n");

export function findUv(which = whichSync) {
  return which("uv");
}

export function whichSync(command) {
  const finder = process.platform === "win32" ? "where" : "which";
  const found = spawnSync(finder, [command], { encoding: "utf8" });
  if (found.status !== 0) return null;
  const first = (found.stdout || "").split(/\r?\n/).find(Boolean);
  return first ? first.trim() : null;
}

export function splitArgs(argv) {
  const passthrough = argv.filter((item) => item !== "--yes" && item !== "--no-install");
  return {
    args: passthrough,
    assumeYes: argv.includes("--yes"),
    allowInstall: !argv.includes("--no-install"),
  };
}

// JEV_RA_FROM lets CI and anyone pinning a fork point uvx at a wheel or a git ref instead.
export function uvxArgs(args, pinned = PINNED, from = process.env.JEV_RA_FROM) {
  return ["--from", from || `jev-ra==${pinned}`, "jev-ra", ...args];
}

async function confirm(question) {
  if (!process.stdin.isTTY) return false;
  const reader = createInterface({ input: process.stdin, output: process.stderr });
  try {
    const answer = await new Promise((resolve) => reader.question(`${question} [y/N] `, resolve));
    return /^y(es)?$/i.test(answer.trim());
  } finally {
    reader.close();
  }
}

function installUv() {
  const command =
    process.platform === "win32"
      ? ["powershell", ["-c", "irm https://astral.sh/uv/install.ps1 | iex"]]
      : ["sh", ["-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]];
  execFileSync(command[0], command[1], { stdio: "inherit" });
}

export async function main(argv = process.argv.slice(2)) {
  const { args, assumeYes, allowInstall } = splitArgs(argv);
  let uv = findUv();
  if (!uv && allowInstall) {
    const agreed = assumeYes || (await confirm("Install uv now?"));
    if (agreed) {
      installUv();
      uv = findUv();
    }
  }
  if (!uv) {
    process.stderr.write(`${INSTALL_HINT}\n`);
    return 2;
  }
  try {
    execFileSync("uvx", uvxArgs(args), { stdio: "inherit" });
    return 0;
  } catch (error) {
    return typeof error.status === "number" ? error.status : 1;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  process.exitCode = await main();
}
