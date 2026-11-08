// route-gate.mjs——由 zhuantang-art 仓 app/src/lib/admin/route-gate.ts 机械剥类型移植（2026-11-08）。
// 只删了 TypeScript 类型注解、export type 块与 as const，路由规则、先验与标签逐行保持一致；
// 行为等价性由同目录 route-gate.test.mjs（上游测试原样移植）验证。
import {
  calculateExpectedLoss,
  calculateQueuePriority,
  propagateImpact,
  updateBetaEvidence,
} from "./decision-math.mjs";

export const ACTION_LEVEL_LABELS = {
  L0: "只读查询",
  L1: "私有草稿",
  L2: "公开修改",
  L3: "不可逆或批量动作",
};

export const EVIDENCE_STATE_LABELS = {
  sufficient: "依据完整",
  partial: "依据不完整",
  conflict: "依据冲突",
  missing: "缺少依据",
};

export const LIKELIHOOD_LABELS = {
  rare: "较少发生",
  possible: "可能发生",
  likely: "较易发生",
  certain: "几乎确定",
};

export const IMPACT_LABELS = {
  low: "低影响",
  medium: "中影响",
  high: "高影响",
  critical: "严重影响",
};

export const REVERSIBILITY_LABELS = {
  reversible: "可以直接撤销",
  compensatable: "可以补偿恢复",
  irreversible: "难以恢复",
};

export const COMPLEXITY_LABELS = {
  simple: "单一对象",
  multi_source: "多来源核对",
  cross_system: "跨系统影响",
};

export const PREPARATION_ROUTE_LABELS = {
  rule: "规则直接处理",
  solo: "单人辅助处理",
  team: "协作处理",
  human: "人工处理",
};

export const APPROVAL_MODE_LABELS = {
  none: "无需额外批准",
  named: "负责人批准",
  dual: "双人复核",
};

export const EXECUTION_MODE_LABELS = {
  automatic: "可以自动执行",
  after_approval: "批准后执行",
  manual_only: "只允许人工执行",
  blocked: "暂不允许执行",
};

export const EXPOSURE_BAND_LABELS = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "严重",
};

export const DEADLINE_LABELS = {
  immediate: "24 小时内",
  soon: "3 天内",
  normal: "一周内",
  none: "无明确期限",
};

export const EVIDENCE_SUPPORT_LABELS = {
  weak: "较弱",
  unresolved: "待核",
  moderate: "中等",
  strong: "较强",
};

export const EXPECTED_LOSS_BAND_LABELS = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "严重",
};

export const QUEUE_PRIORITY_BAND_LABELS = {
  routine: "常规",
  soon: "尽快",
  priority: "优先",
  urgent: "紧急",
};

export const PROPAGATION_BAND_LABELS = {
  local: "当前对象",
  connected: "少量关联",
  wide: "较广关联",
  extensive: "广泛影响",
};

export const CONTROL_LABELS = {
  evidence_resolution: "先补齐或解决冲突依据",
  idempotency: "防止重复执行",
  named_approval: "记录负责人批准",
  dual_approval: "两人分别复核",
  receipt: "保留执行记录",
  readback: "执行后核对结果",
  rollback_plan: "执行前准备回退方案",
  compensation_plan: "执行前准备补偿方案",
  bounded_batch: "逐条或小批执行",
  stop_on_failure: "任一失败立即停止",
};

const LIKELIHOOD_WEIGHT = {
  rare: 1,
  possible: 2,
  likely: 3,
  certain: 4,
};

