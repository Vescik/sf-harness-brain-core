#!/usr/bin/env node

/**
 * Narrow Salesforce org-review MCP facade.
 *
 * The model never receives a command string, org alias, working directory, or raw vendor
 * response. This server binds one allowlisted non-production alias at startup (sandbox, scratch
 * org, or an owner-admitted Developer Edition; the receipt's nonProduction fact is the
 * verdict, isSandbox is only Salesforce's attribute), collects
 * bounded facts through a private Salesforce CLI process and a pinned Salesforce MCP child, and
 * returns normalized reconciliation evidence. Composed read-only SOQL (owner decisions
 * 2026-07-30 and 2026-08-04) runs through review_soql_query as a governed pass-through: the
 * statement executes verbatim against the identity-proven non-production org via the pinned
 * Salesforce MCP child — never the CLI — and rows return unredacted. The 2026-08-04 decision
 * removed the statement blockade (grammar validation, secret-adjacent deny-set, LIMIT
 * policing, value redaction); the walls are one-alias binding, the session-frozen
 * non-production identity proof, the read-only vendor toolset, payload caps, and — when an
 * owner explicitly configures one — the review object allowlist.
 */

import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(SCRIPT_DIR, "..");
const TEST_MODE = process.env.SF_HARNESS_TEST_MODE === "1";
const CONFIG_PATH = TEST_MODE && process.env.SF_HARNESS_CONFIG_PATH
  ? resolve(process.env.SF_HARNESS_CONFIG_PATH)
  : resolve(REPO_ROOT, "config", "harness.local.json");
const POLICY_PATH = TEST_MODE && process.env.SF_HARNESS_REVIEW_POLICY_PATH
  ? resolve(process.env.SF_HARNESS_REVIEW_POLICY_PATH)
  : resolve(REPO_ROOT, "config", "salesforce-review-policy.json");
