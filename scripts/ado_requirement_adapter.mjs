#!/usr/bin/env node
/**
 * Internal read-only ADO requirement adapter.
 *
 * This is NOT a second model-facing ADO toolset. It is a narrow dependency of `design_open` and
 * `design_submit`, and it exists for one reason: a requirement snapshot the model transcribed
 * from a tool result is model output, and model output is never evidence. The executor fetches
 * the hierarchy itself, normalizes it, and hands the Design Case runtime a snapshot the model
 * never touched.
 *
 * It starts the admitted, lockfile-resolved `@azure-devops/mcp` entrypoint through
 * `process.execPath` with an argument array and `shell: false`. It does not — and may not —
 * introduce a second runtime `npx -y` acquisition.
 *
 * Exposed operations are reads only: work-item get and get_batch. No write dispatcher is
 * reachable from here.
 */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const ADO_ENTRYPOINT = join(REPO_ROOT, "node_modules", "@azure-devops", "mcp", "dist", "index.js");
const START_TIMEOUT_MS = 30_000;
const CALL_TIMEOUT_MS = 60_000;
const MAX_CHILDREN = 100;
const MAX_TEXT = 20_000;

// Fields the adapter reads. Anything else is ignored rather than carried into durable state.
const TITLE_FIELD = "System.Title";
const TYPE_FIELD = "System.WorkItemType";
const REVISION_FIELD = "System.Rev";
const STATE_FIELD = "System.State";
const AC_FIELD = "Microsoft.VSTS.Common.AcceptanceCriteria";
const DESCRIPTION_FIELD = "System.Description";

export class AdoAdapterError extends Error {
  constructor(reason) {
    super(reason);
    this.reason = reason;
  }
}

/** Strip HTML to text without executing or interpreting any of it. */
export function plainText(html) {
  if (typeof html !== "string" || !html) return "";
  return html
    .replace(/<\s*(br|\/p|\/div|\/li|\/tr)\s*\/?>/gi, "\n")
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/[ \t]+/g, " ")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n")
    .slice(0, MAX_TEXT);
}

function digest(text) {
  return `sha256:${createHash("sha256").update(text, "utf8").digest("hex")}`;
}

/**
 * Split one rich-text acceptance-criteria field into clause candidates.
 *
 * Ordinal position is deliberately NOT the identity: a reorder would silently rewrite every AC.
 * The adapter emits a normalized fingerprint per clause and lets the Design Case runtime
 * reconcile it against the previous snapshot, requesting human reconciliation when a split,
 * merge, reorder or rewrite is ambiguous.
 */
export function clauseCandidates(text) {
  const lines = plainText(text)
    .split("\n")
    .map((line) => line.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim())
    .filter((line) => line.length > 2);
  return lines.map((line, index) => ({
    ordinal: index + 1,
    summary: line.slice(0, 2000),
    textDigest: digest(line),
    fingerprint: digest(line.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()),
  }));
}

class AdoClient {
  constructor(organization, domains) {
    this.organization = organization;
    this.domains = domains;
    this.child = null;
    this.buffer = "";
    this.pending = new Map();
    this.nextId = 1;
  }

