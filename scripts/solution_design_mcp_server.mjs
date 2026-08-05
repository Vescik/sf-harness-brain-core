#!/usr/bin/env node
/**
 * Solution Design MCP server — the executor of the Design Case loop.
 *
 * Node built-ins only. The wrapper owns ONE persistent `solution_design_worker.py` process and
 * serializes every case mutation through a per-case queue, so there is exactly one mutating
 * surface in a checkout and no Python process per operation.
 *
 * Three things this wrapper deliberately does not do:
 *
 *  1. It never computes a `caseVersion` or a `candidateDigest`. The Python core is the single
 *     digest authority; reimplementing canonicalization here would create a second definition
 *     that silently disagrees on Unicode or integer edges.
 *  2. It never lets the model author a human decision. `design_request_*` tools carry no answer,
 *     approval or status field. The wrapper asks VS Code through MCP elicitation, validates the
 *     closed response schema, and only then calls the internal worker operation with a
 *     single-use nonce. Cancel, dismissal, timeout, replay or a changed version mutates nothing.
 *  3. It never falls back. If the client did not advertise elicitation support, the human-bound
 *     tools return UNSUPPORTED_HOST_CAPABILITY — never chat, never a terminal, never a parameter.
 */

import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SERVER_VERSION = "1.0.0";
const PROTOCOL_VERSION = "2025-06-18";
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PROBE_TIMEOUT_MS = 10_000;
const CALL_TIMEOUT_MS = 120_000;
const ELICITATION_TIMEOUT_MS = 600_000;
const MAX_OUTER_MESSAGE_BYTES = 6_000_000;
const MAX_STDERR_BYTES = 64_000;
const NONCE_TTL_MS = 600_000;

class ServerError extends Error {
  constructor(reason) {
    super(reason);
    this.reason = reason;
  }
}

// ---------------------------------------------------------------------------------------
// Tool surface
// ---------------------------------------------------------------------------------------

const CASE_ID = {
  type: "string",
  description: "ADO-<project-slug>-<item-id> or SD-<yyyy-mm-dd>-<slug>",
};
const CASE_VERSION = {
  type: "string",
  description: "Opaque token from the last read. Never construct or edit it.",
};

