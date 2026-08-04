#!/usr/bin/env node
/**
 * Knowledge MCP facade — read-only search surface over the governed Knowledge store.
 *
 * Exposes the existing Knowledge executors as first-class MCP tools so retrieval competes
 * with native file search inside the model's tool schema instead of relying on prose
 * instructions. The wrapper adds NO search logic: every tool call spawns one allowlisted
 * subcommand of an existing executor, parses its JSON stdout, and passes it through.
 *
 * Hard rules enforced here, not by prompts:
 * - SUBCOMMAND_ALLOWLIST is the only reachable executor surface. Every write-capable
 *   subcommand (entry-draft, entry-approve, feature-*, entry-org-attach, resolve --write,
 *   ...) is unreachable by construction; tests/test_knowledge_mcp_contract.py pins this.
 * - The interpreter is resolved at startup and must import yaml, or startup fails loudly:
 *   a missing dev dependency must surface as a server error, never as silent agent
 *   fallback to force-app grep.
 * - Paths are resolved from this file's location; cwd is never trusted.
 * - Per-call timeout and output cap return a normalized error, never truncated JSON.
 * - INDEX STALE from knowledge_search.py triggers one build + one retry (owner decision
 *   D2). `build` writes only the gitignored generated cache, so the read-only line holds.
 */

