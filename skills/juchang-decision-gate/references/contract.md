# Decision contract

## Input

Provide a JSON object:

```json
{
  "changeRef": "stable-change-id",
  "projectRef": "zhuantang-yixun",
  "adapterRef": "yixun-local",
  "actionLevel": "L0 | L1 | L2 | L3",
  "evidenceState": "sufficient | partial | conflict | missing",
  "likelihood": "rare | possible | likely | certain",
  "impact": "low | medium | high | critical",
  "reversibility": "reversible | compensatable | irreversible",
  "complexity": "simple | multi_source | cross_system",
  "supportingEvidence": 0,
  "contradictingEvidence": 0,
  "affectedObjectCount": 1,
  "dependencyDepth": 0,
  "deadline": "immediate | soon | normal | none",
  "waitingHours": 0
}
```

`changeRef`, `projectRef`, and `adapterRef` are trace metadata and are not part of the calculation. Optional numeric fields default in the shared gate. Dependency depth is capped at three layers.

## Output

The CLI returns `juchang-decision-gate@1` JSON containing:

- the trace metadata, normalized input, and runtime evaluation time;
- `preparationRoute`: `rule`, `solo`, `team`, or `human`;
- `approvalMode`: `none`, `named`, or `dual`;
- `executionMode`: `automatic`, `after_approval`, `manual_only`, or `blocked`;
- a `flow` object naming the decision Skill, preparation route, approval route, execution adapter, and receipt requirement;
- evidence posterior, expected-loss index, queue priority, and propagated scope;
- required controls, human-readable reasons, and explicit authority boundaries.

## Responsibility separation

| Layer | Responsibility | May approve? | May execute? |
| --- | --- | --- | --- |
| JUCHANG Decision Skill | Calculate and explain a deterministic route | No | No |
| Rule/solo preparation | Collect facts and draft a proposal | No | Only when the gate explicitly returns automatic |
| AgentTeams preparation | Split complex verification and reconcile findings | No | No |
| Named/dual approver | Accept responsibility for the proposed action | Yes | Only within the granted action boundary |
| Project adapter | Perform an already authorized action in YIXUN, Feishu, pretix, Chatwoot, or another declared system and return receipts | No new approval | Yes, within approval scope |

## Mathematical interpretation

- Evidence support uses a Beta prior selected from the categorical evidence state plus counted supporting and contradicting observations.
- Expected loss index multiplies event probability, impact cost, recovery multiplier, and propagated scope.
- Propagated scope starts with directly affected objects and discounts each downstream layer by `0.6`.
- Queue priority combines expected loss, deadline, waiting time, and evidence blockage on a bounded `0–100` scale.

These are operational comparison models, not universal mathematical truths. Calibrate their priors and weights only from reviewed historical cases, never by changing them to make a preferred action pass.

## Hard boundaries

- `conflict` and `missing` evidence block public/high-consequence execution regardless of posterior score.
- `partial` evidence blocks `L2` and `L3` execution.
- `L2` always requires named or dual approval.
- `L3` remains manual and requires dual review.
- Queue priority never grants permission.
- AgentTeams is a preparation route, not an authority, knowledge base, or execution engine.
- A project adapter executes only after authorization and must return a receipt/readback result.

> AI生成