export const TOOL_DEFINITIONS = [
  {
    name: "design_open",
    description:
      "Create or resume the canonical Design Case. Empty component scope is allowed. Without " +
      "expectedCaseVersion an existing case resumes read-only; supplying the current token " +
      "authorizes an atomic refresh.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["caseId", "writerId"],
      properties: {
        caseId: CASE_ID,
        writerId: { type: "string", description: "Configured user id acting as the case writer" },
        title: { type: "string" },
        orRequirement: {
          type: "string",
          description:
            "Explicit requirement text. Stored as UNVERIFIED intake; it seeds a " +
            "requirement-attestation obligation and is never treated as human authority.",
        },
        expectedCaseVersion: CASE_VERSION,
      },
    },
  },
  {
    name: "design_context",
    description: "Read the current case: version, writer, status, obligations by route, no raw external values.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["caseId"],
      properties: {
        caseId: CASE_ID,
        view: { enum: ["summary", "grounding", "decisions", "verification", "all"] },
      },
    },
  },
  {
    name: "design_check",
    description:
      "Run every computed gate against one snapshot. Strictly read-only: it writes no receipt, " +
      "pointer or status and never closes an obligation. Returns READY, OPEN or MALFORMED.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["caseId"],
      properties: { caseId: CASE_ID },
    },
  },
  {
    name: "design_apply",
    description:
      "Apply an atomic list of typed operations. Closure authority is enforced: a blocking " +
      "evidence question cannot be closed by prose, and receipt-bearing operations require an " +
      "executor-authored payload this tool cannot supply.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["caseId", "writerId", "expectedCaseVersion", "operations"],
      properties: {
        caseId: CASE_ID,
        writerId: { type: "string" },
        expectedCaseVersion: CASE_VERSION,
        operations: {
          type: "array",
          minItems: 1,
          maxItems: 200,
          items: {
            type: "object",
            required: ["kind", "payload"],
            properties: { kind: { type: "string" }, payload: { type: "object" } },
          },
        },
      },
    },
  },
  {
    name: "design_import_repository_receipt",
    description:
      "Bind an exact tracked Git blob as source evidence. The executor reads the object by OID " +
      "at a full commit SHA; a model file read is never evidence.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["caseId", "writerId", "expectedCaseVersion", "commit", "path"],
      properties: {
        caseId: CASE_ID,
        writerId: { type: "string" },
        expectedCaseVersion: CASE_VERSION,
        commit: { type: "string", description: "Full 40-character commit SHA" },
        path: { type: "string", description: "Repository-relative path" },
        firstLine: { type: "integer", minimum: 1 },
        lastLine: { type: "integer", minimum: 1 },
        questionId: { type: "string" },
        probeId: { type: "string" },
      },
    },
  },
  {
    name: "design_submit",
    description:
      "The only design completeness gate. OPEN leaves the draft editable and returns routed " +
      "gaps; READY creates the immutable candidate and selects the next transition.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["caseId", "writerId", "expectedCaseVersion"],
      properties: { caseId: CASE_ID, writerId: { type: "string" }, expectedCaseVersion: CASE_VERSION },
    },
  },
  {
    name: "design_request_human_input",
    description:
      "Ask the named human, through VS Code, for a material answer or risk acceptance. This " +
      "tool carries NO answer field: the elicitation response is the authority, and the answer " +
      "becomes pre-candidate evidence that recomputes the gates.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["caseId", "expectedCaseVersion", "obligationId", "question"],
      properties: {
        caseId: CASE_ID,
        expectedCaseVersion: CASE_VERSION,
        obligationId: { type: "string", description: "The open obligation this answers" },
        question: { type: "string", description: "What the human is being asked" },
        authorityRole: {
          enum: [
            "requirement-owner",
            "subject-matter-expert",
            "package-vendor",
            "production-owner",
            "risk-owner",
          ],
        },
        target: {
          type: "object",
          required: ["kind", "id"],
          properties: {
            kind: { enum: ["question", "risk", "requirement", "rule"] },
            id: { type: "string" },
          },
        },
      },
    },
  },
  {
    name: "design_request_candidate_decision",
    description:
      "Show the named human the immutable candidate and its exact digest in VS Code and ask for " +
      "Approve, Request revision or Cancel. The model cannot pass the decision.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["caseId", "candidateId", "candidateDigest"],
      properties: {
        caseId: CASE_ID,
        candidateId: { type: "string" },
        candidateDigest: { type: "string" },
      },
    },
  },
  {
    name: "design_request_writer_transfer",
    description:
      "Ask the current owner, through VS Code, to hand this case to another named writer.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["caseId", "expectedCaseVersion", "targetWriterId"],
      properties: {
        caseId: CASE_ID,
        expectedCaseVersion: CASE_VERSION,
        targetWriterId: { type: "string" },
      },
    },
  },
  {
    name: "design_start_development",
    description:
      "Move an accepted candidate into Development and emit the handoff automatically. No hash " +
      "or handoff id is ever copied by an agent.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["caseId"],
      properties: { caseId: CASE_ID },
    },
  },
];

// The model-facing tool name maps to an internal worker operation. Human-bound tools map to a
// worker operation only AFTER a valid elicitation response; that is why they are listed
// separately and never reachable through the direct table.
const DIRECT_OPERATIONS = {
  design_open: "open",
  design_context: "context",
  design_check: "check",
  design_apply: "apply",
  design_import_repository_receipt: "import-repository-receipt",
  design_submit: "submit",
  design_start_development: "start-development",
};

const HUMAN_BOUND_TOOLS = new Set([
  "design_request_human_input",
  "design_request_candidate_decision",
  "design_request_writer_transfer",
]);