const IMPACT_WEIGHT = {
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

const LIKELIHOOD_PROBABILITY = {
  rare: 0.1,
  possible: 0.3,
  likely: 0.6,
  certain: 0.9,
};

const IMPACT_COST = {
  low: 1,
  medium: 4,
  high: 10,
  critical: 25,
};

const REVERSIBILITY_MULTIPLIER = {
  reversible: 1,
  compensatable: 1.4,
  irreversible: 2,
};

const EVIDENCE_PRIOR = {
  sufficient: { alpha: 4, beta: 1 },
  partial: { alpha: 2, beta: 2 },
  conflict: { alpha: 1, beta: 3 },
  missing: { alpha: 1, beta: 4 },
};

const DEADLINE_WEIGHT = {
  immediate: 30,
  soon: 20,
  normal: 10,
  none: 0,
};

function exposureBand(score) {
  if (score <= 3) return "low";
  if (score <= 7) return "medium";
  if (score <= 11) return "high";
  return "critical";
}

export function formatDecisionNumber(value) {
  return Number(value.toFixed(1)).toString();
}

function evidenceSupportBand(probability) {
  if (probability < 0.4) return "weak";
  if (probability < 0.6) return "unresolved";
  if (probability < 0.8) return "moderate";
  return "strong";
}

function preparationRoute(input, propagation) {
  if (input.actionLevel === "L3") {
    return input.complexity === "simple" && propagation.band === "local" ? "human" : "team";
  }
  if (
    input.governanceMode === "sole_owner"
    && input.ownerAttested === true
    && input.actionLevel === "L2"
    && input.evidenceState === "sufficient"
    && input.reversibility === "reversible"
    && input.complexity !== "cross_system"
    && input.impact !== "critical"
  ) return "solo";
  if (propagation.band === "wide" || propagation.band === "extensive") return "team";
  if (input.complexity === "cross_system") return "team";
  if (input.complexity === "multi_source") {
    return input.evidenceState === "sufficient" ? "solo" : "team";
  }
  if (input.actionLevel === "L0" && input.evidenceState === "sufficient") return "rule";
  return "solo";
}

function approvalMode(
  input,
  expectedLoss,
  propagation,
) {
  if (input.actionLevel === "L3") return "dual";
  if (input.actionLevel === "L2") {
    if (
      input.governanceMode === "sole_owner"
      && input.ownerAttested === true
      && input.evidenceState === "sufficient"
      && input.reversibility === "reversible"
      && input.complexity !== "cross_system"
      && input.impact !== "critical"
    ) return "named";
    return input.impact === "critical"
      || expectedLoss.band === "critical"
      || propagation.band === "extensive"
      ? "dual"
      : "named";
  }
  if (input.reversibility === "irreversible") return "named";
  return "none";
}

function evidenceBlocksExecution(input, evidenceSupport) {
  if (input.evidenceState === "conflict" || input.evidenceState === "missing") return true;
  if (input.evidenceState === "partial" && (input.actionLevel === "L2" || input.actionLevel === "L3")) return true;
  return evidenceSupport < 0.5 && (input.actionLevel === "L2" || input.actionLevel === "L3");
}

function executionMode(input, evidenceSupport) {
  if (evidenceBlocksExecution(input, evidenceSupport)) return "blocked";
  if (input.actionLevel === "L3" || input.reversibility === "irreversible") return "manual_only";
  if (input.actionLevel === "L2") return "after_approval";
  return "automatic";
}

function requiredControls(
  input,
  approval,
  evidenceSupport,
) {
  const controls = [];
  if (evidenceBlocksExecution(input, evidenceSupport)) controls.push("evidence_resolution");
  if (input.actionLevel !== "L0") controls.push("idempotency");
  if (approval === "named") controls.push("named_approval");
  if (approval === "dual") controls.push("dual_approval");
  controls.push("receipt");
  if (input.actionLevel !== "L0") controls.push("readback");
  if (input.actionLevel === "L2") controls.push("rollback_plan");
  if (input.actionLevel === "L3" || input.reversibility === "irreversible") controls.push("compensation_plan");
  if (input.actionLevel === "L2" && input.governanceMode === "sole_owner" && input.ownerAttested === true) {
    controls.push("bounded_batch", "stop_on_failure");
  }
  return controls;
}

export function decideRouteGate(input) {
  const evidencePrior = EVIDENCE_PRIOR[input.evidenceState];
  const evidence = updateBetaEvidence({
    priorAlpha: evidencePrior.alpha,
    priorBeta: evidencePrior.beta,
    supportingObservations: input.supportingEvidence ?? 0,
    contradictingObservations: input.contradictingEvidence ?? 0,
  });
  const propagation = propagateImpact({
    directTargets: input.affectedObjectCount ?? 1,
    dependencyDepth: input.dependencyDepth ?? 0,
  });
  const expectedLoss = calculateExpectedLoss({
    eventProbability: LIKELIHOOD_PROBABILITY[input.likelihood],
    impactCost: IMPACT_COST[input.impact],
    reversibilityMultiplier: REVERSIBILITY_MULTIPLIER[input.reversibility],
    propagatedScope: propagation.effectiveScope,
  });
  const likelihoodWeight = LIKELIHOOD_WEIGHT[input.likelihood];
  const impactWeight = IMPACT_WEIGHT[input.impact];
  const score = likelihoodWeight * impactWeight;
  const route = preparationRoute(input, propagation);
  const approval = approvalMode(input, expectedLoss, propagation);
  const execution = executionMode(input, evidence.supportProbability);
  const queuePriority = calculateQueuePriority({
    expectedLoss: expectedLoss.value,
    deadlineWeight: DEADLINE_WEIGHT[input.deadline ?? "normal"],
    waitingHours: input.waitingHours ?? 0,
    blocked: execution === "blocked",
  });
  const reasons = [
    `依据支持度更新为 ${Math.round(evidence.supportProbability * 100)}%，冲突状态仍须人工解决。`,
    `预计损失指数为 ${formatDecisionNumber(expectedLoss.value)}，用于比较处理代价，不改变动作权限。`,
    `折算影响量为 ${formatDecisionNumber(propagation.effectiveScope)}，覆盖 ${propagation.layers.length} 层关系。`,
    `当前处理顺序为 ${queuePriority.score}/100，只决定先后，不代表允许执行。`,
    `${ACTION_LEVEL_LABELS[input.actionLevel]}决定审批和执行边界。`,
    route === "team"
      ? `${COMPLEXITY_LABELS[input.complexity]}需要分工核对，但协作结果不能替代批准。`
      : `${COMPLEXITY_LABELS[input.complexity]}由${PREPARATION_ROUTE_LABELS[route]}准备。`,
  ];

  if (evidenceBlocksExecution(input, evidence.supportProbability)) {
    reasons.unshift(`${EVIDENCE_STATE_LABELS[input.evidenceState]}，在继续执行前必须先处理依据问题。`);
  }
  if (input.reversibility === "irreversible") {
    reasons.push("动作难以恢复，只能由人执行并保留补偿方案。");
  }
  if (input.governanceMode === "sole_owner" && input.ownerAttested === true && approval === "named") {
    reasons.push("项目由唯一负责人承担实名批准；不得虚构第二批准人，执行仍须逐条回读并可回滚。");
  }

  return {
    preparationRoute: route,
    approvalMode: approval,
    executionMode: execution,
    likelihoodWeight,
    impactWeight,
    exposureScore: score,
    exposureBand: exposureBand(score),
    evidenceSupport: evidence.supportProbability,
    evidenceSupportBand: evidenceSupportBand(evidence.supportProbability),
    evidenceAlpha: evidence.alpha,
    evidenceBeta: evidence.beta,
    expectedLoss,
    queuePriority,
    propagation,
    requiredControls: requiredControls(input, approval, evidence.supportProbability),
    reasons,
  };
}
