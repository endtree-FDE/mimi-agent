// route-gate.test.mjs——上游 zhuantang-art 仓 route-gate.test.mjs 原样移植（2026-11-08）。
// 只改了三处环境适配：import 指向同目录的 .mjs 移植版；CLI 路径同目录；
// spawn 去掉 --disable-warning=MODULE_TYPELESS_PACKAGE_JSON（Node 21+ 旗标，CI runner 版本不可控，
// 且本仓库无 package.json，不会触发该警告）。断言与用例逐字保持一致，用来证明机械移植的行为等价性。
// 跑法：node --test skills/juchang-decision-gate/scripts/route-gate.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { decideRouteGate } from "./route-gate.mjs";
import {
  calculateExpectedLoss,
  calculateQueuePriority,
  propagateImpact,
  updateBetaEvidence,
} from "./decision-math.mjs";

function profile(overrides = {}) {
  return {
    actionLevel: "L0",
    evidenceState: "sufficient",
    likelihood: "possible",
    impact: "low",
    reversibility: "reversible",
    complexity: "simple",
    ...overrides,
  };
}

const decisionSkillCli = fileURLToPath(
  new URL("./run-decision-gate.mjs", import.meta.url),
);

function runDecisionSkill(input) {
  const result = spawnSync(
    process.execPath,
    [decisionSkillCli, "--json", JSON.stringify(input)],
    { encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout);
}

test("a supported read-only action can run through deterministic rules", () => {
  const decision = decideRouteGate(profile());
  assert.equal(decision.preparationRoute, "rule");
  assert.equal(decision.approvalMode, "none");
  assert.equal(decision.executionMode, "automatic");
  assert.equal(decision.exposureScore, 2);
});

test("a reversible private draft uses one assistant and leaves controls", () => {
  const decision = decideRouteGate(profile({ actionLevel: "L1", impact: "medium" }));
  assert.equal(decision.preparationRoute, "solo");
  assert.equal(decision.executionMode, "automatic");
  assert.deepEqual(decision.requiredControls, ["idempotency", "receipt", "readback"]);
});

test("a public write always requires named approval", () => {
  const decision = decideRouteGate(profile({ actionLevel: "L2", impact: "medium" }));
  assert.equal(decision.approvalMode, "named");
  assert.equal(decision.executionMode, "after_approval");
});

test("conflicting evidence blocks execution even when the numeric exposure is low", () => {
  const decision = decideRouteGate(profile({ evidenceState: "conflict", likelihood: "rare" }));
  assert.equal(decision.exposureScore, 1);
  assert.equal(decision.executionMode, "blocked");
  assert.match(decision.reasons.join(" "), /依据/);
});

test("cross-system complexity selects collaboration without granting approval", () => {
  const decision = decideRouteGate(profile({
    actionLevel: "L2",
    complexity: "cross_system",
    impact: "high",
    likelihood: "likely",
  }));
  assert.equal(decision.preparationRoute, "team");
  assert.equal(decision.approvalMode, "named");
  assert.equal(decision.executionMode, "after_approval");
});

test("irreversible or destructive actions stay manual and require two-person approval", () => {
  const decision = decideRouteGate(profile({
    actionLevel: "L3",
    impact: "critical",
    likelihood: "likely",
    reversibility: "irreversible",
    complexity: "cross_system",
  }));
  assert.equal(decision.preparationRoute, "team");
  assert.equal(decision.approvalMode, "dual");
  assert.equal(decision.executionMode, "manual_only");
  assert.ok(decision.requiredControls.includes("compensation_plan"));
});

test("critical public changes use two-person approval even below L3", () => {
  const decision = decideRouteGate(profile({
    actionLevel: "L2",
    impact: "critical",
    likelihood: "possible",
  }));
  assert.equal(decision.approvalMode, "dual");
  assert.equal(decision.executionMode, "after_approval");
});

test("evidence observations update a Beta posterior without claiming certainty", () => {
  const posterior = updateBetaEvidence({
    priorAlpha: 2,
    priorBeta: 2,
    supportingObservations: 3,
    contradictingObservations: 1,
  });
  assert.equal(posterior.alpha, 5);
  assert.equal(posterior.beta, 3);
  assert.equal(posterior.supportProbability, 0.625);
});

test("expected loss rises with impact, irreversibility and propagated scope", () => {
  const low = calculateExpectedLoss({
    eventProbability: 0.1,
    impactCost: 1,
    reversibilityMultiplier: 1,
    propagatedScope: 1,
  });
  const high = calculateExpectedLoss({
    eventProbability: 0.6,
    impactCost: 10,
    reversibilityMultiplier: 2,
    propagatedScope: 3,
  });
  assert.equal(low.value, 0.1);
  assert.ok(high.value > low.value);
  assert.equal(high.band, "critical");
});

test("queue priority is bounded and increases with urgency and waiting", () => {
  const normal = calculateQueuePriority({ expectedLoss: 2, deadlineWeight: 10, waitingHours: 0, blocked: false });
  const urgent = calculateQueuePriority({ expectedLoss: 2, deadlineWeight: 30, waitingHours: 96, blocked: true });
  assert.ok(urgent.score > normal.score);
  assert.ok(urgent.score <= 100);
});

test("impact propagation decays by layer and returns a stable aggregate", () => {
  const propagation = propagateImpact({ directTargets: 2, dependencyDepth: 2, attenuation: 0.5 });
  assert.deepEqual(propagation.layers, [2, 1, 0.5]);
  assert.equal(propagation.effectiveScope, 3.5);
});

test("strong observations do not override an unresolved evidence conflict", () => {
  const decision = decideRouteGate(profile({
    actionLevel: "L2",
    evidenceState: "conflict",
    supportingEvidence: 20,
    contradictingEvidence: 0,
  }));
  assert.ok(decision.evidenceSupport > 0.8);
  assert.equal(decision.executionMode, "blocked");
});

test("wide downstream influence selects collaboration and stronger approval", () => {
  const decision = decideRouteGate(profile({
    actionLevel: "L2",
    likelihood: "likely",
    impact: "high",
    affectedObjectCount: 8,
    dependencyDepth: 3,
  }));
  assert.equal(decision.preparationRoute, "team");
  assert.equal(decision.approvalMode, "dual");
  assert.ok(decision.propagation.effectiveScope > 10);
});

test("the decision skill returns a versioned audit contract", () => {
  const result = runDecisionSkill(profile({
    changeRef: "change-001",
    projectRef: "zhuantang-yixun",
    adapterRef: "yixun-local",
    actionLevel: "L2",
  }));
  assert.equal(result.schema, "juchang-decision-gate@1");
  assert.equal(result.projectRef, "zhuantang-yixun");
  assert.equal(result.adapterRef, "yixun-local");
  assert.equal(result.flow.decisionSkill, "juchang-decision-gate@1");
  assert.equal(result.flow.executionTarget, "yixun-local");
  assert.equal(result.flow.receiptRequired, true);
  assert.equal(result.decision.executionMode, "after_approval");
  assert.equal(result.decision.approvalMode, "named");
  assert.equal(result.boundaries.scoreGrantsPermission, false);
});

test("the decision skill keeps evidence conflict as a hard gate", () => {
  const result = runDecisionSkill(profile({
    actionLevel: "L2",
    evidenceState: "conflict",
    supportingEvidence: 20,
  }));
  assert.equal(result.decision.executionMode, "blocked");
  assert.equal(result.flow.executionTarget, "none");
  assert.equal(result.flow.receiptRequired, false);
  assert.equal(result.decision.evidenceSupport, 0.875);
  assert.ok(result.decision.requiredControls.includes("evidence_resolution"));
});

test("the decision skill routes wide changes to AgentTeams preparation without granting approval", () => {
  const result = runDecisionSkill(profile({
    projectRef: "zhuantang-yixun",
    adapterRef: "yixun-local",
    actionLevel: "L2",
    likelihood: "likely",
    impact: "high",
    reversibility: "compensatable",
    complexity: "cross_system",
    affectedObjectCount: 8,
    dependencyDepth: 3,
    deadline: "immediate",
  }));
  assert.equal(result.decision.preparationRoute, "team");
  assert.equal(result.flow.preparation, "agentteams");
  assert.equal(result.flow.executionTarget, "yixun-local");
  assert.equal(result.decision.approvalMode, "dual");
  assert.equal(result.decision.executionMode, "after_approval");
  assert.equal(result.boundaries.agentTeamsMayApprove, false);
});
