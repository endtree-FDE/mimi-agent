#!/usr/bin/env node

import fs from "node:fs";
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";

const WORKER_PREFIX = "JUCHANG_AGENT_STUDIO_WORKER_RUN: ";
const ACCEPTED_PREFIX = "JUCHANG_AGENT_STUDIO_RECEIPT_ACCEPTED: ";
const WORKER_SCHEMA = "yixun-agent-studio-worker-run@1";
const ACCEPTED_SCHEMA = "yixun-agent-studio-receipt-accepted@2";
const PROJECTION_SCHEMA = "yixun-agent-studio-receipt-projection@1";
const RESULT_SCHEMA = "matrix-receipt-verification@1";
const MAX_ACCEPTED_LINE_CHARS = 56 * 1024;
const MAX_PROJECTION_BYTES = 48 * 1024;
const MAX_EVENTS = 10_000;
const MAX_SERVER_TIME_DRIFT_MS = 60_000;
const MAX_ACCEPTANCE_DELAY_MS = 5 * 60_000;
const ROLES = ["material_intake", "evidence_guard", "entity_matcher", "approval_guard"];
const ROLE_SET = new Set(ROLES);
const IMPACT_AREAS = ["event", "ticketing", "customer_service", "notification", "knowledge_base"];
const IMPACT_AREA_SET = new Set(IMPACT_AREAS);
const ORCHESTRATION_SKILLS = new Set(["juchang-dsh-executor", "juchang-task-submit", "juchang-lifecycle-control"]);
const FORBIDDEN_TEXT = /(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|authorization\s*:|bearer\s+|password\s*[=:]|https?:\/\/|思维链|推理过程|系统提示词|开发者提示词|chain[ -]?of[ -]?thought|system prompt|developer prompt|tool arguments?|[A-Za-z]:[\\/]|\/(?:workspace|tmp|var|home|etc)\/)/iu;
const INTERNAL_TEXT_MARKERS = ["\"taskState\":", "\"approvalState\":", "\"sourceUrl\":", "\"sourceTitle\":"];

export class ReceiptVerificationError extends Error {
  constructor(code) {
    super(code);
    this.name = "ReceiptVerificationError";
    this.code = code;
  }
}

function fail(code) {
  throw new ReceiptVerificationError(code);
}

function exactRecord(value, keys, code) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(code);
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) fail(code);
  return value;
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value)
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
    .map(([key, item]) => [key, canonicalValue(item)]));
}

export function canonicalReceiptProjection(value) {
  return JSON.stringify(canonicalValue(value));
}

export function receiptProjectionDigest(value) {
  return createHash("sha256").update(canonicalReceiptProjection(value)).digest("hex");
}

function validId(value, min = 3, max = 128) {
  return typeof value === "string"
    && value.length >= min
    && value.length <= max
    && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value);
}

function validUuid(value) {
  return typeof value === "string" && /^[0-9a-f-]{36}$/i.test(value);
}