  async start() {
    if (!existsSync(ADO_ENTRYPOINT)) {
      throw new AdoAdapterError(
        "ADO_ENTRYPOINT_MISSING: run `npm ci --ignore-scripts` — the adapter starts the " +
          "locally installed, lockfile-resolved server and never acquires a package at runtime",
      );
    }
    this.child = spawn(
      process.execPath,
      [ADO_ENTRYPOINT, this.organization, "-d", ...this.domains],
      { cwd: REPO_ROOT, stdio: ["pipe", "pipe", "pipe"], shell: false },
    );
    this.child.stdout.setEncoding("utf8");
    this.child.stdout.on("data", (chunk) => this.consume(chunk));
    this.child.stderr.setEncoding("utf8");
    this.child.stderr.on("data", () => {});
    this.child.on("exit", () => {
      for (const [, entry] of this.pending) entry.reject(new AdoAdapterError("ADO_SERVER_EXITED"));
      this.pending.clear();
      this.child = null;
    });
    await this.request(
      "initialize",
      {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "sf-harness-requirement-adapter", version: "1.0.0" },
      },
      START_TIMEOUT_MS,
    );
    this.notify("notifications/initialized", {});
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
        continue;
      }
      const entry = this.pending.get(frame.id);
      if (!entry) continue;
      this.pending.delete(frame.id);
      clearTimeout(entry.timer);
      if (frame.error) entry.reject(new AdoAdapterError(`ADO_ERROR: ${frame.error.message}`));
      else entry.resolve(frame.result);
    }
  }

  notify(method, params) {
    this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
  }

  request(method, params, timeoutMs = CALL_TIMEOUT_MS) {
    const id = this.nextId++;
    return new Promise((resolvePromise, rejectPromise) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        rejectPromise(new AdoAdapterError(`ADO_TIMEOUT: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve: resolvePromise, reject: rejectPromise, timer });
      this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }

  async callTool(name, args) {
    const result = await this.request("tools/call", { name, arguments: args });
    if (result?.isError) throw new AdoAdapterError(`ADO_TOOL_ERROR: ${name}`);
    const text = result?.content?.find((item) => item.type === "text")?.text;
    if (result?.structuredContent) return result.structuredContent;
    if (typeof text !== "string") throw new AdoAdapterError(`ADO_EMPTY_RESULT: ${name}`);
    try {
      return JSON.parse(text);
    } catch {
      throw new AdoAdapterError(`ADO_UNPARSEABLE_RESULT: ${name}`);
    }
  }

  stop() {
    if (this.child) this.child.kill();
  }
}

function fields(item) {
  return item?.fields ?? item?.Fields ?? {};
}

function relationIds(item, wanted) {
  const relations = item?.relations ?? item?.Relations ?? [];
  const ids = [];
  for (const relation of relations) {
    const kind = relation?.rel ?? relation?.Rel ?? "";
    if (kind !== wanted) continue;
    const url = relation?.url ?? relation?.URL ?? "";
    const match = /\/(\d+)\s*$/.exec(String(url));
    if (match) ids.push(Number(match[1]));
  }
  return ids.slice(0, MAX_CHILDREN);
}

function relationChildIds(item) {
  return relationIds(item, "System.LinkTypes.Hierarchy-Forward");
}

/** Formally related Test Cases, read as CONTEXT. Never a ranking and never the plan. */
export function linkedTestCaseIds(item) {
  return relationIds(item, "Microsoft.VSTS.Common.TestedBy-Forward");
}

/**
 * Fetch one work item, its full-detail children, and its acceptance criteria.
 *
 * Feature and Epic design loads children with FULL detail: a summary-only child cannot satisfy
 * the requirement gate, so fetching titles alone would produce a snapshot that looks complete
 * and is not.
 */
export async function fetchRequirement({
  organization,
  project,
  itemId,
  includeHierarchy = true,
  includeLinkedTestCases = false,
}) {
  if (!organization) throw new AdoAdapterError("INVALID_INPUT: organization is required");
  if (!project) throw new AdoAdapterError("INVALID_INPUT: project is required");
  if (!Number.isInteger(itemId) || itemId < 1) {
    throw new AdoAdapterError("INVALID_INPUT: itemId must be a positive integer");
  }
  const client = new AdoClient(organization, ["work-items"]);
  try {
    await client.start();
    const root = await client.callTool("wit_get_work_item", {
      project,
      id: itemId,
      expand: "relations",
    });
    const rootFields = fields(root);
    const rootType = String(rootFields[TYPE_FIELD] ?? "");
    const rootRevision = Number(rootFields[REVISION_FIELD] ?? 0);

    let children = [];
    let childIds = [];
    if (includeHierarchy) {
      childIds = relationChildIds(root);
      if (childIds.length) {
        const batch = await client.callTool("wit_get_work_items_batch_by_ids", {
          project,
          ids: childIds,
        });
        const items = Array.isArray(batch) ? batch : (batch?.value ?? batch?.items ?? []);
        children = items.map((item) => {
          const itemFields = fields(item);
          return {
            id: Number(item?.id ?? item?.Id ?? 0),
            type: String(itemFields[TYPE_FIELD] ?? ""),
            state: String(itemFields[STATE_FIELD] ?? ""),
            title: plainText(itemFields[TITLE_FIELD] ?? ""),
            revision: Number(itemFields[REVISION_FIELD] ?? 0),
            description: plainText(itemFields[DESCRIPTION_FIELD] ?? ""),
            acceptanceCriteria: plainText(itemFields[AC_FIELD] ?? ""),
            // A child whose title arrived but whose body did not is summary-only. The gate
            // must see this, not a snapshot that quietly claims completeness.
            detailed: Boolean(itemFields[DESCRIPTION_FIELD] || itemFields[AC_FIELD]),
          };
        });
      }
    }

    const missingDetail = children.filter((child) => !child.detailed).map((child) => child.id);
    const rootAcText = String(rootFields[AC_FIELD] ?? "");
    const snapshot = {
      sourceType: "ado",
      organization,
      project,
      itemId,
      itemType: rootType,
      title: plainText(rootFields[TITLE_FIELD] ?? ""),
      revision: rootRevision,
      retrievedAt: null, // stamped by the Python executor; the adapter keeps no clock authority
      rootAcceptanceCriteria: clauseCandidates(rootAcText),
      rootAcDigest: digest(plainText(rootAcText)),
      children,
      includedItems: children.map((child) => child.id),
      excludedItems: [],
      childIds,
      completeness: missingDetail.length ? "partial" : "complete",
      missingDetailItemIds: missingDetail,
      linkedTestCases: [],
      sourceDigest: digest(
        JSON.stringify({
          itemId,
          revision: rootRevision,
          rootAcText: plainText(rootAcText),
          children: children.map((child) => [child.id, child.revision]),
        }),
      ),
    };
    if (includeLinkedTestCases) {
      // Context only: formally related Test Cases are never the canonical verification plan,
      // and nothing here ranks or suggests them. The Verification Contract stays the plan.
      snapshot.linkedTestCases = linkedTestCaseIds(root);
    }
    return snapshot;
  } finally {
    client.stop();
  }
}

/** Cheap re-read for the submit-time drift check: root revision plus every child revision. */
export async function fetchRevisions({ organization, project, itemId, childIds = [] }) {
  const client = new AdoClient(organization, ["work-items"]);
  try {
    await client.start();
    const root = await client.callTool("wit_get_work_item", { project, id: itemId });
    const revisions = { [itemId]: Number(fields(root)[REVISION_FIELD] ?? 0) };
    if (childIds.length) {
      const batch = await client.callTool("wit_get_work_items_batch_by_ids", {
        project,
        ids: childIds.slice(0, MAX_CHILDREN),
      });
      const items = Array.isArray(batch) ? batch : (batch?.value ?? batch?.items ?? []);
      for (const item of items) {
        revisions[Number(item?.id ?? item?.Id ?? 0)] = Number(fields(item)[REVISION_FIELD] ?? 0);
      }
    }
    return revisions;
  } finally {
    client.stop();
  }
}