// ---------------------------------------------------------------------------------------
// Worker process
// ---------------------------------------------------------------------------------------

function interpreterCandidates() {
  const candidates = [];
  if (process.env.SOLUTION_DESIGN_MCP_PYTHON) candidates.push([process.env.SOLUTION_DESIGN_MCP_PYTHON]);
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
    const probe = spawnSync(candidate[0], [...candidate.slice(1), "-c", "import jsonschema"], {
      timeout: PROBE_TIMEOUT_MS,
      stdio: "ignore",
      shell: false,
    });
    if (!probe.error && probe.status === 0) return candidate;
  }
  return null;
}

class WorkerBridge {
  constructor(python) {
    this.python = python;
    this.child = null;
    this.buffer = "";
    this.pending = new Map();
    this.nextId = 1;
    this.stderrBytes = 0;
  }

  start() {
    this.child = spawn(
      this.python[0],
      [...this.python.slice(1), join(REPO_ROOT, "scripts", "solution_design_worker.py")],
      { cwd: REPO_ROOT, stdio: ["pipe", "pipe", "pipe"], shell: false, env: { ...process.env } },
    );
    this.child.stdout.setEncoding("utf8");
    this.child.stdout.on("data", (chunk) => this.consume(chunk));
    this.child.stderr.setEncoding("utf8");
    this.child.stderr.on("data", (chunk) => {
      this.stderrBytes += Buffer.byteLength(chunk, "utf8");
      if (this.stderrBytes <= MAX_STDERR_BYTES) process.stderr.write(`worker: ${chunk}`);
    });
    this.child.on("exit", (code) => {
      const failure = new ServerError(`WORKER_EXITED (${code})`);
      for (const [, entry] of this.pending) entry.reject(failure);
      this.pending.clear();
      this.child = null;
    });
  }

  consume(chunk) {
    this.buffer += chunk;
    while (this.buffer.includes("\n")) {
      const index = this.buffer.indexOf("\n");
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (!line) continue;
      let frame;
      try {
        frame = JSON.parse(line);
      } catch {
        process.stderr.write("worker: emitted a non-JSON line; ignoring\n");
        continue;
      }
      const entry = this.pending.get(frame.id);
      if (!entry) continue;
      this.pending.delete(frame.id);
      clearTimeout(entry.timer);
      entry.resolve(frame);
    }
  }

  call(operation, params) {
    if (!this.child) this.start();
    const id = this.nextId++;
    const frame = JSON.stringify({ id, op: operation, params });
    return new Promise((resolvePromise, rejectPromise) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        rejectPromise(new ServerError(`WORKER_TIMEOUT: ${operation}`));
      }, CALL_TIMEOUT_MS);
      this.pending.set(id, { resolve: resolvePromise, reject: rejectPromise, timer });
      this.child.stdin.write(`${frame}\n`);
    });
  }
}

/** A bounded per-case queue: one mutation at a time, in call order. */
class CaseQueue {
  constructor() {
    this.tails = new Map();
  }

  run(caseId, task) {
    const previous = this.tails.get(caseId) ?? Promise.resolve();
    const next = previous.then(task, task);
    this.tails.set(
      caseId,
      next.then(
        () => undefined,
        () => undefined,
      ),
    );
    return next;
  }
}

// ---------------------------------------------------------------------------------------
// Elicitation
// ---------------------------------------------------------------------------------------

const nonces = new Map();

function issueNonce(operation, binding) {
  const nonce = randomUUID();
  nonces.set(nonce, { operation, binding, expiresAt: Date.now() + NONCE_TTL_MS });
  return nonce;
}

function consumeNonce(nonce, operation, binding) {
  const entry = nonces.get(nonce);
  if (!entry) throw new ServerError("ELICITATION_NONCE_INVALID");
  nonces.delete(nonce);
  if (entry.expiresAt < Date.now()) throw new ServerError("ELICITATION_EXPIRED");
  if (entry.operation !== operation) throw new ServerError("ELICITATION_WRONG_OPERATION");
  if (JSON.stringify(entry.binding) !== JSON.stringify(binding)) {
    throw new ServerError("ELICITATION_BINDING_CHANGED");
  }
  return createHash("sha256").update(nonce, "utf8").digest("hex");
}