import { spawn, spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(SCRIPT_DIR, "..");
const PROTOCOL_VERSION = "2025-06-18";
const SERVER_VERSION = "1.0.0";
const MAX_OUTER_MESSAGE_BYTES = 1_048_576;
// Below half the outer cap: the envelope is embedded twice in a tools/call response
// (content[0].text and structuredContent), so an executor result must fit twice plus
// framing, or the outer cap would fire with a less actionable error.
const MAX_EXECUTOR_OUTPUT_BYTES = 480_000;
const CALL_TIMEOUT_MS = 60_000;
const PROBE_TIMEOUT_MS = 15_000;
const MAX_STRING_INPUT = 400;
const STALE_INDEX_REASON = /^INDEX STALE/;

// The only executor surface reachable through this server. `build` is spawnable by the
// stale-index retry alone — no tool maps to it. Data, not code, so the contract test can
// pin it against the argparse trees. The full read surface of knowledge_search.py is
// exposed (owner decision 2026-08-04: definitions go MCP-only, no CLI dual-path); the
// write-capable stores stay pinned to their single read subcommand.
export const SUBCOMMAND_ALLOWLIST = Object.freeze({
  "knowledge_search.py": Object.freeze([
    "context",
    "search",
    "impact",
    "build",
    "explain",
    "tree",
    "feature-drift",
    "feature-dossier",
    "edge-health",
    "capabilities",
  ]),
  "knowledge_store.py": Object.freeze(["entry-status"]),
  // `inventory` is spawnable by the missing-inventory self-heal alone — no tool maps to
  // it. Like `build`, it writes only the gitignored generated cache.
  "force_app_knowledge.py": Object.freeze(["resolve", "inventory"]),
});

export const TOOL_EXECUTORS = Object.freeze({
  knowledge_context: Object.freeze({ script: "knowledge_search.py", subcommand: "context" }),
  knowledge_search: Object.freeze({ script: "knowledge_search.py", subcommand: "search" }),
  knowledge_impact: Object.freeze({ script: "knowledge_search.py", subcommand: "impact" }),
  knowledge_resolve: Object.freeze({ script: "force_app_knowledge.py", subcommand: "resolve" }),
  knowledge_entry_status: Object.freeze({ script: "knowledge_store.py", subcommand: "entry-status" }),
  knowledge_explain: Object.freeze({ script: "knowledge_search.py", subcommand: "explain" }),
  knowledge_tree: Object.freeze({ script: "knowledge_search.py", subcommand: "tree" }),
  knowledge_feature_drift: Object.freeze({ script: "knowledge_search.py", subcommand: "feature-drift" }),
  knowledge_feature_dossier: Object.freeze({ script: "knowledge_search.py", subcommand: "feature-dossier" }),
  knowledge_edge_health: Object.freeze({ script: "knowledge_search.py", subcommand: "edge-health" }),
  knowledge_capabilities: Object.freeze({ script: "knowledge_search.py", subcommand: "capabilities" }),
});

const STEERING =
  "Use this BEFORE searching force-app files for any repository-source question (what a " +
  "component declares, what touches a field, what depends on what). Native file search " +
  "over force-app is the fallback after NO_ENTRY — report the gap as missing Knowledge — " +
  "and the verification step before citing or editing source.";

const IDENTITY_HINT =
  "Exact identity `<MetadataType>:<ns|c>:<FullName>` — use knowledge_resolve first to turn " +
  "a bare name or file path into one.";

const FEATURE_HINT = "Feature slug — lowercase alphanumeric with single hyphens.";

export const TOOL_DEFINITIONS = Object.freeze([
  {
    name: "knowledge_context",
    title: "Composed Knowledge pack for one artifact",
    description:
      `${STEERING} One composed pack for a single artifact: parts, usage, permissions, ` +
      "coverage, dependency chains. Default first lookup when the identity is known. " +
      "NO_ENTRY means no approved Knowledge Entry projects this identity in the current " +
      "index generation — it is NOT evidence the artifact is absent from force-app. " +
      "Results are not citable; cite only via knowledge_entry_status.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["identity"],
      properties: {
        identity: { type: "string", maxLength: MAX_STRING_INPUT, description: IDENTITY_HINT },
        top: { type: "integer", minimum: 1, maximum: 50, description: "Cap per result section." },
        direction: {
          type: "string",
          enum: ["incoming", "outgoing"],
          description: "Direction of the chains traversal only; edge sections always report both.",
        },
        includeHeuristic: { type: "boolean", description: "Also traverse heuristic edges." },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "knowledge_search",
    title: "Typed retrieval over approved Knowledge entries",
    description:
      `${STEERING} Free text, exact identity, facets (key[:op]=value), dependency anchors, ` +
      "or a pasted error message (mode=intentional-flow-error). NO_MATCH or NO_ENTRY is " +
      "absence of an approved entry, NOT absence of the artifact. Multi-hit or ambiguous " +
      "results are never resolved by silently taking the top hit — narrow the query or ask. " +
      "Hits carry only a profileDigest and are not citable; cite via knowledge_entry_status.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        text: { type: "string", maxLength: MAX_STRING_INPUT, description: "Free-text query or pasted error message." },
        identity: { type: "string", maxLength: MAX_STRING_INPUT, description: IDENTITY_HINT },
        metadataType: { type: "string", maxLength: MAX_STRING_INPUT, description: "Filter by metadata type, e.g. CustomObject." },
        namespace: { type: "string", maxLength: MAX_STRING_INPUT, description: "Filter by namespace (`c` for local)." },
        facet: {
          type: "array",
          maxItems: 8,
          items: { type: "string", maxLength: MAX_STRING_INPUT },
          description: "Facet filters, each `key[:op]=value`; see `capabilities` in the CLI for the menu.",
        },
        relationAnchor: { type: "string", maxLength: MAX_STRING_INPUT, description: "Identity to anchor a dependency search on." },
        relationKind: { type: "string", maxLength: MAX_STRING_INPUT, description: "Restrict anchored search to one edge kind." },
        direction: { type: "string", enum: ["incoming", "outgoing"], description: "Edge direction for anchored search." },
        includeHeuristic: { type: "boolean", description: "Also match heuristic edges." },
        mode: { type: "string", enum: ["hybrid", "intentional-flow-error"], description: "intentional-flow-error matches pasted Flow/VR error surfaces." },
        top: { type: "integer", minimum: 1, maximum: 50, description: "Result cap (default 10)." },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "knowledge_impact",
    title: "Bounded dependency traversal from one identity",
    description:
      `${STEERING} direction=incoming answers "what breaks if I change this"; ` +
      'direction=outgoing answers "how does this work / what does it reach" and usually ' +
      "needs includeHeuristic=true to see heuristic edges. NO_ENTRY is a Knowledge gap, " +
      "not artifact absence.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["identity"],
      properties: {
        identity: { type: "string", maxLength: MAX_STRING_INPUT, description: IDENTITY_HINT },
        direction: { type: "string", enum: ["incoming", "outgoing"], description: "Default incoming." },
        depth: { type: "integer", minimum: 1, maximum: 2, description: "Traversal depth (default 1; 2 is the executor's impact limit)." },
        top: { type: "integer", minimum: 1, maximum: 50, description: "Cap per level." },
        includeHeuristic: { type: "boolean", description: "Also traverse heuristic edges." },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "knowledge_resolve",
    title: "Resolve names or paths to exact Knowledge identities",
    description:
      "Turn bare component names or force-app file paths into exact Knowledge identities " +
      "(`<MetadataType>:<ns|c>:<FullName>`) with lane and documentation status. Use it " +
      "whenever you have a name or a path but not an identity, before knowledge_context " +
      "or knowledge_impact. resolution=ambiguous is never resolved by blindly picking a " +
      "suggestion — narrow or ask; unmatched means the inventory does not know the name, " +
      "NOT that the artifact is absent.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        names: {
          type: "array",
          maxItems: 40,
          items: { type: "string", maxLength: MAX_STRING_INPUT },
          description: "Component names, ids, or source-file basenames.",
        },
        paths: {
          type: "array",
          maxItems: 40,
          items: { type: "string", maxLength: MAX_STRING_INPUT },
          description: "force-app file or directory paths.",
        },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "knowledge_entry_status",
    title: "Citable lane receipt for one Knowledge entry",
    description:
      "The ONLY citable receipt for Knowledge: the computed lane for one identity. Call it " +
      "before citing any entry in an answer or record — search and context hits carry only " +
      "a profileDigest and hand-built entryRefs are rejected by validation.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["identity"],
      properties: {
        identity: { type: "string", maxLength: MAX_STRING_INPUT, description: IDENTITY_HINT },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "knowledge_explain",
    title: "Full usage table for one artifact (deep dive)",
    description:
      "One artifact with its full usage and reverse-usage tables. Start with " +
      "knowledge_context; call this when the context pack's summary is not enough. " +
      "NO_ENTRY / an unknown-identity error is a Knowledge gap, not artifact absence.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["identity"],
      properties: {
        identity: { type: "string", maxLength: MAX_STRING_INPUT, description: IDENTITY_HINT },
        top: { type: "integer", minimum: 1, maximum: 50, description: "Cap per usage table." },
        includeHeuristic: { type: "boolean", description: "Also list heuristic edges." },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "knowledge_tree",
    title: "Current membership of an approved feature boundary",
    description:
      "Walk an approved feature's boundary rule and report current membership. " +
      "direction=outgoing is exploratory only — the approved membership digest is defined " +
      "on the incoming traversal.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["feature"],
      properties: {
        feature: { type: "string", maxLength: MAX_STRING_INPUT, description: FEATURE_HINT },
        direction: { type: "string", enum: ["incoming", "outgoing"], description: "Traversal direction (default incoming)." },
        includeHeuristic: { type: "boolean", description: "Also traverse heuristic edges." },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "knowledge_feature_drift",
    title: "Feature membership drift since approval",
    description:
      "What a feature's membership did since its boundary was approved — additions, " +
      "losses, and lane changes against the approved digest.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["feature"],
      properties: {
        feature: { type: "string", maxLength: MAX_STRING_INPUT, description: FEATURE_HINT },
        includeHeuristic: { type: "boolean", description: "Also traverse heuristic edges." },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "knowledge_feature_dossier",
    title: "Feature dossier rendered from the approved boundary",
    description:
      "Render a feature dossier from its approved boundary rule: members, lanes, and " +
      "the evidence trail. Read-only rendering; nothing is written.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["feature"],
      properties: {
        feature: { type: "string", maxLength: MAX_STRING_INPUT, description: FEATURE_HINT },
        includeHeuristic: { type: "boolean", description: "Also traverse heuristic edges." },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "knowledge_edge_health",
    title: "Edge-resolution diagnostics for the current index",
    description:
      "How edge targets resolve to entries in this index generation — the store " +
      "diagnostics surface for curation work, not a step-1 lookup.",
    inputSchema: { type: "object", additionalProperties: false, properties: {} },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
  {
    name: "knowledge_capabilities",
    title: "Valid facets, operators, and modes for knowledge_search",
    description:
      "The menu of valid facet keys, operators, states, and modes. Call it before " +
      "composing facet queries instead of guessing keys — an unknown facet is an error, " +
      "not an empty result.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        metadataType: { type: "string", maxLength: MAX_STRING_INPUT, description: "Narrow the facet menu to one metadata type." },
      },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  },
]);

class KnowledgeError extends Error {
  constructor(reason) {
    super(reason);
    this.name = "KnowledgeError";
    this.reason = reason;
  }
}

function assertAllowlisted(script, subcommand) {
  const allowed = SUBCOMMAND_ALLOWLIST[script];
  if (!allowed || !allowed.includes(subcommand)) {
    throw new KnowledgeError(`DISALLOWED EXECUTOR: ${script} ${subcommand}`);
  }
}

// Manual validation mirroring the inputSchema exactly: unknown keys, types, enums, and
// bounds all reject with a normalized reason instead of reaching the executor.
function validateToolInput(name, input) {
  const definition = TOOL_DEFINITIONS.find((tool) => tool.name === name);
  const schema = definition.inputSchema;
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    return "arguments must be an object";
  }
  for (const key of Object.keys(input)) {
    if (!schema.properties[key]) return `unknown argument: ${key}`;
  }
  for (const required of schema.required ?? []) {
    if (input[required] === undefined) return `missing required argument: ${required}`;
  }
  for (const [key, value] of Object.entries(input)) {
    const spec = schema.properties[key];
    if (spec.type === "string") {
      if (typeof value !== "string" || value.length === 0 || value.length > spec.maxLength) {
        return `argument ${key} must be a non-empty string of at most ${spec.maxLength} characters`;
      }
      if (spec.enum && !spec.enum.includes(value)) {
        return `argument ${key} must be one of: ${spec.enum.join(", ")}`;
      }
    } else if (spec.type === "integer") {
      if (!Number.isInteger(value) || value < spec.minimum || value > spec.maximum) {
        return `argument ${key} must be an integer between ${spec.minimum} and ${spec.maximum}`;
      }
    } else if (spec.type === "boolean") {
      if (typeof value !== "boolean") return `argument ${key} must be a boolean`;
    } else if (spec.type === "array") {
      if (!Array.isArray(value) || value.length > spec.maxItems) {
        return `argument ${key} must be an array of at most ${spec.maxItems} items`;
      }
      for (const item of value) {
        if (typeof item !== "string" || item.length === 0 || item.length > spec.items.maxLength) {
          return `argument ${key} items must be non-empty strings of at most ${spec.items.maxLength} characters`;
        }
      }
    }
  }
  if (name === "knowledge_search") {
    const selectors = ["text", "identity", "metadataType", "namespace", "facet", "relationAnchor"];
    if (!selectors.some((key) => input[key] !== undefined && (!Array.isArray(input[key]) || input[key].length > 0))) {
      return `at least one of ${selectors.join(", ")} is required`;
    }
  }
  if (name === "knowledge_resolve") {
    if (!(input.names?.length || input.paths?.length)) {
      return "at least one of names, paths is required";
    }
  }
  return null;
}

// Values are always passed as single `--flag=value` tokens so a value can never be
// misread as a flag by argparse, and --write is unconstructable for resolve.
function argvForTool(name, input) {
  const { subcommand } = TOOL_EXECUTORS[name];
  const argv = [subcommand];
  if (name === "knowledge_resolve") {
    for (const value of input.names ?? []) argv.push(`--name=${value}`);
    for (const value of input.paths ?? []) argv.push(`--path=${value}`);
    return argv;
  }
  if (name === "knowledge_entry_status") {
    argv.push(`--identity=${input.identity}`);
    return argv;
  }
  if (input.identity !== undefined) argv.push(`--identity=${input.identity}`);
  if (input.feature !== undefined) argv.push(`--feature=${input.feature}`);
  if (input.text !== undefined) argv.push(`--text=${input.text}`);
  if (input.metadataType !== undefined) argv.push(`--metadata-type=${input.metadataType}`);
  if (input.namespace !== undefined) argv.push(`--namespace=${input.namespace}`);
  for (const value of input.facet ?? []) argv.push(`--facet=${value}`);
  if (input.relationAnchor !== undefined) argv.push(`--relation-anchor=${input.relationAnchor}`);
  if (input.relationKind !== undefined) argv.push(`--relation-kind=${input.relationKind}`);
  if (input.direction !== undefined) argv.push(`--direction=${input.direction}`);
  if (input.mode !== undefined) argv.push(`--mode=${input.mode}`);
  if (input.depth !== undefined) argv.push(`--depth=${input.depth}`);
  if (input.top !== undefined) argv.push(`--top=${input.top}`);
  if (input.includeHeuristic) argv.push("--include-heuristic");
  return argv;
}

function interpreterCandidates() {
  const candidates = [];
  if (process.env.KNOWLEDGE_MCP_PYTHON) candidates.push([process.env.KNOWLEDGE_MCP_PYTHON]);
  candidates.push(
    [join(REPO_ROOT, ".venv", "bin", "python")],
    [join(REPO_ROOT, ".venv", "Scripts", "python.exe")],
    ["py", "-3"],
    ["python3"],
    ["python"],
  );
  return candidates;
}

export function resolveInterpreter() {
  for (const candidate of interpreterCandidates()) {
    const probe = spawnSync(candidate[0], [...candidate.slice(1), "-c", "import yaml"], {
      timeout: PROBE_TIMEOUT_MS,
      stdio: "ignore",
    });
    if (!probe.error && probe.status === 0) return candidate;
  }
  return null;
}

function runExecutor(python, scriptName, argv) {
  return new Promise((resolvePromise) => {
    const child = spawn(
      python[0],
      [...python.slice(1), join(REPO_ROOT, "scripts", scriptName), ...argv],
      { cwd: REPO_ROOT, stdio: ["ignore", "pipe", "pipe"] },
    );
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (envelope) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolvePromise(envelope);
    };
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      finish({
        outcome: "ERROR",
        reason: `EXECUTOR TIMEOUT: ${scriptName} ${argv[0]} exceeded ${CALL_TIMEOUT_MS} ms`,
      });
    }, CALL_TIMEOUT_MS);
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      if (Buffer.byteLength(stdout, "utf8") > MAX_EXECUTOR_OUTPUT_BYTES) {
        child.kill("SIGKILL");
        finish({
          outcome: "ERROR",
          reason:
            `EXECUTOR OUTPUT CAP EXCEEDED (${MAX_EXECUTOR_OUTPUT_BYTES} bytes): ` +
            "narrow the query (lower top, tighter facets) instead of reading a truncated body",
        });
      }
    });
    child.stderr.on("data", (chunk) => {
      if (Buffer.byteLength(stderr, "utf8") < 4096) stderr += chunk;
    });
    child.on("error", (error) => {
      finish({ outcome: "ERROR", reason: `EXECUTOR SPAWN FAILED: ${scriptName}: ${error.code ?? error.message}` });
    });
    child.on("close", (code) => {
      if (settled) return;
      try {
        finish(JSON.parse(stdout));
      } catch {
        const detail = (stderr || stdout).slice(0, 200).replaceAll("\n", " ").trim();
        finish({
          outcome: "ERROR",
          reason: `EXECUTOR OUTPUT NOT JSON (${scriptName} exit ${code}): ${detail}`,
        });
      }
    });
  });
}

function isStaleIndex(envelope) {
  return (
    envelope !== null &&
    typeof envelope === "object" &&
    envelope.outcome === "ERROR" &&
    typeof envelope.reason === "string" &&
    STALE_INDEX_REASON.test(envelope.reason)
  );
}

// resolve on a fresh checkout fails with a non-JSON "force-app inventory is missing" —
// the same generated-cache class as INDEX STALE, healed the same bounded way (D2).
const MISSING_INVENTORY_REASON = /inventory is missing/;

function isMissingInventory(envelope) {
  return (
    envelope !== null &&
    typeof envelope === "object" &&
    envelope.outcome === "ERROR" &&
    typeof envelope.reason === "string" &&
    MISSING_INVENTORY_REASON.test(envelope.reason)
  );
}

async function callKnowledgeTool(python, name, input) {
  if (!TOOL_EXECUTORS[name]) throw new KnowledgeError(`UNKNOWN TOOL: ${name}`);
  const problem = validateToolInput(name, input);
  if (problem) throw new KnowledgeError(`INVALID INPUT: ${problem}`);
  const executor = TOOL_EXECUTORS[name];
  assertAllowlisted(executor.script, executor.subcommand);
  const argv = argvForTool(name, input);
  let result = await runExecutor(python, executor.script, argv);
  if (isStaleIndex(result) && executor.script === "knowledge_search.py") {
    // Owner decision D2: one bounded rebuild of the gitignored generated cache, then one
    // retry, so the INDEX STALE -> build -> retry dance never reaches the agent.
    assertAllowlisted("knowledge_search.py", "build");
    const rebuild = await runExecutor(python, "knowledge_search.py", ["build"]);
    if (rebuild?.outcome === "BUILT") {
      result = await runExecutor(python, executor.script, argv);
    } else {
      return rebuild;
    }
  }
  if (isMissingInventory(result) && executor.script === "force_app_knowledge.py") {
    assertAllowlisted("force_app_knowledge.py", "inventory");
    const rebuilt = await runExecutor(python, "force_app_knowledge.py", ["inventory"]);
    if (rebuilt?.status === "complete") {
      result = await runExecutor(python, executor.script, argv);
    } else {
      return rebuilt;
    }
  }
  return result;
}

function writeMessage(message) {
  const serialized = JSON.stringify(message);
  if (Buffer.byteLength(serialized, "utf8") > MAX_OUTER_MESSAGE_BYTES) {
    throw new KnowledgeError("RESULT TOO LARGE FOR ONE MESSAGE: narrow the query");
  }
  process.stdout.write(`${serialized}\n`);
}

async function handleProtocolMessage(python, message) {
  if (!message || message.jsonrpc !== "2.0" || typeof message.method !== "string") return;
  if (message.id === undefined) return;
  try {
    let result;
    if (message.method === "initialize") {
      result = {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "sf-harness-knowledge", version: SERVER_VERSION },
        instructions:
          `${STEERING} NO_ENTRY / NO_MATCH is absence of an approved entry, never proof ` +
          "the artifact is absent from force-app — report it as a Knowledge gap. Ambiguous " +
          "results are never resolved by picking the top hit. Cite entries only via " +
          "knowledge_entry_status, never from a search or context hit.",
      };
    } else if (message.method === "ping") {
      result = {};
    } else if (message.method === "tools/list") {
      result = { tools: TOOL_DEFINITIONS };
    } else if (message.method === "tools/call") {
      const envelope = await callKnowledgeTool(
        python,
        message.params?.name,
        message.params?.arguments ?? {},
      );
      result = {
        content: [{ type: "text", text: JSON.stringify(envelope) }],
        structuredContent: envelope,
        isError: envelope?.outcome === "ERROR",
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
    const reason = error instanceof KnowledgeError ? error.reason : "INTERNAL_ERROR";
    writeMessage({
      jsonrpc: "2.0",
      id: message.id,
      error: { code: -32000, message: reason },
    });
  }
}

async function main() {
  const python = resolveInterpreter();
  if (!python) {
    process.stderr.write(
      "Knowledge MCP server refused to start: no Python interpreter with the PyYAML dev " +
        "dependency was found (tried KNOWLEDGE_MCP_PYTHON, the repo .venv, py -3, python3, " +
        "python). Install dev dependencies (first_launch.py / pip install -r " +
        "requirements-dev.txt) — starting without them would silently push agents back " +
        "to force-app grep.\n",
    );
    process.exit(2);
  }
  let buffer = "";
  let bytes = 0;
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    bytes += Buffer.byteLength(chunk, "utf8");
    if (bytes > MAX_OUTER_MESSAGE_BYTES) {
      process.stderr.write("Knowledge MCP server stopped: inbound message exceeded the size cap\n");
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
        process.stderr.write("Knowledge MCP server stopped: inbound line was not JSON\n");
        process.exit(2);
      }
      void handleProtocolMessage(python, message);
    }
  });
}

// Importable for the contract test without starting the stdio loop. Windows compares
// case-insensitively: drive-letter case in argv[1] depends on the invoking shell.
const entryPath = process.argv[1] ? resolve(process.argv[1]) : "";
const selfPath = fileURLToPath(import.meta.url);
const invokedDirectly =
  process.platform === "win32"
    ? entryPath.toLowerCase() === selfPath.toLowerCase()
    : entryPath === selfPath;
if (invokedDirectly) {
  main().catch((error) => {
    const reason = error instanceof KnowledgeError ? error.reason : "INTERNAL_ERROR";
    process.stderr.write(`Knowledge MCP server stopped: ${reason}\n`);
    process.exit(2);
  });
}
