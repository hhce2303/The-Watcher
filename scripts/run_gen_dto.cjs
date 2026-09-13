#!/usr/bin/env node
// Resolve a working Python interpreter for scripts/gen_dto_ts.py.
//
// Locally, bare `python` on PATH can resolve to the Windows Store's stub
// instead of a real interpreter, so dev machines run this via
// `uv run --python <path-to-the-project-venv>`. In CI
// (.github/workflows/ci.yml), `actions/setup-python@v5` puts a real
// interpreter directly on PATH and installs project/requirements.txt into
// it -- no uv, no venv layer -- so plain `python` already works there.
// GitHub Actions always sets CI=true, which is the signal used below.
"use strict";

const { spawnSync } = require("node:child_process");
const { existsSync } = require("node:fs");
const path = require("node:path");

const localVenvPython = path.join(
  process.env.LOCALAPPDATA || "",
  "The Watcher",
  "venv",
  "Scripts",
  "python.exe",
);

function hasUv() {
  // No `shell: true` here (or below): spawnSync passes the argv array
  // straight to CreateProcess on Windows, which quotes each argument
  // correctly on its own. Going through cmd.exe (shell: true) splits
  // localVenvPython's un-quoted spaces ("...\The Watcher\venv\...") into
  // separate argv entries instead.
  const probe = spawnSync("uv", ["--version"], { stdio: "ignore" });
  return probe.status === 0;
}

const useUv = !process.env.CI && existsSync(localVenvPython) && hasUv();

const result = useUv
  ? spawnSync("uv", ["run", "--python", localVenvPython, "python", "scripts/gen_dto_ts.py"], {
      stdio: "inherit",
    })
  : spawnSync("python", ["scripts/gen_dto_ts.py"], { stdio: "inherit" });

process.exit(result.status === null ? 1 : result.status);