const outbound = new Map();
let outboundId = 1;

function writeMessage(message) {
  const serialized = JSON.stringify(message);
  if (Buffer.byteLength(serialized, "utf8") > MAX_OUTER_MESSAGE_BYTES) {
    throw new ServerError("RESULT_TOO_LARGE_FOR_ONE_MESSAGE");
  }
  process.stdout.write(`${serialized}\n`);
}

function elicit(message, requestedSchema) {
  const id = `sd-elicit-${outboundId++}`;
  return new Promise((resolvePromise) => {
    const timer = setTimeout(() => {
      outbound.delete(id);
      resolvePromise({ action: "cancel" });
    }, ELICITATION_TIMEOUT_MS);
    outbound.set(id, (response) => {
      clearTimeout(timer);
      resolvePromise(response);
    });
    writeMessage({
      jsonrpc: "2.0",
      id,
      method: "elicitation/create",
      params: { message, requestedSchema },
    });
  });
}

let clientSupportsElicitation = false;

function requireElicitationSupport() {
  if (!clientSupportsElicitation) {
    throw new ServerError(
      "UNSUPPORTED_HOST_CAPABILITY: this MCP client did not advertise elicitation support. " +
        "A human decision is never taken from chat, a terminal or a model parameter.",
    );
  }
}

/** The closed response contract. Anything else is treated as no decision at all. */
function readElicitationResult(response, allowedActions) {
  if (!response || response.action !== "accept" || typeof response.content !== "object") {
    return null;
  }
  const content = response.content ?? {};
  const identity = typeof content.identity === "string" ? content.identity.trim() : "";
  if (!identity) return null;
  if (allowedActions && !allowedActions.includes(content.decision)) return null;
  return content;
}

// ---------------------------------------------------------------------------------------
// Tool dispatch
// ---------------------------------------------------------------------------------------

function unwrap(frame) {
  if (frame.ok) return frame.result;
  throw new ServerError(`${frame.error?.code ?? "REJECTED"}: ${frame.error?.message ?? ""}`);
}

async function callHumanInput(bridge, input) {
  requireElicitationSupport();
  const binding = { caseId: input.caseId, expectedCaseVersion: input.expectedCaseVersion };
  const nonce = issueNonce("record-human-input", binding);
  const response = await elicit(
    `Solution Design — ${input.caseId}\n\n${input.question}\n\n` +
      `This answer becomes pre-candidate evidence: it recomputes the design gates and is ` +
      `hashed into any later candidate. It is not a design approval.`,
    {
      type: "object",
      required: ["identity", "answer"],
      properties: {
        identity: { type: "string", title: "Your name" },
        answer: { type: "string", title: "Answer" },
        limitation: { type: "string", title: "Known limitation of this answer" },
      },
    },
  );
  const content = readElicitationResult(response);
  if (!content) return { outcome: "NO_DECISION", detail: "no elicitation response; nothing changed" };
  const nonceDigest = `sha256:${consumeNonce(nonce, "record-human-input", binding)}`;
  return unwrap(
    await bridge.call("record-human-input", {
      caseId: input.caseId,
      expectedCaseVersion: input.expectedCaseVersion,
      answer: content.answer,
      authorityRole: input.authorityRole ?? "subject-matter-expert",
      target: input.target ?? {},
      limitations: content.limitation ? [content.limitation] : [],
      elicitation: { identity: content.identity, nonceDigest },
    }),
  );
}

