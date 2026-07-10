#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(SCRIPT_DIR, "..");
const METADATA_ROOT = resolve(REPO_ROOT, "..", "salesforce-metadata");
const CONFIG_PATH = resolve(REPO_ROOT, "config", "harness.local.json");
const SALESFORCE_MCP_VERSION = "0.30.15";

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
      fail("expected --mode <readonly|development> --org <alias>");
    }
    parsed[key.slice(2)] = value;
  }
  return parsed;
}

const { mode, org } = parseArgs(process.argv.slice(2));
if (!new Set(["readonly", "development"]).has(mode)) {
  fail(`unsupported mode '${mode ?? ""}'`);
}
if (!org || /(^|[^a-z])(prod|production)([^a-z]|$)/i.test(org)) {
  fail("the org alias is missing or production-like");
}

let config;
try {
  config = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
} catch (error) {
  fail(`cannot read valid ${CONFIG_PATH}: ${error.message}`);
}

const entry = config?.salesforce?.orgs?.find((candidate) => candidate?.alias === org);
if (!entry) {
  fail(`alias '${org}' is not present in config/harness.local.json`);
}
const environment = String(entry.environment).trim().toLowerCase();
if (!new Set(["development", "qa", "uat"]).has(environment)) {
  fail(`alias '${org}' has an unsupported environment classification`);
}
if (mode === "development" && environment !== "development") {
  fail(`development mode requires environment=development for alias '${org}'`);
}
const permission = mode === "development" ? "allowAgentWrite" : "allowAgentRead";
if (entry[permission] !== true) {
  fail(`alias '${org}' does not grant ${permission}`);
}
if (mode === "development") {
  if (process.platform === "win32") {
    fail("development mode is disabled on Windows because MCP sandboxing is unavailable");
  }
  if (config?.safety?.sharedSandboxWritesApproved !== true) {
    fail("shared-sandbox writes are not approved in local configuration");
  }
  if (!String(config?.safety?.sharedSandboxApprovalRef ?? "").trim()) {
    fail("shared-sandbox approval reference is missing");
  }
  if (!existsSync(resolve(METADATA_ROOT, "sfdx-project.json"))) {
    fail(`Salesforce metadata root is missing sfdx-project.json: ${METADATA_ROOT}`);
  }
}

const python = process.platform === "win32" ? "py" : "python3";
const verificationArgs = process.platform === "win32"
  ? ["-3", resolve(SCRIPT_DIR, "verify_salesforce_org.py"), "--org", org]
  : [resolve(SCRIPT_DIR, "verify_salesforce_org.py"), "--org", org];
const verification = spawnSync(python, verificationArgs, {
  cwd: REPO_ROOT,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "pipe"],
  timeout: 30000,
  shell: false,
});
if (verification.status !== 0) {
  fail("live Organization.IsSandbox proof failed; MCP server was not started");
}

const args = ["-y", `@salesforce/mcp@${SALESFORCE_MCP_VERSION}`, "--orgs", org, "--no-telemetry"];
if (mode === "readonly") {
  args.push("--tools", "list_all_orgs,run_soql_query");
} else {
  args.push(
    "--toolsets",
    "metadata,testing,code-analysis",
    "--tools",
    "list_all_orgs,run_soql_query",
  );
}

const executable = process.platform === "win32" ? "npx.cmd" : "npx";
const child = spawn(executable, args, {
  cwd: mode === "development" ? METADATA_ROOT : REPO_ROOT,
  env: process.env,
  stdio: "inherit",
  shell: false,
});

child.on("error", (error) => fail(`failed to start npx: ${error.message}`));
child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code ?? 1);
  }
});
