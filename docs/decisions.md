# 项目决策账本（append-only）

mimi-agent 的决策账本，格式对齐 [poteto/plugins 的 pstack](https://github.com/poteto/plugins/tree/main/pstack)
之 `show-me-your-work`（`decision-log-template.tsv`）六列：`ts / phase / decision / why / evidence / result`。

**纪律**（照 pstack 原文，见 [docs/从pstack学到的结构防线.md](docs/从pstack学到的结构防线.md)）：

- 一行一决策；**append-only**：记错了不编辑历史，追加一行写更正。
- `evidence` 是指针（提交号 / PR / 标签 / 文件路径），不是事实描述。
- 重大工作（合 PR、发版、上线、回滚、弃用、改安全边界）才写；日常小改不写。
- 跑完可让异构模型对账（interrogate），自己审自己不算。
- 页码显示「还没做完」的决策，留 `suggestion` 列写明下一步与时机。

## 账本

| ts | phase | decision | why | evidence | 备注 |
|----|-------|----------|-----|----------|------|
| 2026-07-19 | adopt | 把 zhuantang-art 作为艺文运营主仓持续维护 | 最活跃、作品以 JSON 维护、Cloudflare Pages 官网 | zhuantang-art main | 持续 |
| 2026-08-01 | adopt | evidencegate-ocr 定位「文档 AI 输出的厂商无关证据门禁」，坚持零写入 | 模型输出视为不可信候选，字段带证据+确定性契约+人工路由 | evidencegate-ocr main; README | v0.4.1 |
| 2026-10-28 | archive | GOAI 2026 比赛完结，goai-crisis-cloud-bridge 与 juchang-crisis-agentteams 归档 | 不再参与比赛，避免误导访客 | gh api archived=true | 可逆（unarchive） |
| 2026-10-28 | keep | juchang-skills、agentteams-dsh-runtime 不归档（mimi 升级要用 decision-gate/evidence-replay/receipt-verifier） | 制度沉淀，非比赛存档；mimi 写提案制度化要拿它 | juchang-skills main; agentteams-dsh-runtime main | 持续 |
| 2026-11-05 | adopt | v0.11.0 接待桥 intake（默认关，只进不出，无发送通路） | 访客合作意向先落本地待审，不直接进群 | v0.11.0; CHANGELOG | 已上线 |
| 2026-11-08 | adopt | v0.12.0 本地控制面 mcp_server.py（stdio 只读，无写入口）+ 意向待看提醒 + guard 冒号补洞 | OpenMausBot 第四个成熟案例的只读抄法；确认不能关 | PR #92(4cb48c0) / #93(14fa29f); deploy/mimi-20261108 | 已上线 |
| 2026-11-08 | adopt | EvidenceGate 接入 mimi（evidencegate_check 只读工具，默认关→实例启用）：群票据/文档先过门禁再答 | 门一管内容可信度；三路由（ACCEPT/HUMAN_REVIEW/INVALID）如实路由 | PR #94(d9fc5e1); deploy/mimi-20261108-evidencegate | 实例已启用 |
| 2026-11-08 | adopt | juchang 三门接入 mimi（decision-gate 包裹写提案流 + evidence_replay_check + receipt_verify，默认关） | 门二管动作是否允许；evidencegate 路由是 decision-gate 输入；门禁只能加严不能放宽，automatic 仍需确认 | PR #95(5f0514f); deploy/mimi-20261108-juchang | 实例已启用（docs_create/base_create=L2 试运行） |
| 2026-11-08 | fix | 回执核验脚本入口判定改用 pathToFileURL（上游手拼 URL pathname 在 8.3 短路径 `RUNNER~1` 下永不相等、入口静默不执行） | CI TEMP 含 `~` 路径触发；中文用户名路径同风险 | PR #95 提交 c30341f; checks/lint.py 规则 B | 已修+已编码防线 |
| 2026-11-09 | adopt | 零写入冻结导出器 freeze-audit.mjs（stdout 只读）把群记忆+审计链冻结成可重算哈希档案 | 兑现已写的哈希链冻结映射，符合本地 JSON 备份偏好，不破零写入 | PR #96(c1778e8); skills/juchang-evidence-replay/scripts/freeze-audit.mjs | 已上线 |
| 2026-11-09 | adopt | 从 pstack 学「Encode Lessons in Structure」：把四轮踩坑编码成 checks/lint.py 硬规则 + selftest | 文档能被跳过不报错，lint 当场拦截；新检查必须先挂真实错误 | PR #97; checks/lint.py; 规则 A/B | 本次 |
| 2026-11-09 | adopt | dual 双人复核落地：Tools.review() 独立于 confirm()（后者被同发起人校验挡住），第一位确认只记下不执行，第二位白名单管理员「复核 码」才执行 | 承认 juchang 契约 dual 场景的必需能力；门禁只能加严（fail closed：单人永不执行），取消不担；审计链 dual first → dual second → write_done 可回放 | confirm_mode.confirm_pattern 正则加「复核」; tools.py review(); agentbot.py 路由分支; tests/test_juchang.py test_dual_review | 本次 |
| 2026-11-09 | adopt | 双人复核第二人可配值班表 write.review_roster，默认关 | 高风险写的复核人按星期和时段收窄，不再只能从白名单里随便找一位；未配置行为不变；值班人仍须在 allowed_users；不抬日常 L2、不关确认；对不上班次时 fail closed | review_roster.py; tools.py review(); agents/example.json; tests/test_juchang.py test_review_roster | 本次 |

## 更正记录（append-only，不叠历史）

> 当前没有更正。记错时在此追加一行，注明更正哪一行与更正内容。

> AI生成