const SALESFORCE_MCP_BIN = resolve(REPO_ROOT, "node_modules", "@salesforce", "mcp", "bin", "run.js");
const OBJECT_API_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;
const ALIAS = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;
const ORG_ID = /^00D[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$/;
const NON_PRODUCTION_HOST = /^(?:[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*\.sandbox\.my\.salesforce\.com|[a-z0-9][a-z0-9-]*\.scratch\.my\.salesforce\.com|[a-z0-9][a-z0-9-]*\.develop\.my\.salesforce\.com)$/i;
const DEV_EDITION_HOST = /^[a-z0-9][a-z0-9-]*\.develop\.my\.salesforce\.com$/i;
const MAX_OUTER_MESSAGE_BYTES = 1_048_576;

const EXPECTED_QUERIES = Object.freeze({
  orgIdentity: "SELECT Id, IsSandbox FROM Organization LIMIT 1",
  installedPackages: "SELECT SubscriberPackage.NamespacePrefix, SubscriberPackage.Name, SubscriberPackageVersion.Name, SubscriberPackageVersion.MajorVersion, SubscriberPackageVersion.MinorVersion, SubscriberPackageVersion.PatchVersion, SubscriberPackageVersion.BuildNumber FROM InstalledSubscriberPackage WHERE SubscriberPackage.NamespacePrefix IN (${PACKAGE_NAMESPACES}) ORDER BY SubscriberPackage.NamespacePrefix, SubscriberPackage.Name LIMIT 500",
  objectEntity: "SELECT QualifiedApiName FROM EntityDefinition WHERE QualifiedApiName = '${OBJECT_API_NAME}' LIMIT 2",
  objectFields: "SELECT QualifiedApiName, DataType FROM FieldDefinition WHERE EntityDefinition.QualifiedApiName = '${OBJECT_API_NAME}' ORDER BY QualifiedApiName LIMIT 501",
});

const TOOL_DEFINITIONS = Object.freeze([
  {
    name: "review_org_identity",
    title: "Review configured non-production Salesforce identity",
    description: "Reconcile the configured non-production org identity through bounded Salesforce CLI and MCP reads.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "review_installed_packages",
    title: "Review installed Salesforce packages",
    description: "Reconcile normalized package namespace, name, and version facts for the configured non-production org.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "review_configured_orgs",
    title: "List the locally configured Salesforce orgs (scoped enumeration)",
    description: "Enumerate ONLY the org aliases configured in config/harness.local.json with their agent permissions. Requires safety.allowScopedEnumeration; never reveals org ids, hosts, or unconfigured orgs.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "review_object_contract",
    title: "Review one allowlisted Salesforce object contract",
    description: "Reconcile object existence and normalized field API-name/type facts for one configured object.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["objectApiName"],
      properties: {
        objectApiName: {
          type: "string",
          pattern: "^[A-Za-z][A-Za-z0-9_]{0,79}$",
          description: "Exact API name from the local review allowlist.",
        },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "review_soql_query",
    title: "Run one composed read-only SOQL query against the configured non-production org",
    description: "Execute one model-composed read-only SOQL statement verbatim against the configured, identity-proven non-production org through the pinned Salesforce MCP (never the CLI). Rows return unredacted, bounded only by payload size and timeout. Add a LIMIT yourself: an overflowing result set returns INCOMPLETE/RESULT_TRUNCATED.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["query"],
      properties: {
        query: {
          type: "string",
          minLength: 8,
          maxLength: 4000,
          description: "One read-only SOQL statement, executed verbatim ('${' is reserved by the profile engine and rejected).",
        },
        useToolingApi: {
          type: "boolean",
          description: "Run through the Tooling API (for example EntityDefinition or FieldDefinition).",
        },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
]);

class ReviewError extends Error {
  constructor(code, status = "BLOCKED") {
    super(code);
    this.name = "ReviewError";
    this.code = code;
    this.status = status;
  }
}

function parseServerArgs(argv) {
  if (argv.length !== 2 || argv[0] !== "--org" || !ALIAS.test(argv[1])) {
    throw new ReviewError("ALIAS_NOT_ALLOWLISTED");
  }
  if (/(^|[^a-z])(prod|production)([^a-z]|$)/i.test(argv[1])) {
    throw new ReviewError("ALIAS_PRODUCTION_LIKE");
  }
  return argv[1];
}

function readJson(path, code) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    throw new ReviewError(code);
  }
}

function loadRuntime(alias) {
  const config = readJson(CONFIG_PATH, "CONFIG_MISSING");
  const policy = readJson(POLICY_PATH, "CONFIG_INVALID");
  const configured = config?.salesforce?.orgs?.find((candidate) => candidate?.alias === alias);
  const review = config?.salesforce?.review;
  if (configured?.environment === "production") {
    throw new ReviewError("ALIAS_MARKED_PRODUCTION");
  }
  // Owner decision 2026-08-04 (supersedes the 2026-07-31 allowAnyNonProduction toggle):
  // which org a developer connects is the developer's responsibility. Any alias — configured
  // or not — is admitted on live identity proof alone; the proven identity is frozen on
  // first proof for the session. environment=production stays a hard deny marker, and any
  // organization ID listed in review.deniedOrganizationIds is refused at proof time.
  const dynamic = !configured;
  const entry = configured ?? { alias, environment: "dynamic" };
  if (review?.enabled !== true) throw new ReviewError("REVIEW_DISABLED");
  if (configured && !["development", "qa", "uat"].includes(entry.environment)) {
    throw new ReviewError("CONFIG_INVALID");
  }
  // Identity pins are optional (owner decision 2026-08-04): both present → the exact-org
  // pinned lane; both absent → discovery, exactly like an unlisted alias; exactly one
  // present is a config error. Knowledge org-attach still requires the pin (owner D-4).
  const hasHostPin = configured && entry.expectedInstanceHost !== undefined;
  const hasOrgIdPin = configured && entry.expectedOrganizationId !== undefined;
  if (hasHostPin !== hasOrgIdPin) throw new ReviewError("CONFIG_INVALID");
  const pinned = hasHostPin && hasOrgIdPin;
  if (pinned) {
    if (!NON_PRODUCTION_HOST.test(String(entry.expectedInstanceHost ?? ""))) {
      throw new ReviewError("CONFIG_INVALID");
    }
    if (!ORG_ID.test(String(entry.expectedOrganizationId ?? ""))) {
      throw new ReviewError("CONFIG_INVALID");
    }
  }
  const deniedOrganizationIds = review?.deniedOrganizationIds ?? [];
  if (
    !Array.isArray(deniedOrganizationIds) ||
    deniedOrganizationIds.some((orgId) => !ORG_ID.test(String(orgId)))
  ) {
    throw new ReviewError("CONFIG_INVALID");
  }
  if (!/^\d{2}\.0$/.test(String(review.apiVersion ?? ""))) {
    throw new ReviewError("CONFIG_INVALID");
  }
  if (review.requireDualSource !== true) throw new ReviewError("CONFIG_INVALID");
  // Absent allowedObjectApiNames means all objects (owner decision 2026-07-30); an explicit list
  // remains fully supported for orgs holding sensitive data.
  const allowedObjectApiNames = review.allowedObjectApiNames ?? ["*"];
  if (!Array.isArray(allowedObjectApiNames) || allowedObjectApiNames.length === 0) {
    throw new ReviewError("CONFIG_INVALID");
  }
  if (allowedObjectApiNames.some((name) => name !== "*" && !OBJECT_API_NAME.test(name))) {
    throw new ReviewError("CONFIG_INVALID");
  }
  // An empty list means NO managed packages are in scope — the correct statement for an
  // org that has none, and previously unrepresentable: the config was rejected outright,
  // which blocked preflight and therefore every skill. ["*"] means all installed packages.
  if (
    !Array.isArray(review.allowedPackageNamespaces) ||
    review.allowedPackageNamespaces.some(
      (namespace) => namespace !== "*" && !/^[A-Za-z][A-Za-z0-9]{0,14}$/.test(namespace),
    ) ||
    (review.allowedPackageNamespaces.includes("*") && review.allowedPackageNamespaces.length > 1)
  ) {
    throw new ReviewError("CONFIG_INVALID");
  }
  if (!Number.isInteger(review.maxFieldsPerObject) || review.maxFieldsPerObject < 1 || review.maxFieldsPerObject > 500) {
    throw new ReviewError("CONFIG_INVALID");
  }
  if (
    policy?.schemaVersion !== 1 ||
    policy.salesforceMcpPackage !== "@salesforce/mcp@0.30.15" ||
    policy.mcpProtocolVersion !== "2025-06-18" ||
    policy.salesforceCliMajor !== 2 ||
    !Number.isInteger(policy.commandTimeoutSeconds) ||
    policy.commandTimeoutSeconds < 5 ||
    policy.commandTimeoutSeconds > 60 ||
    !Number.isInteger(policy.maxVendorPayloadBytes) ||
    policy.maxVendorPayloadBytes < 65_536 ||
    policy.maxVendorPayloadBytes > 1_048_576 ||
    !Number.isInteger(policy.soqlQueryTimeoutSeconds) ||
    policy.soqlQueryTimeoutSeconds < 5 ||
    policy.soqlQueryTimeoutSeconds > 120
  ) {
    throw new ReviewError("CONFIG_INVALID");
  }
  for (const [name, query] of Object.entries(EXPECTED_QUERIES)) {
    if (policy?.profiles?.[name]?.query !== query || typeof policy.profiles[name].useToolingApi !== "boolean") {
      throw new ReviewError("QUERY_PROFILE_DENIED");
    }
  }
  return {
    alias,
    entry,
    review,
    policy,
    dynamic,
    pinned,
    // Salesforce IDs come back 15- or 18-character; the first 15 are the identity.
    deniedOrganizationIds: new Set(deniedOrganizationIds.map((orgId) => String(orgId).slice(0, 15))),
    discovered: { host: null, orgId: null, isSandbox: null },
    allowedObjects: new Set(allowedObjectApiNames),
    allowedPackageNamespaces: new Set(review.allowedPackageNamespaces),
  };
}

function assertOrgIdPermitted(runtime, orgId) {
  if (runtime.deniedOrganizationIds.has(String(orgId).slice(0, 15))) {
    throw new ReviewError("ORG_ID_DENIED");
  }
}

function now() {
  return new Date().toISOString();
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

function digest(value) {
  return createHash("sha256").update(JSON.stringify(canonicalize(value))).digest("hex");
}

function containsSensitiveMaterial(value) {
  const forbiddenKeys = new Set([
    "accesstoken",
    "refreshtoken",
    "sfdxauthurl",
    "authorization",
    "clientid",
    "username",
    "orgid",
    "organizationid",
    "instanceurl",
  ]);
  const inspect = (item) => {
    if (Array.isArray(item)) return item.some(inspect);
    if (item && typeof item === "object") {
      return Object.entries(item).some(([key, child]) => forbiddenKeys.has(key.toLowerCase()) || inspect(child));
    }
    if (typeof item !== "string") return false;
    return (
      /\bBearer\s+[A-Za-z0-9._~+/=-]+/i.test(item) ||
      /force:\/\//i.test(item) ||
      /\b00D[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?\b/.test(item) ||
      /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/.test(item)
    );
  };
  return inspect(value);
}

function baseTarget(runtime, proof = {}) {
  return {
    environment: runtime.entry.environment,
    apiVersion: runtime.review.apiVersion,
    aliasPolicyMatched: true,
    expectedHostMatched: proof.expectedHostMatched === true,
    expectedOrgIdMatched: proof.expectedOrgIdMatched === true,
    isSandbox: proof.isSandbox === true,
    nonProduction: proof.nonProduction === true,
  };
}

function unavailableSource(kind, version = "unavailable") {
  return { kind, version, complete: false, retrievedAt: now() };
}

function makeEnvelope({ runtime, reviewType, status, target, sources, facts, reconciliation, completeness, warnings, sensitiveGateExempt }) {
  const withoutHash = {
    schemaVersion: 1,
    runId: randomUUID(),
    generatedAt: now(),
    reviewType,
    status,
    target: target ?? baseTarget(runtime),
    sources: sources ?? {
      cli: unavailableSource("salesforce-cli"),
      mcp: unavailableSource("salesforce-mcp", "0.30.15"),
    },
    facts: facts ?? {},
    reconciliation: reconciliation ?? { status: "NOT_RUN", comparisons: [] },
    completeness: completeness ?? { complete: false, dualSource: false, truncated: false },
    warnings: [...new Set(warnings ?? [])].sort(),
  };
  // Composed-SOQL results are exempt (owner decision 2026-08-04): record values — including
  // emails and record Ids — return unredacted, so the leak scan would blank every real result.
  if (!sensitiveGateExempt && containsSensitiveMaterial(withoutHash)) {
    const minimal = {
      ...withoutHash,
      status: "BLOCKED",
      target: baseTarget(runtime),
      facts: {},
      reconciliation: { status: "NOT_RUN", comparisons: [] },
      completeness: { complete: false, dualSource: false, truncated: false },
      warnings: ["SENSITIVE_OUTPUT_DETECTED"],
      sources: {
        cli: unavailableSource("salesforce-cli"),
        mcp: unavailableSource("salesforce-mcp", "0.30.15"),
      },
    };
    return { ...minimal, sha256: digest(minimal) };
  }
  return { ...withoutHash, sha256: digest(withoutHash) };
}

function safeString(value, maxLength = 160) {
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength) {
    throw new ReviewError("CLI_SCHEMA_MISMATCH", "INCOMPLETE");
  }
  return value;
}

function testExecutable(name, fallback) {
  if (!TEST_MODE) return fallback;
  return process.env[name] || fallback;
}

// GUI-launched VS Code on macOS inherits launchd's PATH (/usr/bin:/bin:/usr/sbin:/sbin),
// which misses every standard `sf` install location — the bare spawn then fails as
// CLI_UNAVAILABLE even though the CLI works in any terminal (live failure, 2026-08-04).
// POSIX execvp resolves the executable against the CHILD environment's PATH, so appending
// the standard prefixes here is enough; Windows terminals inherit the user PATH already.
const SPAWN_PATH = process.platform === "win32"
  ? process.env.PATH
  : [process.env.PATH, "/usr/local/bin", "/opt/homebrew/bin"].filter(Boolean).join(":");
const SPAWN_ENV = { ...process.env, PATH: SPAWN_PATH };

function runJsonProcess(command, args, runtime, failureCode) {
  return new Promise((resolvePromise, rejectPromise) => {
    let settled = false;
    let stdout = "";
    let stderrBytes = 0;
    const maxBytes = runtime.policy.maxVendorPayloadBytes;
    const child = spawn(command, args, {
      cwd: REPO_ROOT,
      env: SPAWN_ENV,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const finishError = (error) => {
      if (settled) return;
      settled = true;
      rejectPromise(error);
    };
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      finishError(new ReviewError("CLI_TIMEOUT", "INCOMPLETE"));
    }, runtime.policy.commandTimeoutSeconds * 1000);
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
      if (Buffer.byteLength(stdout, "utf8") > maxBytes) {
        child.kill("SIGKILL");
        finishError(new ReviewError("CLI_OUTPUT_TOO_LARGE", "INCOMPLETE"));
      }
    });
    child.stderr.on("data", (chunk) => {
      stderrBytes += chunk.length;
      if (stderrBytes > maxBytes) child.kill("SIGKILL");
    });
    child.on("error", () => finishError(new ReviewError(failureCode, "INCOMPLETE")));
    child.on("close", (code) => {
      clearTimeout(timer);
      if (settled) return;
      if (code !== 0) {
        finishError(new ReviewError(failureCode, "INCOMPLETE"));
        return;
      }
      try {
        const payload = JSON.parse(stdout);
        settled = true;
        resolvePromise(payload);
      } catch {
        finishError(new ReviewError("CLI_SCHEMA_MISMATCH", "INCOMPLETE"));
      }
    });
  });
}

async function cli(runtime, args, failureCode = "CLI_UNAVAILABLE") {
  const executable = testExecutable(
    "SF_HARNESS_SF_EXECUTABLE",
    process.platform === "win32" ? "sf.cmd" : "sf",
  );
  let baseArgs = [];
  if (TEST_MODE) {
    try {
      baseArgs = JSON.parse(process.env.SF_HARNESS_SF_ARGS_JSON || "[]");
    } catch {
      throw new ReviewError("CLI_UNAVAILABLE", "INCOMPLETE");
    }
    if (!Array.isArray(baseArgs) || baseArgs.some((item) => typeof item !== "string")) {
      throw new ReviewError("CLI_UNAVAILABLE", "INCOMPLETE");
    }
  }
  return runJsonProcess(executable, [...baseArgs, ...args], runtime, failureCode);
}

function requireSuccessfulCli(payload) {
  if (!payload || (payload.status !== undefined && payload.status !== 0)) {
    throw new ReviewError("CLI_SCHEMA_MISMATCH", "INCOMPLETE");
  }
  return payload.result;
}

async function collectCliIdentity(runtime) {
  const retrievedAt = now();
  const versionPayload = await cli(runtime, ["version", "--json"]);
  const cliVersion = safeString(versionPayload?.cliVersion, 80);
  const versionMatch = cliVersion.match(/^@salesforce\/cli\/(\d+)\./);
  if (!versionMatch || Number(versionMatch[1]) !== runtime.policy.salesforceCliMajor) {
    throw new ReviewError("CLI_VERSION_UNSUPPORTED");
  }

  const display = requireSuccessfulCli(
    await cli(runtime, ["org", "display", "--target-org", runtime.alias, "--json"]),
  );
  let instance;
  try {
    instance = new URL(String(display?.instanceUrl));
  } catch {
    throw new ReviewError("CLI_SCHEMA_MISMATCH");
  }
  const host = instance.hostname.toLowerCase();
  const expectedHost = runtime.pinned
    ? runtime.entry.expectedInstanceHost.toLowerCase()
    : runtime.discovered.host ?? host;
  if (
    instance.protocol !== "https:" ||
    instance.port ||
    instance.username ||
    instance.password ||
    instance.pathname !== "/" ||
    instance.search ||
    instance.hash ||
    host !== expectedHost ||
    !NON_PRODUCTION_HOST.test(host)
  ) {
    throw new ReviewError("IDENTITY_HOST_MISMATCH");
  }
  const displayOrgId = String(display?.id ?? display?.orgId ?? "");
  const expectedOrgId = runtime.pinned
    ? runtime.entry.expectedOrganizationId
    : runtime.discovered.orgId ?? displayOrgId;
  if (!ORG_ID.test(displayOrgId) || displayOrgId !== expectedOrgId) {
    throw new ReviewError("IDENTITY_ORG_ID_MISMATCH");
  }
  assertOrgIdPermitted(runtime, displayOrgId);

  const identityResult = requireSuccessfulCli(
    await cli(runtime, [
      "data",
      "query",
      "--query",
      runtime.policy.profiles.orgIdentity.query,
      "--target-org",
      runtime.alias,
      "--api-version",
      runtime.review.apiVersion,
      "--json",
    ]),
  );
  const records = identityResult?.records;
  if (!Array.isArray(records) || records.length !== 1) {
    throw new ReviewError("CLI_SCHEMA_MISMATCH");
  }
  if (records[0]?.Id !== expectedOrgId) {
    throw new ReviewError("IDENTITY_ORG_ID_MISMATCH");
  }
  const wantSandbox = !DEV_EDITION_HOST.test(host);
  if (records[0]?.IsSandbox !== wantSandbox) throw new ReviewError("NOT_SANDBOX");
  if (!runtime.pinned) {
    runtime.discovered.host = host;
    runtime.discovered.orgId = displayOrgId;
    runtime.discovered.isSandbox = wantSandbox;
  }
  return {
    proof: {
      expectedHostMatched: true,
      expectedOrgIdMatched: true,
      isSandbox: wantSandbox,
      // Reaching this point already proves it: the live host passed NON_PRODUCTION_HOST
      // above (or IDENTITY_HOST_MISMATCH) and IsSandbox matched what that host shape
      // implies (or NOT_SANDBOX). `isSandbox` stays as a description of the org — it is
      // legitimately false for a Developer Edition — while this is the security verdict.
      nonProduction: true,
    },
    source: { kind: "salesforce-cli", version: cliVersion, complete: true, retrievedAt },
  };
}

function mcpProcess() {
  if (TEST_MODE && process.env.SF_HARNESS_MCP_COMMAND) {
    let baseArgs = [];
    try {
      baseArgs = JSON.parse(process.env.SF_HARNESS_MCP_ARGS_JSON || "[]");
    } catch {
      throw new ReviewError("MCP_START_FAILED", "INCOMPLETE");
    }
    if (!Array.isArray(baseArgs) || baseArgs.some((item) => typeof item !== "string")) {
      throw new ReviewError("MCP_START_FAILED", "INCOMPLETE");
    }
    return { command: process.env.SF_HARNESS_MCP_COMMAND, baseArgs };
  }
  if (!existsSync(SALESFORCE_MCP_BIN)) {
    throw new ReviewError("MCP_START_FAILED", "INCOMPLETE");
  }
  return { command: process.execPath, baseArgs: [SALESFORCE_MCP_BIN] };
}

class McpJsonLineClient {
  constructor(runtime) {
    this.runtime = runtime;
    this.child = undefined;
    this.buffer = "";
    this.stdoutBytes = 0;
    this.nextId = 1;
    this.pending = new Map();
    this.closed = false;
  }

  async connect() {
    const processConfig = mcpProcess();
    const args = [
      ...processConfig.baseArgs,
      "--orgs",
      this.runtime.alias,
      "--tools",
      "run_soql_query",
      "--no-telemetry",
    ];
    this.child = spawn(processConfig.command, args, {
      cwd: REPO_ROOT,
      env: { ...SPAWN_ENV, SF_ORG_API_VERSION: this.runtime.review.apiVersion },
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.child.stdout.on("data", (chunk) => this.onData(chunk));
    this.child.stderr.on("data", () => {});
    this.child.on("error", () => this.failPending(new ReviewError("MCP_START_FAILED", "INCOMPLETE")));
    this.child.on("close", () => this.failPending(new ReviewError("MCP_TOOL_ERROR", "INCOMPLETE")));
    await this.request("initialize", {
      protocolVersion: this.runtime.policy.mcpProtocolVersion,
      capabilities: {},
      clientInfo: { name: "sf-harness-review-facade", version: "1.0.0" },
    });
    this.notify("notifications/initialized", {});
  }

  onData(chunk) {
    this.stdoutBytes += chunk.length;
    if (this.stdoutBytes > this.runtime.policy.maxVendorPayloadBytes) {
      this.failPending(new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE"));
      this.close();
      return;
    }
    this.buffer += chunk.toString("utf8");
    while (this.buffer.includes("\n")) {
      const index = this.buffer.indexOf("\n");
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (!line) continue;
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        this.failPending(new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE"));
        this.close();
        return;
      }
      if (message.id === undefined) continue;
      const pending = this.pending.get(String(message.id));
      if (!pending) continue;
      this.pending.delete(String(message.id));
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new ReviewError("MCP_TOOL_ERROR", "INCOMPLETE"));
      else pending.resolve(message.result);
    }
  }

  failPending(error) {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
  }

  request(method, params, timeoutSeconds) {
    if (!this.child?.stdin?.writable || this.closed) {
      return Promise.reject(new ReviewError("MCP_START_FAILED", "INCOMPLETE"));
    }
    const id = this.nextId++;
    return new Promise((resolvePromise, rejectPromise) => {
      const timer = setTimeout(() => {
        this.pending.delete(String(id));
        rejectPromise(new ReviewError("MCP_TIMEOUT", "INCOMPLETE"));
        this.close();
      }, (timeoutSeconds ?? this.runtime.policy.commandTimeoutSeconds) * 1000);
      this.pending.set(String(id), { resolve: resolvePromise, reject: rejectPromise, timer });
      this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }

  notify(method, params) {
    if (this.child?.stdin?.writable && !this.closed) {
      this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
    }
  }

  async query(profile, replacements = {}, timeoutSeconds) {
    let query = profile.query;
    for (const [token, value] of Object.entries(replacements)) {
      query = query.replace("${" + token + "}", value);
    }
    if (/\$\{[A-Z0-9_]+\}/.test(query)) {
      throw new ReviewError("QUERY_PROFILE_DENIED");
    }
    const result = await this.request("tools/call", {
      name: "run_soql_query",
      arguments: {
        query,
        usernameOrAlias: this.runtime.alias,
        directory: REPO_ROOT,
        useToolingApi: profile.useToolingApi,
      },
    }, timeoutSeconds);
    if (result?.isError === true || !Array.isArray(result?.content) || result.content.length !== 1) {
      throw new ReviewError("MCP_TOOL_ERROR", "INCOMPLETE");
    }
    const block = result.content[0];
    if (block?.type !== "text" || typeof block.text !== "string") {
      throw new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE");
    }
    const prefix = "SOQL query results:\n\n";
    if (!block.text.startsWith(prefix)) {
      throw new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE");
    }
    let payload;
    try {
      payload = JSON.parse(block.text.slice(prefix.length));
    } catch {
      throw new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE");
    }
    if (!Array.isArray(payload?.records) || payload.done !== true) {
      throw new ReviewError(payload?.done === false ? "RESULT_TRUNCATED" : "MCP_SCHEMA_MISMATCH", "INCOMPLETE");
    }
    return payload;
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    try {
      this.child?.stdin?.end();
      this.child?.kill();
    } catch {
      // Best-effort cleanup; raw child errors are never exposed.
    }
  }
}

async function withMcp(runtime, callback) {
  const client = new McpJsonLineClient(runtime);
  try {
    await client.connect();
    return await callback(client);
  } finally {
    client.close();
  }
}

function validateMcpIdentity(runtime, payload) {
  if (payload.records.length !== 1) throw new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE");
  const record = payload.records[0];
  const recordId = String(record?.Id ?? "");
  const expectedOrgId = runtime.pinned
    ? runtime.entry.expectedOrganizationId
    : runtime.discovered.orgId ?? recordId;
  if (!ORG_ID.test(recordId) || recordId !== expectedOrgId) {
    throw new ReviewError("IDENTITY_ORG_ID_MISMATCH");
  }
  assertOrgIdPermitted(runtime, recordId);
  // Fail closed when the CLI leg has not frozen an identity yet: the old
  // `?? record?.IsSandbox` fallback compared the record to ITSELF and always passed, so
  // this leg would have asserted its own truth. Unreachable today only because every
  // caller goes through cliIdentityGate first — which is not an invariant worth betting on.
  if (!runtime.pinned && runtime.discovered.isSandbox === null) {
    throw new ReviewError("NOT_SANDBOX");
  }
  const wantSandbox = runtime.pinned
    ? !DEV_EDITION_HOST.test(String(runtime.entry.expectedInstanceHost ?? ""))
    : runtime.discovered.isSandbox;
  if (typeof record?.IsSandbox !== "boolean" || record.IsSandbox !== wantSandbox) {
    throw new ReviewError("NOT_SANDBOX");
  }
  if (!runtime.pinned) {
    runtime.discovered.orgId = recordId;
    runtime.discovered.isSandbox = record.IsSandbox;
  }
  return { expectedOrgIdMatched: true, isSandbox: record.IsSandbox, nonProduction: true };
}

function normalizedPackage(namespace, name, version) {
  const safeNamespace = namespace === null || namespace === undefined || namespace === ""
    ? null
    : safeString(namespace, 80);
  return {
    namespace: safeNamespace,
    name: safeString(name),
    version: safeString(version, 80),
  };
}

function packageInScope(runtime, namespace) {
  return runtime.allowedPackageNamespaces.has("*") || runtime.allowedPackageNamespaces.has(namespace);
}

function normalizeCliPackages(runtime, result) {
  if (!Array.isArray(result)) throw new ReviewError("CLI_SCHEMA_MISMATCH", "INCOMPLETE");
  const scoped = result.filter((item) => packageInScope(runtime, item?.SubscriberPackageNamespace));
  if (scoped.length >= 500) throw new ReviewError("RESULT_TRUNCATED", "INCOMPLETE");
  return scoped.map((item) => normalizedPackage(
    item?.SubscriberPackageNamespace,
    item?.SubscriberPackageName,
    item?.SubscriberPackageVersionNumber,
  )).sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
}

function normalizeMcpPackages(runtime, payload) {
  const scoped = payload.records.filter((item) => packageInScope(runtime, item?.SubscriberPackage?.NamespacePrefix));
  if (scoped.length !== payload.records.length) {
    throw new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE");
  }
  if (scoped.length >= 500) throw new ReviewError("RESULT_TRUNCATED", "INCOMPLETE");
  return scoped.map((item) => {
    const versionRecord = item?.SubscriberPackageVersion;
    const version = [
      versionRecord?.MajorVersion,
      versionRecord?.MinorVersion,
      versionRecord?.PatchVersion,
      versionRecord?.BuildNumber,
    ];
    if (version.some((part) => !Number.isInteger(part) || part < 0)) {
      throw new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE");
    }
    return normalizedPackage(
      item?.SubscriberPackage?.NamespacePrefix,
      item?.SubscriberPackage?.Name,
      version.join("."),
    );
  }).sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
}

function cliTypeFamily(value) {
  const type = safeString(value, 80).toLowerCase();
  if (["string", "textarea", "email", "phone", "url", "encryptedstring", "combobox"].includes(type)) return "text";
  if (["double", "int", "currency", "percent"].includes(type)) return "number";
  if (["reference", "masterrecord"].includes(type)) return "reference";
  if (["picklist", "multipicklist"].includes(type)) return type;
  if (["boolean", "date", "datetime", "time", "base64", "address", "location", "id"].includes(type)) return type;
  return `other:${type}`;
}

function mcpTypeFamily(value) {
  const raw = safeString(value, 160).trim().toLowerCase();
  if (/^(text|long text area|rich text|html|encrypted text|email|phone|url|auto number)/.test(raw)) return "text";
  if (/^(number|currency|percent|formula \((number|currency|percent))/.test(raw)) return "number";
  if (/^(lookup|master-detail|hierarchy relationship|external lookup|indirect lookup)/.test(raw)) return "reference";
  if (/^multi-select picklist/.test(raw)) return "multipicklist";
  if (/^picklist/.test(raw)) return "picklist";
  if (/^(checkbox|formula \(checkbox)/.test(raw)) return "boolean";
  if (/^(date\/time|formula \(date\/time)/.test(raw)) return "datetime";
  if (/^(date|formula \(date)/.test(raw)) return "date";
  if (/^(time|formula \(time)/.test(raw)) return "time";
  if (/^geolocation/.test(raw)) return "location";
  if (/^address/.test(raw)) return "address";
  if (/^base64/.test(raw)) return "base64";
  if (/^id$/.test(raw)) return "id";
  return `other:${raw.replace(/\s+/g, "-")}`;
}

function normalizeCliObject(runtime, requested, result) {
  if (!result || result.name !== requested || !Array.isArray(result.fields)) {
    throw new ReviewError("CLI_SCHEMA_MISMATCH", "INCOMPLETE");
  }
  if (result.fields.length > runtime.review.maxFieldsPerObject) {
    throw new ReviewError("RESULT_TRUNCATED", "INCOMPLETE");
  }
  const fields = result.fields.map((field) => ({
    name: safeString(field?.name, 80),
    typeFamily: cliTypeFamily(field?.type),
  })).sort((left, right) => left.name.localeCompare(right.name));
  return { objectApiName: requested, exists: true, fields };
}

function normalizeMcpObject(runtime, requested, entity, fieldPayload) {
  if (entity.records.length > 1) throw new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE");
  if (entity.records.length === 0) {
    if (fieldPayload.records.length !== 0) throw new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE");
    return { objectApiName: requested, exists: false, fields: [] };
  }
  if (entity.records[0]?.QualifiedApiName !== requested) {
    throw new ReviewError("MCP_SCHEMA_MISMATCH", "INCOMPLETE");
  }
  if (fieldPayload.records.length > runtime.review.maxFieldsPerObject) {
    throw new ReviewError("RESULT_TRUNCATED", "INCOMPLETE");
  }
  const fields = fieldPayload.records.map((field) => ({
    name: safeString(field?.QualifiedApiName, 80),
    typeFamily: mcpTypeFamily(field?.DataType),
  })).sort((left, right) => left.name.localeCompare(right.name));
  return { objectApiName: requested, exists: true, fields };
}

async function captureSource(kind, version, operation) {
  try {
    const value = await operation();
    return { ok: true, value };
  } catch (error) {
    const normalized = error instanceof ReviewError
      ? error
      : new ReviewError("INTERNAL_ERROR", "BLOCKED");
    return {
      ok: false,
      error: normalized,
      source: unavailableSource(kind, version),
    };
  }
}

function comparison(fact, matches) {
  return { fact, result: matches ? "MATCH" : "MISMATCH" };
}

function failedEnvelope(runtime, reviewType, cliCapture, mcpCapture, target) {
  const captures = [cliCapture, mcpCapture];
  const blocked = captures.find((capture) => !capture.ok && capture.error.status === "BLOCKED");
  const warnings = captures.filter((capture) => !capture.ok).map((capture) => capture.error.code);
  const completeSourceCount = captures.filter((capture) => capture.ok).length;
  return makeEnvelope({
    runtime,
    reviewType,
    status: blocked ? "BLOCKED" : "INCOMPLETE",
    target,
    sources: {
      cli: cliCapture.ok ? cliCapture.value.source : cliCapture.source,
      mcp: mcpCapture.ok ? mcpCapture.value.source : mcpCapture.source,
    },
    facts: {},
    reconciliation: {
      status: completeSourceCount === 1 ? "SINGLE_SOURCE" : "NOT_RUN",
      comparisons: [],
    },
    completeness: { complete: false, dualSource: false, truncated: warnings.includes("RESULT_TRUNCATED") },
    warnings,
  });
}

async function cliIdentityGate(runtime, reviewType) {
  // Identity is frozen per alias for the server session (the dynamic lane already worked that
  // way). Re-proving it on every call added three CLI subprocesses per read without producing
  // a new fact; every MCP leg still re-checks org id and sandbox flag per query. Only success
  // is cached — failures stay retryable.
  if (runtime.identityProof) return { identity: runtime.identityProof };
  const capture = await captureSource("salesforce-cli", "unavailable", () => collectCliIdentity(runtime));
  if (capture.ok) {
    runtime.identityProof = capture.value;
    return { identity: capture.value };
  }
  return {
    envelope: makeEnvelope({
      runtime,
      reviewType,
      status: "BLOCKED",
      target: baseTarget(runtime),
      sources: {
        cli: capture.source,
        mcp: unavailableSource("salesforce-mcp", "0.30.15"),
      },
      facts: {},
      reconciliation: { status: "NOT_RUN", comparisons: [] },
      completeness: { complete: false, dualSource: false, truncated: false },
      warnings: [capture.error.code],
    }),
  };
}

async function reviewIdentity(runtime) {
  const gate = await cliIdentityGate(runtime, "org-identity");
  if (gate.envelope) return gate.envelope;
  const identity = gate.identity;
  const cliCapture = {
    ok: true,
    value: {
      ...identity,
      facts: {
        expectedOrgIdMatched: true,
        isSandbox: identity.proof.isSandbox === true,
        nonProduction: identity.proof.nonProduction === true,
      },
    },
  };
  const target = baseTarget(runtime, identity.proof);
  const mcpCapture = await captureSource("salesforce-mcp", "0.30.15", async () => {
    const retrievedAt = now();
    const facts = await withMcp(runtime, async (client) => validateMcpIdentity(
      runtime,
      await client.query(runtime.policy.profiles.orgIdentity),
    ));
    return {
      facts,
      source: { kind: "salesforce-mcp", version: "0.30.15", complete: true, retrievedAt },
    };
  });
  if (!cliCapture.ok || !mcpCapture.ok) {
    return failedEnvelope(runtime, "org-identity", cliCapture, mcpCapture, target);
  }
  return makeEnvelope({
    runtime,
    reviewType: "org-identity",
    status: "VERIFIED",
    target,
    sources: { cli: cliCapture.value.source, mcp: mcpCapture.value.source },
    facts: {
      identityPolicyMatched: true,
      isSandbox: identity.proof.isSandbox === true,
      nonProduction: identity.proof.nonProduction === true,
    },
    reconciliation: {
      status: "MATCH",
      comparisons: [comparison("organization-identity", true), comparison("is-sandbox", true)],
    },
    completeness: { complete: true, dualSource: true, truncated: false },
    warnings: [],
  });
}

async function reviewPackages(runtime) {
  const gate = await cliIdentityGate(runtime, "installed-packages");
  if (gate.envelope) return gate.envelope;
  const identity = gate.identity;
  const target = baseTarget(runtime, identity.proof);
  const cliCapture = await captureSource("salesforce-cli", identity.source.version, async () => {
    const packages = normalizeCliPackages(runtime, requireSuccessfulCli(await cli(runtime, [
      "package",
      "installed",
      "list",
      "--target-org",
      runtime.alias,
      "--api-version",
      runtime.review.apiVersion,
      "--json",
    ])));
    return {
      packages,
      source: { ...identity.source, retrievedAt: now(), complete: true },
    };
  });
  const mcpCapture = await captureSource("salesforce-mcp", "0.30.15", async () => {
    const retrievedAt = now();
    const packages = await withMcp(runtime, async (client) => {
      validateMcpIdentity(runtime, await client.query(runtime.policy.profiles.orgIdentity));
      // Empty scope: there is nothing to ask for. An `IN ()` list is not valid SOQL, so the
      // query is skipped rather than malformed — identity is still proven above.
      if (runtime.allowedPackageNamespaces.size === 0) return [];
      // "*": every installed package. A namespace IN-list cannot express that, so this uses
      // the separate fixed profile that omits the namespace predicate.
      if (runtime.allowedPackageNamespaces.has("*")) {
        return normalizeMcpPackages(
          runtime,
          await client.query(runtime.policy.profiles.installedPackagesAll),
        );
      }
      const namespaces = [...runtime.allowedPackageNamespaces]
        .sort()
        .map((namespace) => `'${namespace}'`)
        .join(",");
      return normalizeMcpPackages(
        runtime,
        await client.query(runtime.policy.profiles.installedPackages, { PACKAGE_NAMESPACES: namespaces }),
      );
    });
    return {
      packages,
      source: { kind: "salesforce-mcp", version: "0.30.15", complete: true, retrievedAt },
    };
  });
  if (!cliCapture.ok || !mcpCapture.ok) {
    return failedEnvelope(runtime, "installed-packages", cliCapture, mcpCapture, target);
  }
  const matches = JSON.stringify(cliCapture.value.packages) === JSON.stringify(mcpCapture.value.packages);
  return makeEnvelope({
    runtime,
    reviewType: "installed-packages",
    status: matches ? "VERIFIED" : "MISMATCH",
    target,
    sources: { cli: cliCapture.value.source, mcp: mcpCapture.value.source },
    facts: matches
      ? { packages: cliCapture.value.packages }
      : { packageCounts: { cli: cliCapture.value.packages.length, mcp: mcpCapture.value.packages.length } },
    reconciliation: { status: matches ? "MATCH" : "MISMATCH", comparisons: [comparison("installed-packages", matches)] },
    completeness: { complete: matches, dualSource: true, truncated: false },
    warnings: matches ? [] : ["EVIDENCE_MISMATCH"],
  });
}

async function reviewObject(runtime, input) {
  const objectApiName = input?.objectApiName;
  // "*" in the allowlist opts into all objects; the name is still validated by OBJECT_API_NAME.
  const objectAllowed = runtime.allowedObjects.has("*") || runtime.allowedObjects.has(objectApiName);
  if (!OBJECT_API_NAME.test(String(objectApiName ?? "")) || !objectAllowed) {
    return makeEnvelope({
      runtime,
      reviewType: "object-contract",
      status: "BLOCKED",
      facts: {},
      warnings: ["OBJECT_NOT_ALLOWLISTED"],
    });
  }
  const gate = await cliIdentityGate(runtime, "object-contract");
  if (gate.envelope) return gate.envelope;
  const identity = gate.identity;
  const target = baseTarget(runtime, identity.proof);
  const cliCapture = await captureSource("salesforce-cli", identity.source.version, async () => {
    const object = normalizeCliObject(runtime, objectApiName, requireSuccessfulCli(await cli(runtime, [
      "sobject",
      "describe",
      "--sobject",
      objectApiName,
      "--target-org",
      runtime.alias,
      "--api-version",
      runtime.review.apiVersion,
      "--json",
    ])));
    return {
      object,
      source: { ...identity.source, retrievedAt: now(), complete: true },
    };
  });
  const mcpCapture = await captureSource("salesforce-mcp", "0.30.15", async () => {
    const retrievedAt = now();
    const object = await withMcp(runtime, async (client) => {
      validateMcpIdentity(runtime, await client.query(runtime.policy.profiles.orgIdentity));
      const entity = await client.query(runtime.policy.profiles.objectEntity, { OBJECT_API_NAME: objectApiName });
      const fields = await client.query(runtime.policy.profiles.objectFields, { OBJECT_API_NAME: objectApiName });
      return normalizeMcpObject(runtime, objectApiName, entity, fields);
    });
    return {
      object,
      source: { kind: "salesforce-mcp", version: "0.30.15", complete: true, retrievedAt },
    };
  });
  if (!cliCapture.ok || !mcpCapture.ok) {
    return failedEnvelope(runtime, "object-contract", cliCapture, mcpCapture, target);
  }
  const matches = JSON.stringify(cliCapture.value.object) === JSON.stringify(mcpCapture.value.object);
  return makeEnvelope({
    runtime,
    reviewType: "object-contract",
    status: matches ? "VERIFIED" : "MISMATCH",
    target,
    sources: { cli: cliCapture.value.source, mcp: mcpCapture.value.source },
    facts: matches
      ? { object: cliCapture.value.object }
      : {
          objectApiName,
          observedExists: { cli: cliCapture.value.object.exists, mcp: mcpCapture.value.object.exists },
          fieldCounts: { cli: cliCapture.value.object.fields.length, mcp: mcpCapture.value.object.fields.length },
        },
    reconciliation: { status: matches ? "MATCH" : "MISMATCH", comparisons: [comparison("object-contract", matches)] },
    completeness: { complete: matches, dualSource: true, truncated: false },
    warnings: matches ? [] : ["EVIDENCE_MISMATCH"],
  });
}

function stripSoqlLiterals(query) {
  // Replace single-quoted literals (with escapes) by empty literals so FROM scanning cannot
  // be confused by quoted content. The raw query is what executes; this is scan-only.
  return query.replace(/'(?:\\.|[^'\\])*'/g, "''");
}

// Descriptive pass over a composed statement — NOT a validator (owner decision 2026-08-04:
// the statement blockade is removed). FROM extraction feeds the envelope's fromObjects fact,
// which the org-sampling executor keys on, and the optional configured object allowlist. The
// statement itself executes verbatim.
function describeComposedSoql(rawQuery, useToolingApi, runtime) {
  if (typeof rawQuery !== "string" || rawQuery.length < 8 || rawQuery.length > 4000) {
    return { ok: false, warning: "QUERY_VALIDATION_DENIED" };
  }
  if (useToolingApi !== undefined && typeof useToolingApi !== "boolean") {
    return { ok: false, warning: "QUERY_VALIDATION_DENIED" };
  }
  if (rawQuery.includes("${")) {
    // '${' is the profile-substitution token; a residual would be rejected downstream anyway.
    return { ok: false, warning: "QUERY_VALIDATION_DENIED" };
  }
  const fromTargets = [
    ...stripSoqlLiterals(rawQuery).matchAll(/\bFROM\s+([A-Za-z][A-Za-z0-9_]*)\b/gi),
  ].map((match) => match[1]);
  if (!runtime.allowedObjects.has("*")) {
    // An explicitly configured allowlist is the owner's data-scoping choice for an org holding
    // sensitive data and stays honored; the default (absent key = "*") restricts nothing.
    for (const target of fromTargets) {
      if (!runtime.allowedObjects.has(target)) {
        return { ok: false, warning: "OBJECT_NOT_ALLOWLISTED" };
      }
    }
  }
  return {
    ok: true,
    fromObjects: [...new Set(fromTargets)].sort(),
    useToolingApi: useToolingApi === true,
  };
}

function stripAttributes(value) {
  // Vendor `attributes` blocks carry record URLs (instance host noise), never queried data.
  if (Array.isArray(value)) return value.map(stripAttributes);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => key !== "attributes")
        .map(([key, entry]) => [key, stripAttributes(entry)]),
    );
  }
  return value;
}

async function reviewSoqlQuery(runtime, input) {
  const description = describeComposedSoql(input?.query, input?.useToolingApi, runtime);
  if (!description.ok) {
    return makeEnvelope({
      runtime,
      reviewType: "soql-query",
      status: "BLOCKED",
      facts: {},
      warnings: [description.warning],
    });
  }
  const gate = await cliIdentityGate(runtime, "soql-query");
  if (gate.envelope) return gate.envelope;
  const identity = gate.identity;
  const target = baseTarget(runtime, identity.proof);
  // The CLI contributes the session identity proof only; the statement and its rows travel
  // exclusively through the pinned Salesforce MCP child. Result values are single-source by
  // design (IDENTITY_MATCH_ONLY) — two transports would race a volatile dataset, not
  // corroborate it.
  const cliCapture = {
    ok: true,
    value: { source: { ...identity.source, retrievedAt: now(), complete: true } },
  };
  const mcpCapture = await captureSource("salesforce-mcp", "0.30.15", async () => {
    const retrievedAt = now();
    const payload = await withMcp(runtime, async (client) => {
      validateMcpIdentity(runtime, await client.query(runtime.policy.profiles.orgIdentity));
      return client.query(
        { query: input.query, useToolingApi: description.useToolingApi },
        {},
        runtime.policy.soqlQueryTimeoutSeconds,
      );
    });
    return { payload, source: { kind: "salesforce-mcp", version: "0.30.15", complete: true, retrievedAt } };
  });
  if (!mcpCapture.ok) {
    return failedEnvelope(runtime, "soql-query", cliCapture, mcpCapture, target);
  }
  const records = stripAttributes(mcpCapture.value.payload.records);
  return makeEnvelope({
    runtime,
    reviewType: "soql-query",
    status: "VERIFIED",
    target,
    sources: { cli: cliCapture.value.source, mcp: mcpCapture.value.source },
    facts: {
      soqlQuery: {
        // The digest binds the envelope to EXACTLY the submitted statement — the org-sampling
        // executor refuses an attach when the facade executed different text.
        queryDigest: createHash("sha256").update(input.query, "utf8").digest("hex"),
        fromObjects: description.fromObjects,
        useToolingApi: description.useToolingApi,
        matched: records.length,
        records,
      },
    },
    reconciliation: {
      status: "IDENTITY_MATCH_ONLY",
      comparisons: [comparison("organization-identity", true), comparison("is-sandbox", true)],
    },
    completeness: { complete: true, dualSource: false, truncated: false },
    warnings: [],
    sensitiveGateExempt: true,
  });
}

function validateToolInput(name, input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) return false;
  const keys = Object.keys(input);
  if (name === "review_object_contract") return keys.length === 1 && keys[0] === "objectApiName";
  if (name === "review_soql_query") {
    if (keys.length === 1) return keys[0] === "query";
    if (keys.length === 2) return keys.includes("query") && keys.includes("useToolingApi");
    return false;
  }
  return keys.length === 0;
}

async function callReviewTool(runtime, name, input) {
  if (!TOOL_DEFINITIONS.some((tool) => tool.name === name) || !validateToolInput(name, input)) {
    const blockedReviewType = name === "review_object_contract"
      ? "object-contract"
      : name === "review_soql_query"
        ? "soql-query"
        : "org-identity";
    return makeEnvelope({
      runtime,
      reviewType: blockedReviewType,
      status: "BLOCKED",
      facts: {},
      warnings: ["QUERY_PROFILE_DENIED"],
    });
  }
  if (name === "review_org_identity") return reviewIdentity(runtime);
  if (name === "review_installed_packages") return reviewPackages(runtime);
  if (name === "review_configured_orgs") return reviewConfiguredOrgs(runtime);
  if (name === "review_soql_query") return reviewSoqlQuery(runtime, input);
  return reviewObject(runtime, input);
}

function reviewConfiguredOrgs(runtime) {
  // Wrapper-side scoped enumeration: the response is built purely from the local config, so the
  // agent can never observe orgs the developer is authenticated to but has not configured. No org
  // ids or instance hosts are included (the sensitive-material gate would redact them anyway).
  const config = readJson(CONFIG_PATH, "CONFIG_MISSING");
  if (config?.safety?.allowScopedEnumeration !== true) {
    return makeEnvelope({
      runtime,
      reviewType: "configured-orgs",
      status: "BLOCKED",
      facts: {},
      warnings: ["SCOPED_ENUMERATION_DISABLED"],
    });
  }
  const orgs = (config?.salesforce?.orgs ?? [])
    .filter((entry) => entry && typeof entry.alias === "string")
    .map((entry) => ({
      alias: entry.alias,
      environment: entry.environment ?? null,
    }));
  return makeEnvelope({
    runtime,
    reviewType: "configured-orgs",
    status: "VERIFIED",
    facts: { orgCount: orgs.length, orgs },
    reconciliation: { status: "NOT_RUN", comparisons: [] },
    completeness: { complete: true, dualSource: false, truncated: false },
    warnings: [],
  });
}

function writeMessage(message) {
  const serialized = JSON.stringify(message);
  if (Buffer.byteLength(serialized, "utf8") > MAX_OUTER_MESSAGE_BYTES) {
    throw new ReviewError("CLI_OUTPUT_TOO_LARGE");
  }
  process.stdout.write(`${serialized}\n`);
}

async function handleProtocolMessage(runtime, message) {
  if (!message || message.jsonrpc !== "2.0" || typeof message.method !== "string") return;
  if (message.id === undefined) return;
  try {
    let result;
    if (message.method === "initialize") {
      result = {
        protocolVersion: runtime.policy.mcpProtocolVersion,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "sf-harness-salesforce-review", version: "1.0.0" },
        instructions: "Use only normalized reconciliation evidence. MISMATCH, INCOMPLETE, and BLOCKED are never confirmed facts. review_soql_query values are single-source sandbox observations — sanitized, bounded, and timestamped; cite them with the org context and observation time, never as production truth.",
      };
    } else if (message.method === "ping") {
      result = {};
    } else if (message.method === "tools/list") {
      result = { tools: TOOL_DEFINITIONS };
    } else if (message.method === "tools/call") {
      const envelope = await callReviewTool(
        runtime,
        message.params?.name,
        message.params?.arguments ?? {},
      );
      result = {
        content: [{ type: "text", text: JSON.stringify(envelope) }],
        structuredContent: envelope,
        isError: envelope.status === "BLOCKED",
      };
    } else {
      writeMessage({
        jsonrpc: "2.0",
        id: message.id,
        error: { code: -32601, message: "Method not found" },
      });
      return;
    }
    writeMessage({ jsonrpc: "2.0", id: message.id, result });
  } catch (error) {
    const code = error instanceof ReviewError ? error.code : "INTERNAL_ERROR";
    writeMessage({
      jsonrpc: "2.0",
      id: message.id,
      error: { code: -32000, message: code },
    });
  }
}

async function main() {
  const alias = parseServerArgs(process.argv.slice(2));
  const runtime = loadRuntime(alias);
  let buffer = "";
  let bytes = 0;
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    bytes += Buffer.byteLength(chunk, "utf8");
    if (bytes > MAX_OUTER_MESSAGE_BYTES) {
      process.stderr.write("Salesforce review facade blocked: MCP_SCHEMA_MISMATCH\n");
      process.exit(2);
    }
    buffer += chunk;
    while (buffer.includes("\n")) {
      const index = buffer.indexOf("\n");
      const line = buffer.slice(0, index).trim();
      buffer = buffer.slice(index + 1);
      bytes = Buffer.byteLength(buffer, "utf8");
      if (!line) continue;
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        process.stderr.write("Salesforce review facade blocked: MCP_SCHEMA_MISMATCH\n");
        process.exit(2);
      }
      void handleProtocolMessage(runtime, message);
    }
  });
}

main().catch((error) => {
  const code = error instanceof ReviewError ? error.code : "INTERNAL_ERROR";
  process.stderr.write(`Salesforce review facade blocked: ${code}\n`);
  process.exit(2);
});
