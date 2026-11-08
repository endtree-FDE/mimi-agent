---
name: juchang-decision-gate
description: 决策门禁：按证据状态 × 动作等级 × 可逆性把写提案路由到允许进确认 / 需确认 / 阻断 / 只允许人工。只算路由，不执行、不给权限；分数只排先后。
---

# juchang 决策门禁

把「这个动作能不能做」变成可审计的确定性路由，而不是一句保证。

> mimi 实例版说明：本包是 juchang-skills 仓 juchang-decision-gate 的中文缩短版；完整契约见 references/contract.md 与上游仓库。公式源码 scripts/route-gate.mjs、scripts/decision-math.mjs 由上游 TypeScript 机械剥类型移植，行为等价性由 scripts/route-gate.test.mjs（上游 16 条测试原样移植）验证。

## 何时用

- 群友要让机器人写入飞书（建文档 / 追加内容 / 记日程 / 写表格 / 记群记忆）之前；
- 需要判断一个动作是允许、需要谁确认、还是必须先补依据；
- 需要一条带路由依据的审计记录。

## 路由维度

1. 动作等级：L0 只读查询 / L1 私有草稿 / L2 公开修改 / L3 不可逆或批量动作。
2. 证据状态：sufficient 依据完整 / partial 依据不完整 / conflict 依据冲突 / missing 缺少依据。
3. 可逆性：reversible 可直接撤销 / compensatable 可补偿恢复 / irreversible 难以恢复。

## 路由结果

| executionMode | 人话 | mimi 里的动作 |
|---|---|---|
| automatic | 可以自动执行 | 仍走发起人确认（mimi 确认不能关，门禁只能加严不能放宽） |
| after_approval | 批准后执行 | 走白名单发起人 + 确认码 / 卡片的既有确认流 |
| manual_only | 只允许人工执行 | 机器人拒绝代做，提示管理员自行操作 |
| blocked | 暂不允许执行 | 拒绝提案，先补齐或解决依据问题 |

## 用法（mimi 内）

只读查询路由用 `decision_gate_check` 工具（默认关，配置 `tools.decision_gate_check.enabled=true` 后启用）：

```json
{"tool":"decision_gate_check","args":{"input":{"actionLevel":"L2","evidenceState":"sufficient","likelihood":"possible","impact":"medium","reversibility":"reversible","complexity":"simple"}}}
```

写提案自动过门：配置 `write.decision_gate.enabled=true`，并在 `write.decision_gate.tools` 里声明各写工具的等级（如 `"docs_create": "L2"`）。propose 阶段自动评估：blocked / manual_only 的拒绝话术带路由依据，放行的提案审计里写 gate 字段（等级、证据状态与来源、路由、审批模式）。

证据状态的来源：写提案若依据 OCR / 文档内容，先跑 `evidencegate_check`（门一），其三路由映射为证据状态（ACCEPT_CANDIDATE→sufficient、HUMAN_REVIEW→partial、MODEL_OUTPUT_INVALID→missing）作为本门禁（门二）的输入；没有近期证据检查时用配置默认并在审计里写明来源。

## 硬边界

- conflict / missing 证据无条件阻断公开与高后果执行，数值再好也不放行。
- partial 证据阻断 L2 / L3 执行。
- L2 必须具名批准；L3 只允许人工执行并需双人复核。
- 队列优先级只决定先后，永远不给权限。
- 预计损失指数与折算影响量是操作比较模型：不是钱、不是确定性、不是真相、不是许可。
- 本 Skill 不执行任何写入、不发消息、不改动数据；它只会说「不」。