function validSha(value) {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

function validMatrixSender(value) {
  return typeof value === "string" && /^@[^:\s]+:[^\s]+$/.test(value);
}

function matrixLocalpart(value) {
  const match = /^@([^:\s]+):[^\s]+$/.exec(value);
  return match?.[1] || "";
}

function validSessionId(value) {
  return typeof value === "string" && /^studio-[A-Za-z0-9][A-Za-z0-9-]{15,79}$/.test(value);
}

function validAt(value) {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function strictText(value, limit, allowEmpty = false) {
  if (typeof value !== "string" || value.length > limit || (!allowEmpty && !value.trim())) return false;
  const normalized = value.replace(/\s+/gu, " ").trim();
  if (normalized !== value || FORBIDDEN_TEXT.test(value) || INTERNAL_TEXT_MARKERS.some((marker) => value.includes(marker))) return false;
  return allowEmpty || Boolean(value);
}

function validField(value) {
  return typeof value === "string" && /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}$/.test(value);
}

function parseEvidenceRefs(value) {
  if (!Array.isArray(value) || value.length > 6) fail("projection_evidence_refs_invalid");
  const safe = value.filter((item) => (
    typeof item === "string"
    && /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}(?::\d{1,7}|\[[A-Za-z0-9_.:'"\[\]-]{1,80}\])?$/.test(item)
  ));
  if (safe.length !== value.length || new Set(value).size !== value.length) fail("projection_evidence_refs_invalid");
  return value;
}

function parseFacts(value) {
  if (!Array.isArray(value) || value.length > 12) fail("projection_facts_invalid");
  return value.map((item) => {
    const row = exactRecord(item, ["field", "value", "evidenceRefs"], "projection_facts_invalid");
    if (!validField(row.field) || !strictText(row.value, 320)) fail("projection_facts_invalid");
    parseEvidenceRefs(row.evidenceRefs);
    return row;
  });
}

function parseConflicts(value) {
  if (!Array.isArray(value) || value.length > 6) fail("projection_conflicts_invalid");
  return value.map((item) => {
    const row = exactRecord(item, ["field", "description", "severity", "evidenceRefs"], "projection_conflicts_invalid");
    if (!validField(row.field) || !strictText(row.description, 480)
      || !["low", "medium", "high", "critical", "unspecified"].includes(row.severity)) {
      fail("projection_conflicts_invalid");
    }
    parseEvidenceRefs(row.evidenceRefs);
    return row;
  });
}

function parseImpacts(value) {
  if (!Array.isArray(value) || value.length > 8) fail("projection_impacts_invalid");
  return value.map((item) => {
    const row = exactRecord(item, ["area", "description", "evidenceRefs"], "projection_impacts_invalid");
    if (!IMPACT_AREA_SET.has(row.area) || !strictText(row.description, 360)) fail("projection_impacts_invalid");
    parseEvidenceRefs(row.evidenceRefs);
    return row;
  });
}

function parseUnknownFields(value) {
  if (!Array.isArray(value) || value.length > 12 || value.some((field) => !validField(field))
    || new Set(value).size !== value.length) fail("projection_unknown_fields_invalid");
  return value;
}

function parseSafetyCounters(value) {
  const row = exactRecord(value, ["productionWrites", "publicPublishes", "realRefunds", "externalMessages"], "projection_safety_counters_invalid");
  if (Object.values(row).some((item) => !Number.isInteger(item) || item < 0 || item > 1_000_000)) {
    fail("projection_safety_counters_invalid");
  }
  return row;
}

function parseDomainSkillReceipt(value) {
  if (value === null) return null;
  const row = exactRecord(value, ["skillId", "status"], "projection_domain_skill_receipt_invalid");
  if (typeof row.skillId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{1,119}$/.test(row.skillId)
    || FORBIDDEN_TEXT.test(row.skillId)
    || ORCHESTRATION_SKILLS.has(row.skillId)
    || !["succeeded", "blocked", "failed", "not_called"].includes(row.status)) {
    fail("projection_domain_skill_receipt_invalid");
  }
  return row;
}

export function parseReceiptProjection(value) {
  const row = exactRecord(value, [
    "schema", "conclusion", "analysisSummary", "facts", "conflicts", "impacts", "unknownFields", "nextAction",
    "safetyCounters", "domainSkillReceipt", "runtimeSkillTraceValidated",
  ], "projection_schema_or_fields_invalid");
  if (row.schema !== PROJECTION_SCHEMA) fail("projection_schema_or_fields_invalid");
  if (!["HUMAN_REVIEW", "APPROVED", "BLOCKED", "REJECTED"].includes(row.conclusion)) fail("projection_conclusion_invalid");
  if (!strictText(row.analysisSummary, 800) || !strictText(row.nextAction, 480, true)) fail("projection_text_unsafe");
  parseFacts(row.facts);
  parseConflicts(row.conflicts);
  parseImpacts(row.impacts);
  parseUnknownFields(row.unknownFields);
  parseSafetyCounters(row.safetyCounters);
  parseDomainSkillReceipt(row.domainSkillReceipt);
  if (typeof row.runtimeSkillTraceValidated !== "boolean") fail("projection_runtime_trace_state_invalid");
  if (Buffer.byteLength(canonicalReceiptProjection(row), "utf8") > MAX_PROJECTION_BYTES) fail("projection_too_large");
  return row;
}

function markerLine(body, prefix, maxChars = Infinity) {
  if (typeof body !== "string") return null;
  const line = body.split(/\r?\n/).find((candidate) => candidate.startsWith(prefix));
  if (!line) return null;
  if (line.length > maxChars) fail("marker_too_large");
  return line;
}

function parseJsonMarker(body, prefix, code, maxChars = Infinity) {
  const line = markerLine(body, prefix, maxChars);
  if (!line) return null;
  try {
    return JSON.parse(line.slice(prefix.length));
  } catch {
    fail(code);
  }
}

export function parseCompletedWorkerMarker(body) {
  const value = parseJsonMarker(body, WORKER_PREFIX, "worker_marker_json_invalid");
  if (!value) return null;
  const row = exactRecord(value, [
    "schema", "projectId", "taskId", "sessionId", "threadId", "commandId", "runId", "workerId", "role",
    "workerTaskId", "status", "tool", "receiptDigest", "at",
  ], "worker_marker_fields_invalid");
  if (row.schema !== WORKER_SCHEMA || row.status !== "completed" || !validId(row.projectId) || !validId(row.taskId)
    || !validSessionId(row.sessionId) || !validId(row.threadId) || !validUuid(row.commandId) || !validUuid(row.runId)
    || !validId(row.workerId, 2, 80) || !ROLE_SET.has(row.role) || !validId(row.workerTaskId)
    || (row.tool !== "" && (typeof row.tool !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/.test(row.tool)))
    || !validSha(row.receiptDigest) || !validAt(row.at)) fail("worker_marker_invalid");
  return row;
}

export function parseAcceptedV2Marker(body) {
  const value = parseJsonMarker(body, ACCEPTED_PREFIX, "accepted_marker_json_invalid", MAX_ACCEPTED_LINE_CHARS);
  if (!value) return null;
  const row = exactRecord(value, [
    "schema", "projectId", "taskId", "sessionId", "threadId", "commandId", "runId", "role", "workerId",
    "workerTaskId", "receiptDigest", "at", "projectionDigest", "projection",
  ], "accepted_marker_fields_invalid");
  if (row.schema !== ACCEPTED_SCHEMA || !validId(row.projectId) || !validId(row.taskId) || !validSessionId(row.sessionId)
    || !validId(row.threadId) || !validUuid(row.commandId) || !validUuid(row.runId) || !ROLE_SET.has(row.role)
    || !validId(row.workerId, 2, 80) || !validId(row.workerTaskId) || !validSha(row.receiptDigest)
    || !validSha(row.projectionDigest) || !validAt(row.at)) fail("accepted_marker_invalid");
  const projection = parseReceiptProjection(row.projection);
  if (receiptProjectionDigest(projection) !== row.projectionDigest) fail("accepted_projection_digest_mismatch");
  return { ...row, projection };
}

function normalizeEvent(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail("matrix_event_invalid");
  const sender = value.sender;
  const body = typeof value.body === "string" ? value.body : value.content?.body;
  const timestamp = value.origin_server_ts ?? value.timestamp;
  if (!validMatrixSender(sender) || typeof body !== "string" || !Number.isFinite(timestamp)) fail("matrix_event_invalid");
  return { sender, body, timestamp };
}

function parseExpected(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail("expected_scope_invalid");
  const allowed = new Set([
    "projectId", "taskId", "sessionId", "threadId", "commandId", "runId", "leaderSender",
    "roles", "workerSenders", "projectionProfile",
  ]);
  if (Object.keys(value).some((key) => !allowed.has(key))) fail("expected_scope_invalid");
  const roles = value.roles === undefined ? [...ROLES] : value.roles;
  if (!validId(value.projectId) || !validId(value.taskId) || !validSessionId(value.sessionId) || !validId(value.threadId)
    || !validUuid(value.commandId) || !validUuid(value.runId) || !validMatrixSender(value.leaderSender)
    || !Array.isArray(roles) || roles.length === 0 || roles.some((role) => !ROLE_SET.has(role))
    || new Set(roles).size !== roles.length || !value.workerSenders || typeof value.workerSenders !== "object"
    || Array.isArray(value.workerSenders)) fail("expected_scope_invalid");
  if (JSON.stringify(Object.keys(value.workerSenders).sort()) !== JSON.stringify([...roles].sort())
    || roles.some((role) => !validMatrixSender(value.workerSenders[role]))) fail("expected_worker_senders_invalid");
  const projectionProfile = value.projectionProfile || "app-compatible";
  if (!["app-compatible", "runtime-zero-write"].includes(projectionProfile)) fail("projection_profile_invalid");
  return { ...value, roles, projectionProfile };
}

function scopeMatches(value, expected) {
  return value.projectId === expected.projectId
    && value.taskId === expected.taskId
    && value.sessionId === expected.sessionId
    && value.threadId === expected.threadId
    && value.commandId === expected.commandId
    && value.runId === expected.runId;
}

function timestampMatches(payloadAt, serverTimestamp) {
  return Math.abs(Date.parse(payloadAt) - serverTimestamp) <= MAX_SERVER_TIME_DRIFT_MS;
}

function assertRuntimeZeroWriteProjection(projection) {
  if (JSON.stringify(projection.impacts.map((impact) => impact.area)) !== JSON.stringify(IMPACT_AREAS)
    || Object.values(projection.safetyCounters).some((value) => value !== 0)) fail("zero_write_policy_failed");
}

function validateChain(acceptedEvent, workerEvents, expected) {
  const accepted = acceptedEvent.marker;
  if (acceptedEvent.sender !== expected.leaderSender) fail("leader_sender_mismatch");
  if (!timestampMatches(accepted.at, acceptedEvent.timestamp)) fail("matrix_timestamp_mismatch");
  const expectedWorkerSender = expected.workerSenders[accepted.role];
  const correlatedWorkers = workerEvents.filter((candidate) => (
    candidate.marker.role === accepted.role
    && candidate.marker.workerTaskId === accepted.workerTaskId
  ));
  const worker = correlatedWorkers.find((candidate) => candidate.marker.receiptDigest === accepted.receiptDigest)
    || correlatedWorkers[0];
  if (!worker) fail("completed_worker_marker_missing");
  if (worker.sender !== expectedWorkerSender) fail("worker_sender_mismatch");
  if (!timestampMatches(worker.marker.at, worker.timestamp)) fail("matrix_timestamp_mismatch");
  const serverDelay = acceptedEvent.timestamp - worker.timestamp;
  const payloadDelay = Date.parse(accepted.at) - Date.parse(worker.marker.at);
  if (serverDelay < 0 || payloadDelay < 0 || serverDelay > MAX_ACCEPTANCE_DELAY_MS || payloadDelay > MAX_ACCEPTANCE_DELAY_MS) {
    fail("receipt_causal_order_invalid");
  }
  if (matrixLocalpart(expectedWorkerSender) !== accepted.workerId || accepted.workerId !== worker.marker.workerId) {
    fail("worker_identity_mismatch");
  }
  for (const key of ["projectId", "taskId", "sessionId", "threadId", "commandId", "runId", "role", "workerId", "workerTaskId"]) {
    if (accepted[key] !== worker.marker[key]) fail("receipt_chain_correlation_mismatch");
  }
  if (accepted.receiptDigest !== worker.marker.receiptDigest) fail("receipt_digest_binding_mismatch");
  if (expected.projectionProfile === "runtime-zero-write") assertRuntimeZeroWriteProjection(accepted.projection);
  return accepted;
}

export function verifyReceiptExport(input) {
  const envelope = exactRecord(input, ["expected", "events"], "input_envelope_invalid");
  const expected = parseExpected(envelope.expected);
  if (!Array.isArray(envelope.events) || envelope.events.length === 0 || envelope.events.length > MAX_EVENTS) fail("matrix_events_invalid");
  const events = envelope.events.map(normalizeEvent);
  const workers = [];
  const accepted = [];
  for (const event of events) {
    const worker = parseCompletedWorkerMarker(event.body);
    const leaderAccepted = parseAcceptedV2Marker(event.body);
    if (worker && scopeMatches(worker, expected)) workers.push({ marker: worker, ...event });
    if (leaderAccepted && scopeMatches(leaderAccepted, expected)) accepted.push({ marker: leaderAccepted, ...event });
  }
  for (const role of expected.roles) {
    const roleWorkers = workers.filter((candidate) => candidate.marker.role === role);
    for (const worker of roleWorkers) {
      if (worker.sender !== expected.workerSenders[role]) fail("worker_sender_mismatch");
      if (!timestampMatches(worker.marker.at, worker.timestamp)) fail("matrix_timestamp_mismatch");
    }
    const bindings = new Set(roleWorkers.map((candidate) => `${candidate.marker.workerTaskId}:${candidate.marker.receiptDigest}`));
    if (bindings.size > 1) fail("conflicting_worker_bindings");
  }
  const verified = accepted.map((candidate) => validateChain(candidate, workers, expected));
  const roleResults = [];
  for (const role of expected.roles) {
    const candidates = verified.filter((candidate) => candidate.role === role);
    if (candidates.length === 0) fail("missing_expected_role");
    const bindings = new Set(candidates.map((candidate) => `${candidate.receiptDigest}:${candidate.projectionDigest}`));
    if (bindings.size !== 1) fail("conflicting_receipt_bindings");
    const latest = [...candidates].sort((left, right) => Date.parse(right.at) - Date.parse(left.at))[0];
    roleResults.push({
      role,
      receiptDigest: latest.receiptDigest,
      projectionDigest: latest.projectionDigest,
      conclusion: latest.projection.conclusion,
      runtimeTraceClaimedValidated: latest.projection.runtimeSkillTraceValidated,
      domainSkillClaim: latest.projection.domainSkillReceipt
        ? { present: true, status: latest.projection.domainSkillReceipt.status }
        : { present: false, status: "none" },
      safetyCounters: latest.projection.safetyCounters,
      facts: latest.projection.facts.length,
      conflicts: latest.projection.conflicts.length,
      impacts: latest.projection.impacts.length,
      unknownFields: latest.projection.unknownFields.length,
    });
  }
  return {
    schema: RESULT_SCHEMA,
    verdict: "passed",
    verificationScope: "self_consistency_only",
    sourceAuthenticity: "not_verified",
    scopeAuthority: "caller_supplied",
    profile: expected.projectionProfile,
    eventCountExamined: events.length,
    expectedRoleCount: expected.roles.length,
    verifiedRoleCount: roleResults.length,
    zeroWritePolicy: expected.projectionProfile === "runtime-zero-write" ? "passed" : "not_requested",
    roles: roleResults,
  };
}

function usage() {
  return "Usage: node scripts/verify-matrix-receipts.mjs --input <export.json|-> [--pretty]";
}

function parseArgs(argv) {
  const options = { input: "", pretty: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--input") options.input = argv[++index] || "";
    else if (arg === "--pretty") options.pretty = true;
    else if (arg === "--help" || arg === "-h") return { help: true };
    else fail("cli_argument_invalid");
  }
  if (!options.input) fail("cli_input_required");
  return options;
}

function readInput(filename) {
  try {
    return filename === "-" ? fs.readFileSync(0, "utf8") : fs.readFileSync(filename, "utf8");
  } catch {
    const error = new ReceiptVerificationError("input_file_unreadable");
    error.exitCode = 2;
    throw error;
  }
}

export function runCli(argv) {
  const options = parseArgs(argv);
  if (options.help) {
    process.stdout.write(`${usage()}\n`);
    return 0;
  }
  let input;
  try {
    input = JSON.parse(readInput(options.input));
  } catch (error) {
    if (error instanceof ReceiptVerificationError) throw error;
    const wrapped = new ReceiptVerificationError("input_json_invalid");
    wrapped.exitCode = 2;
    throw wrapped;
  }
  const result = verifyReceiptExport(input);
  process.stdout.write(`${JSON.stringify(result, null, options.pretty ? 2 : 0)}\n`);
  return 0;
}

// 入口判定：mimi 环境适配修复（上游原为 argv[1] 反斜杠转斜杠后手拼 /盘符:/ 路径，
// 再与 new URL(import.meta.url).pathname 比较；含 ~（如 Windows 8.3 短路径 RUNNER~1）
// 或非 ASCII 的路径会被 URL 百分号编码，手拼路径不编码，永不相等，入口不执行、exit 0 无输出）。
// 改为标准的 pathToFileURL(process.argv[1]).href === import.meta.url，核验逻辑零改动。
const invokedPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : "";
if (invokedPath && invokedPath === import.meta.url) {
  try {
    process.exitCode = runCli(process.argv.slice(2));
  } catch (error) {
    const code = error instanceof ReceiptVerificationError ? error.code : "verification_internal_error";
    process.stdout.write(`${JSON.stringify({ schema: RESULT_SCHEMA, verdict: "failed", code })}\n`);
    process.exitCode = error?.exitCode || (code.startsWith("cli_") || code.startsWith("input_") ? 2 : 1);
  }
}
