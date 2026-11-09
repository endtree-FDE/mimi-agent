# v0.13.0 发布说明

版本号是仓库根目录的 `VERSION`：`0.13.0`。发布日期是 2026-11-09。正文不写密钥、群号、open_id、客户名或个人电脑路径。

这一版相对 [v0.12.0](release-0.12.0.md)（`14fa29f`）。本页正文不写 `agents/mimi.json` 这类实例名，用「实例目录」指代。

## 这一版加了什么

旧的 `agents/*.json` 不改也能接着跑。据场三门与写提案门禁全部默认关，不写那几段配置，行为就和 0.12.0 一模一样。

- **据场三门（juchang-skills 第一批三个成熟 Skill 的 mimi 适配版，全部默认关）**。门一 `evidencegate_check`（0.12.0 已有）管「内容可信度」；这一版补上门二 `decision_gate_check`（按证据状态×动作等级×可逆性算出写动作的路由与理由，只算不执行）与两个离线核对器 `evidence_replay_check`（证据回放）、`receipt_verify`（Matrix 回执导出，结果只证明内部一致）。三个技能包进 `skills/`，脚本零依赖（Node 标准库）。决策门禁的公式由上游 TypeScript 机械剥类型移植，行为等价性用上游 16 条测试原样移植验证（`node --test` 全绿）。
- **写提案决策门禁 `write.decision_gate`（默认关）**。在 `tools` 里声明写工具的等级（如 `"docs_create": "L2"`）后，提案阶段自动过门：依据冲突或缺失阻断（说明理由），不可逆动作拒绝代做，其余放行进既有确认流——门禁只能加严不能放宽，`automatic` 在 mimi 里仍要发起人确认（确认不能关）。证据状态优先取本会话近期 `evidencegate_check` 的路由（双门联动），来源连同等级、路由一起写进审计。回滚 = 配置里删掉 `decision_gate` 段。
- **`/状态` 多一行门禁状态（三门全关时不出现）**：三门开关、最近 7 天放行提案 / 阻断 / 门禁查询次数、最近一次阻断的等级与依据来源。不打印编号、群号和路径。
- **证据链可核验闭环**：`skills/juchang-evidence-replay/scripts/freeze-audit.mjs` 零写入冻结导出器（stdout 只读），把群记忆与审计链冻结成可重算哈希的只读回放档案——`freeze.sourceText` 内嵌档案里，任何人可重算 `rawExportSha256` 比对；配合核对器核验。脚本不写文件、不发消息，守住零写入红线。用法见 skills/juchang-evidence-replay/SKILL.md。
- **结构防线与决策账本（学 pstack 的「Encode Lessons in Structure」）**：`checks/lint.py` 加两条硬规则（测试不得硬编码 gitignored 的实例配置——CI checkout 里没有那个文件；Node 技能入口判定必须限定 `pathToFileURL`——含 `~` 的 8.3 短路径会让手拼路径永不相等、入口静默不执行）与 `--selftest`（坏样例必须红、好样例不误报——「新检查必须先挂真实错误」）。新增 [docs/decisions.md](../docs/decisions.md) 项目决策账本（append-only，六列，evidence 是提交 / PR / tag 指针）。
- **文档**：[docs/决策门禁对照与接入方案.md](../docs/决策门禁对照与接入方案.md)（LangGraph / OpenAI Agents SDK / Claude Code / CrewAI 对照 juchang 三维路由的 18 条抄/不抄表）；[docs/从pstack学到的结构防线.md](../docs/从pstack学到的结构防线.md)；[agents/CONFIG.md](../agents/CONFIG.md) 补齐四个新键。

安全边界沿用既有红线：三门只读、只拦或放行，不代替执行；确认不能关；审计含路由依据；零写入（技能脚本不写文件、不发消息）。

## 从 0.12.0 换上

一个实例一个实例地换，看门狗大约 3 分钟看一次心跳，升级期间放锁，不用停那条计划任务。

```powershell
# 1 先确认这台现在是好的（只读）
python checks\verify_deploy.py --base . -c agents\<名字>.json --no-doctor
# 2 取代码，只接受快进；然后跑离线测试
git fetch origin --tags
git reset --keep v0.13.0
python tests\run_tests.py
# 3 放锁，平滑重启
. scripts\botproc.ps1; Set-DeployLock (Get-Location) 1200 'upgrade-0.13.0'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\reload.ps1 -Config agents\<名字>.json
# 4 复核，通过就释放锁
python checks\verify_deploy.py --base . -c agents\<名字>.json
. scripts\botproc.ps1; Clear-DeployLock (Get-Location)
```

换上之后在群里发 `/状态`，门禁开着时会多一行（本机实例已在 11-08 把决策门禁声明为 docs_create / base_create = L2 试运行，升级后这行就会出现）。想关掉写提案门禁：把 `write.decision_gate` 段删掉即可，无需改代码。

## 退回 0.12.0

退回目标是 `v0.12.0`。回滚比重启更危险：先停看门狗那条计划任务，再动代码，失败时让它留在停用状态。

```powershell
python checks\verify_deploy.py --base . -c agents\<名字>.json --no-doctor
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop.ps1
git reset --keep v0.12.0
python agentbot.py agents\<名字>.json --check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1 -Config agents\<名字>.json
python checks\verify_deploy.py --base . -c agents\<名字>.json
```

## 还没做（如实登记）

- dual 双人复核的第二确认人机制：现为文案提示（另一管理员跟帖），真有 critical 场景再上。
- Cursor CLI 视觉输出 → evidence schema 适配器：视觉模型输出若不是契约 JSON，门禁如实判 INVALID，属正确行为。
- 群里真实票据的端到端实测：代码已用生产配置形态验证，真实使用观察点是 `audit/*.jsonl` 的 `write_blocked`。
- 幕幕 / 灵波两台实例的复制部署：等主人定节奏。

> AI生成
