#!/usr/bin/env node

import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(SCRIPT_DIR, "..");
const CONFIG_PATH = resolve(REPO_ROOT, "config", "harness.local.json");
const SALESFORCE_MCP_VERSION = "0.30.15";
const SALESFORCE_MCP_BIN = resolve(
  REPO_ROOT,
  "node_modules",
  "@salesforce",
  "mcp",
  "bin",
  "run.js",
);
const REVIEW_SERVER = resolve(SCRIPT_DIR, "salesforce_review_server.mjs");

function fail(message) {
  process.stderr.write(`Salesforce MCP startup blocked: ${message}\n`);
  process.exit(2);
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      fail("expected --mode review --org <alias>");
    }
    parsed[key.slice(2)] = value;
  }
  return parsed;
}

const { mode, org } = parseArgs(process.argv.slice(2));
// The development/write lane was retired 2026-08-04 (owner decision): org changes are
// human-only, so the vendor MCP is never spawned with write toolsets from this launcher.
if (mode !== "review") {
  fail(`unsupported mode '${mode ?? ""}'; org changes are human-only`);
}
if (!org || /(^|[^a-z])(prod|production)([^a-z]|$)/i.test(org)) {
  fail("the org alias is missing or production-like");
}

let config;
if (!existsSync(CONFIG_PATH)) {
  fail(
    "config/harness.local.json is missing; create the ignored local policy from " +
      "config/harness.example.json before starting Salesforce MCP",
  );
}
try {
  config = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
} catch (error) {
  fail(`cannot read valid ${CONFIG_PATH}: ${error.message}`);
}

const entry = config?.salesforce?.orgs?.find((candidate) => candidate?.alias === org);
const environment = entry ? String(entry.environment).trim().toLowerCase() : null;
if (environment === "production") {
  fail(`alias '${org}' is marked production in local configuration`);
}
if (entry && !new Set(["development", "qa", "uat"]).has(environment)) {
  fail(`alias '${org}' has an unsupported environment classification`);
}
if (config?.salesforce?.review?.enabled !== true) {
  fail("Salesforce org review is disabled in local configuration");
}
// Owner decision 2026-08-04: which org a developer connects is the developer's
// responsibility. No per-alias grants and no startup identity subprocess here — any
// non-production-looking alias is admitted, and the review facade proves live
// non-production identity on every tool call and refuses any organization ID listed
// in salesforce.review.deniedOrganizationIds.
if (!existsSync(SALESFORCE_MCP_BIN)) {
  fail(`pinned @salesforce/mcp@${SALESFORCE_MCP_VERSION} is missing; run npm ci`);
}

const child = spawn(process.execPath, [REVIEW_SERVER, "--org", org], {
  cwd: REPO_ROOT,
  env: { ...process.env, SF_ORG_API_VERSION: String(config.salesforce.review.apiVersion) },
  stdio: "inherit",
  shell: false,
});

child.on("error", (error) => fail(`failed to start guarded Node runtime: ${error.message}`));
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