async function callCandidateDecision(bridge, input) {
  requireElicitationSupport();
  const binding = {
    caseId: input.caseId,
    candidateId: input.candidateId,
    candidateDigest: input.candidateDigest,
  };
  const nonce = issueNonce("candidate-decision", binding);
  const response = await elicit(
    `Solution Design candidate — ${input.caseId}\n\n` +
      `Candidate: ${input.candidateId}\nDigest: ${input.candidateDigest}\n\n` +
      `Review the immutable candidate design before deciding. Approving binds this exact ` +
      `digest; a later change supersedes it. You cannot add a new fact here — a missing answer ` +
      `must go back into the draft as evidence first.`,
    {
      type: "object",
      required: ["identity", "decision"],
      properties: {
        identity: { type: "string", title: "Your name" },
        decision: { enum: ["Approve", "Request revision", "Cancel"], title: "Decision" },
        reason: { type: "string", title: "Reason (required for a revision request)" },
      },
    },
  );
  const content = readElicitationResult(response, ["Approve", "Request revision", "Cancel"]);
  if (!content || content.decision === "Cancel") {
    return { outcome: "NO_DECISION", detail: "no approval and no revision; nothing changed" };
  }
  const nonceDigest = `sha256:${consumeNonce(nonce, "candidate-decision", binding)}`;
  const operation =
    content.decision === "Approve" ? "confirm-candidate" : "request-candidate-revision";
  return unwrap(
    await bridge.call(operation, {
      caseId: input.caseId,
      candidateId: input.candidateId,
      candidateDigest: input.candidateDigest,
      reason: content.reason,
      elicitation: { identity: content.identity, nonceDigest },
    }),
  );
}

async function callWriterTransfer(bridge, input) {
  requireElicitationSupport();
  const binding = {
    caseId: input.caseId,
    expectedCaseVersion: input.expectedCaseVersion,
    targetWriterId: input.targetWriterId,
  };
  const nonce = issueNonce("transfer-case-writer", binding);
  const response = await elicit(
    `Transfer Design Case ${input.caseId} to ${input.targetWriterId}?\n\n` +
      `Only the current owner may transfer. Your current case token becomes invalid immediately.`,
    {
      type: "object",
      required: ["identity", "decision"],
      properties: {
        identity: { type: "string", title: "Your name (must be the current owner)" },
        decision: { enum: ["Transfer", "Cancel"], title: "Decision" },
        reason: { type: "string", title: "Reason" },
      },
    },
  );
  const content = readElicitationResult(response, ["Transfer", "Cancel"]);
  if (!content || content.decision === "Cancel") {
    return { outcome: "NO_DECISION", detail: "ownership unchanged" };
  }
  const nonceDigest = `sha256:${consumeNonce(nonce, "transfer-case-writer", binding)}`;
  return unwrap(
    await bridge.call("transfer-case-writer", {
      caseId: input.caseId,
      expectedCaseVersion: input.expectedCaseVersion,
      targetWriterId: input.targetWriterId,
      reason: content.reason,
      elicitation: { identity: content.identity, nonceDigest },
    }),
  );
}

export async function callDesignTool(bridge, queue, name, input) {
  const definition = TOOL_DEFINITIONS.find((tool) => tool.name === name);
  if (!definition) throw new ServerError(`UNKNOWN_TOOL: ${name}`);
  const caseId = input?.caseId;
  if (typeof caseId !== "string" || !caseId) throw new ServerError("INVALID_INPUT: caseId is required");
  for (const key of Object.keys(input ?? {})) {
    if (!Object.prototype.hasOwnProperty.call(definition.inputSchema.properties, key)) {
      throw new ServerError(`INVALID_INPUT: unknown argument '${key}' for ${name}`);
    }
  }
  for (const key of definition.inputSchema.required ?? []) {
    if (input?.[key] === undefined) throw new ServerError(`INVALID_INPUT: ${name} requires ${key}`);
  }

  return queue.run(caseId, async () => {
    if (name === "design_request_human_input") return callHumanInput(bridge, input);
    if (name === "design_request_candidate_decision") return callCandidateDecision(bridge, input);
    if (name === "design_request_writer_transfer") return callWriterTransfer(bridge, input);
    if (HUMAN_BOUND_TOOLS.has(name)) throw new ServerError(`UNROUTED_HUMAN_TOOL: ${name}`);
    const operation = DIRECT_OPERATIONS[name];
    return unwrap(await bridge.call(operation, input));
  });
}

