// decision-math.mjs——由 zhuantang-art 仓 app/src/lib/admin/decision-math.ts 机械剥类型移植（2026-11-08）。
// 只删了 TypeScript 类型注解与 export type 块，公式、常数与行为逐行保持一致；
// 行为等价性由同目录 route-gate.test.mjs（上游测试原样移植）验证。
function finiteNonNegative(value) {
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

function round(value, digits = 3) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export function updateBetaEvidence(input) {
  const priorAlpha = Math.max(0.001, finiteNonNegative(input.priorAlpha));
  const priorBeta = Math.max(0.001, finiteNonNegative(input.priorBeta));
  const supportingObservations = finiteNonNegative(input.supportingObservations);
  const contradictingObservations = finiteNonNegative(input.contradictingObservations);
  const alpha = priorAlpha + supportingObservations;
  const beta = priorBeta + contradictingObservations;

  return {
    alpha: round(alpha),
    beta: round(beta),
    supportProbability: round(alpha / (alpha + beta)),
    observationCount: round(supportingObservations + contradictingObservations),
  };
}

function expectedLossBand(value) {
  if (value <= 2) return "low";
  if (value <= 6) return "medium";
  if (value <= 18) return "high";
  return "critical";
}

export function calculateExpectedLoss({
  eventProbability,
  impactCost,
  reversibilityMultiplier,
  propagatedScope,
}) {
  const safeProbability = Math.min(1, finiteNonNegative(eventProbability));
  const safeImpactCost = finiteNonNegative(impactCost);
  const safeReversibility = Math.max(1, finiteNonNegative(reversibilityMultiplier));
  const safeScope = Math.max(1, finiteNonNegative(propagatedScope));
  const value = round(safeProbability * safeImpactCost * safeReversibility * safeScope);
  return {
    value,
    band: expectedLossBand(value),
    eventProbability: safeProbability,
    impactCost: safeImpactCost,
    reversibilityMultiplier: safeReversibility,
    propagatedScope: safeScope,
  };
}

function queuePriorityBand(score) {
  if (score <= 24) return "routine";
  if (score <= 49) return "soon";
  if (score <= 74) return "priority";
  return "urgent";
}

export function calculateQueuePriority({
  expectedLoss,
  deadlineWeight,
  waitingHours,
  blocked,
}) {
  const lossPoints = Math.min(50, finiteNonNegative(expectedLoss) * 2.5);
  const deadlinePoints = Math.min(30, finiteNonNegative(deadlineWeight));
  const waitingPoints = Math.min(15, finiteNonNegative(waitingHours) / 8);
  const evidencePoints = blocked ? 10 : 0;
  const score = Math.min(100, Math.round(lossPoints + deadlinePoints + waitingPoints + evidencePoints));
  return {
    score,
    band: queuePriorityBand(score),
    lossPoints: round(lossPoints),
    deadlinePoints: round(deadlinePoints),
    waitingPoints: round(waitingPoints),
    evidencePoints,
  };
}

function propagationBand(effectiveScope) {
  if (effectiveScope <= 2) return "local";
  if (effectiveScope <= 5) return "connected";
  if (effectiveScope <= 10) return "wide";
  return "extensive";
}

export function propagateImpact({
  directTargets,
  dependencyDepth,
  attenuation = 0.6,
}) {
  const targets = Math.max(1, Math.round(finiteNonNegative(directTargets)));
  const depth = Math.min(3, Math.max(0, Math.round(finiteNonNegative(dependencyDepth))));
  const decay = Math.min(0.95, Math.max(0.1, finiteNonNegative(attenuation)));
  const layers = Array.from({ length: depth + 1 }, (_, index) => round(targets * decay ** index));
  const effectiveScope = round(layers.reduce((sum, value) => sum + value, 0));
  return { layers, effectiveScope, band: propagationBand(effectiveScope), attenuation: decay };
}
