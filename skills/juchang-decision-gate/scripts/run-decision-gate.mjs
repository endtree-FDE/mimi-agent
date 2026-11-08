// run-decision-gate.mjs——juchang 决策门禁 CLI（自包含版）。
// 上游版本 import 仓库外 app/src/lib/admin/route-gate.ts；本版把移植后的 route-gate.mjs
// 放在同目录，技能包自包含。其余逻辑与上游一致：评估并返回 JSON，不改数据、不发消息。
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

import { decideRouteGate } from "./route-gate.mjs";

const ENUMS = {
  actionLevel: ["L0", "L1", "L2", "L3"],
  evidenceState: ["sufficient", "partial", "conflict", "missing"],
  likelihood: ["rare", "possible", "likely", "certain"],
  impact: ["low", "medium", "high", "critical"],
  reversibility: ["reversible", "compensatable", "irreversible"],
  complexity: ["simple", "multi_source", "cross_system"],
  deadline: ["immediate", "soon", "normal", "none"],
};

const REQUIRED_FIELDS = ["actionLevel", "evidenceState", "likelihood", "impact", "reversibility", "complexity"];

function usage() {
  return "Usage: run-decision-gate.mjs (--input <file.json> | --json <json> | --stdin)";
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

async function readPayload(args) {
  const inputIndex = args.indexOf("--input");
  const jsonIndex = args.indexOf("--json");
  const sources = Number(inputIndex >= 0) + Number(jsonIndex >= 0) + Number(args.includes("--stdin"));
  if (sources !== 1) throw new Error(usage());
  if (inputIndex >= 0) {
    if (!args[inputIndex + 1]) throw new Error(usage());
    return readFile(args[inputIndex + 1], "utf8");
  }
  if (jsonIndex >= 0) {
    if (!args[jsonIndex + 1]) throw new Error(usage());
    return args[jsonIndex + 1];
  }
  return readStdin();
}

function validateInput(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Input must be a JSON object.");
  for (const field of REQUIRED_FIELDS) {
    if (!ENUMS[field].includes(input[field])) throw new Error(`${field} must be one of: ${ENUMS[field].join(", ")}.`);
  }
  if (input.deadline !== undefined && !ENUMS.deadline.includes(input.deadline)) {
    throw new Error(`deadline must be one of: ${ENUMS.deadline.join(", ")}.`);
  }
  for (const field of ["supportingEvidence", "contradictingEvidence", "affectedObjectCount", "dependencyDepth", "waitingHours"]) {
    if (input[field] !== undefined && (typeof input[field] !== "number" || !Number.isFinite(input[field]))) {
      throw new Error(`${field} must be a finite number when provided.`);
    }
  }
  return input;
}

export function evaluateDecisionGate(input, evaluatedAt = new Date().toISOString()) {
  const validated = validateInput(input);
  const { changeRef = "", projectRef = "", adapterRef = "", ...gateInput } = validated;
  const decision = decideRouteGate(gateInput);
  const normalizedAdapterRef = typeof adapterRef === "string" ? adapterRef : "";
  return {
    schema: "juchang-decision-gate@1",
    changeRef: typeof changeRef === "string" ? changeRef : "",
    projectRef: typeof projectRef === "string" ? projectRef : "",
    adapterRef: normalizedAdapterRef,
    evaluatedAt,
    input: gateInput,
    flow: {
      decisionSkill: "juchang-decision-gate@1",
      preparation: decision.preparationRoute === "team" ? "agentteams" : decision.preparationRoute,
      approval: decision.approvalMode,
      executionTarget: decision.executionMode === "blocked" ? "none" : (normalizedAdapterRef || "unspecified-adapter"),
      receiptRequired: decision.executionMode !== "blocked",
    },
    decision: {
      preparationRoute: decision.preparationRoute,
      approvalMode: decision.approvalMode,
      executionMode: decision.executionMode,
      evidenceSupport: decision.evidenceSupport,
      evidenceSupportBand: decision.evidenceSupportBand,
      evidencePosterior: { alpha: decision.evidenceAlpha, beta: decision.evidenceBeta },
      expectedLossIndex: decision.expectedLoss.value,
      expectedLossBand: decision.expectedLoss.band,
      queuePriority: decision.queuePriority,
      propagation: decision.propagation,
      requiredControls: decision.requiredControls,
      reasons: decision.reasons,
    },
    boundaries: {
      scoreGrantsPermission: false,
      agentTeamsMayApprove: false,
      skillMayExecuteWrites: false,
      rerunAfterMaterialChange: true,
    },
  };
}

async function main() {
  try {
    const raw = await readPayload(process.argv.slice(2));
    process.stdout.write(`${JSON.stringify(evaluateDecisionGate(JSON.parse(raw)), null, 2)}\n`);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 2;
  }
}

const entryPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : "";
if (entryPath === import.meta.url) await main();