// ---------------------------------------------------------------------------------------
// Protocol
// ---------------------------------------------------------------------------------------

const STEERING =
  "The Design Case runtime owns workflow state; design.md owns the human narrative. " +
  "Never type a workflow script, never copy a digest, never claim a phase. Run design_check " +
  "and act on its routed gaps. An OPEN draft is still editable.";

async function handleProtocolMessage(bridge, queue, message) {
  if (!message || message.jsonrpc !== "2.0") return;

  // A response to one of OUR outbound elicitation requests.
  if (message.method === undefined && outbound.has(message.id)) {
    const resolver = outbound.get(message.id);
    outbound.delete(message.id);
    resolver(message.error ? { action: "cancel" } : message.result);
    return;
  }
  if (typeof message.method !== "string" || message.id === undefined) return;

  try {
    let result;
    if (message.method === "initialize") {
      clientSupportsElicitation = Boolean(message.params?.capabilities?.elicitation);
      result = {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "sf-harness-solution-design", version: SERVER_VERSION },
        instructions: STEERING,
      };
    } else if (message.method === "ping") {
      result = {};
    } else if (message.method === "tools/list") {
      result = { tools: TOOL_DEFINITIONS };
    } else if (message.method === "tools/call") {
      const payload = await callDesignTool(
        bridge,
        queue,
        message.params?.name,
        message.params?.arguments ?? {},
      );
      result = {
        content: [{ type: "text", text: JSON.stringify(payload) }],
        structuredContent: payload,
        isError: false,
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
    writeMessage({
      jsonrpc: "2.0",
      id: message.id,
      error: { code: -32000, message: error instanceof ServerError ? error.reason : "INTERNAL_ERROR" },
    });
  }
}

async function main() {
  const python = resolveInterpreter();
  if (!python) {
    process.stderr.write(
      "Solution Design MCP server refused to start: no Python interpreter with jsonschema was " +
        "found (tried SOLUTION_DESIGN_MCP_PYTHON, the repo .venv, py -3, python3, python). " +
        "Install dev dependencies with first_launch.py — starting without them would leave the " +
        "Design Case runtime unable to validate its own state.\n",
    );
    process.exit(2);
  }
  const bridge = new WorkerBridge(python);
  bridge.start();
  const queue = new CaseQueue();
  let buffer = "";
  let bytes = 0;
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    bytes += Buffer.byteLength(chunk, "utf8");
    if (bytes > MAX_OUTER_MESSAGE_BYTES) {
      process.stderr.write("Solution Design MCP server stopped: inbound message exceeded the cap\n");
      process.exit(2);
    }
    buffer += chunk;
    while (buffer.includes("\n")) {
      const index = buffer.indexOf("\n");
      const line = buffer.slice(0, index).trim();
      buffer = buffer.slice(index + 1);
      bytes = Buffer.byteLength(buffer, "utf8");
      if (!line) continue;
      let parsed;
      try {
        parsed = JSON.parse(line);
      } catch {
        process.stderr.write("Solution Design MCP server stopped: inbound line was not JSON\n");
        process.exit(2);
      }
      void handleProtocolMessage(bridge, queue, parsed);
    }
  });
}

const entryPath = process.argv[1] ? resolve(process.argv[1]) : "";
const selfPath = fileURLToPath(import.meta.url);
const invokedDirectly =
  process.platform === "win32"
    ? entryPath.toLowerCase() === selfPath.toLowerCase()
    : entryPath === selfPath;
if (invokedDirectly) {
  main().catch((error) => {
    process.stderr.write(
      `Solution Design MCP server stopped: ${error instanceof ServerError ? error.reason : "INTERNAL_ERROR"}\n`,
    );
    process.exit(2);
  });
}
