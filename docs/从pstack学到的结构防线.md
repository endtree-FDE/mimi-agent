# 从 pstack 学到的：Encode Lessons in Structure 在 mimi 的落地

2026-11-09 调研定稿。参考：Lauren Tan（poteto）开源的 Agent Harness `pstack`（仓库
`poteto/plugins/pstack`，Cursor 官方插件库可用；微信《Grok 土豆姐的 Agent 实战经验》一文介绍）。
对照物：mimi-agent 已有的工程纪律（evidence-first、决策门禁、审计账、先红后绿、零写入）。

一句话结论：**pstack 整套体系最值钱的是「Encode Lessons in Structure」——能用结构修复的，就只留
结构修复，写进文档的那行指令只是症状。mimi 已有代码闸门（决策门禁、审计），这次把它延伸到「开发
纪律本身」：把踩过的坑编码成 lint 硬规则，并立一份可审计的决策账本。**

## 一、pstack 到底给了什么（四层防线）

pstack 把「防 Agent 犯错」按确定性排了四层，精力从上往下投：

| 层 | 机制 | 为什么强 |
|---|---|---|
| 1 代码结构/架构 | 单一数据源、隐藏内部，错误写法写不出来 | 最高优先、零开销 |
| 2 类型/静态检查/Lint | `.hot.ts` 禁分配、体积红线；报错写明改法 | 硬拦截，读错自愈 |
| 3 测试/状态建模 | 断言外部行为，TLA+ 穷举并发死角 | 拦截行为错 |
| 4 文档/人工审查 | CLAUDE.md 只排主观判断 | **跳过不报错，最后防线** |

核心警句（pstack `principle-encode-lessons-in-structure` 原文）：**「Agent 跳过文档规则时什么都不会报错
（Nothing fails when an agent skips them）」**。所以同类错犯两次就该把规则编码成 lint/运行时检查，而不是
再加一行文档警告。另外两条纪律：

- **`/correct`**：同一类错犯两次才立规矩（偶发一次不加复杂度）；**新检查必须在真实历史错误上先挂过一次**（没红过的检查什么都证明不了）。
- **`/show-me-your-work`**：决策账本 `decisions.tsv` 一行一决策（ts/phase/decision/why/evidence/result），`evidence` 是指针不是散文，append-only，重大工作才写，跑完强制异构审计且自己审自己不算。

## 二、抄什么 / 不抄什么（对照 mimi）

| pstack 做法 | 抄不抄 | 在 mimi 怎么落 |
|---|---|---|
| 四层防线：能用结构修复就只留结构修复 | **抄** | 已有：决策门禁是代码闸门、审计是硬留痕、证据门禁是路由。这次把「开发纪律」也结构化了（见下） |
| lint/静态检查硬拦截 | **抄** | checks/lint.py 加两条规则，专门盯项目自己踩过的坑（真实案例，见下） |
| 新检查必须先挂真实错误（先红后绿） | **抄** | lint.py 加 `--selftest`：坏样例必须命中、好样例不误报，作为可跑断言 |
| 决策账本 decisions.tsv（六列 append-only + 异构审计） | **抄** | 新增 `docs/decisions.md`：按同六列补录 mimi 项目关键决策，append-only，evidence 是提交/PR/tag 指针 |
| 单入口 /poteto-mode（只给目标+验收+证据） | 不抄（借鉴） | mimi 是群机器人非 coding agent，无单入口场景；但「目标+验收+证据」这套交付口径我们一直沿用 |
| 异构模型分工（Grok 写特性 / Opus 裁判） | 不抄 | mimi 单模型通道；异构审计留给重大决策的人工对账 |
| 窄 PR 栈、写码 Agent 不自审 | 已抄 | mimi 一直窄 PR + CI 全绿 + 自审前先跑测试；本次继续 |
| `/interrogate` 多模型对抗审查 | 暂缓 | 可进 evidencegate 盲测筹备，不阻塞 |
| TLA+/statechart 并发形式化验证 | 暂缓 | mimi 单进程，pending 确认是既有幂等闸；真遇到并发死角再上 |

## 三、本次落地（M2 结构防线 + M3 决策账本）

### 1. checks/lint.py 两条「写不出来」规则（都来自真实踩坑）

- **规则 A（gitignored 生产配置）**：`tests/*.py` 里不得硬编码 `agents/<名字>.json`（example/config.schema 除外）。
  出处：test_juchang 的 e2e 曾 `json.load(agents/mimi.json)`，CI checkout 没有这个 gitignored 文件，ubuntu 整格崩。
  改法：用仓库内联配置蓝本；真要核对真实配置就在本机 `os.path.isfile` 守卫里读，或在文件前 8 行声明 `# gitignored-config-fixture`。
- 规则 B（Node 入口判定）：`skills/**/scripts/*.mjs` 的入口判定只认 `pathToFileURL(process.argv[1]).href === import.meta.url`。
  出处：verify-matrix-receipts.mjs 原版把 argv[1] 手拼 `/盘符:/` 再与 `new URL(import.meta.url).pathname` 比较，
  CI 的 8.3 短路径 `RUNNER~1`（含 `~`）在 URL pathname 里被编码成 `%7E` 而手拼不编码，永不相等、入口静默不执行（exit 0 无输出）。
- **`--selftest`**：每条规则用坏样例证明真能命中、用好样例证明不误报（对应 pstack 的「新检查必须先挂真实错误」）。

### 2. docs/decisions.md 决策账本

按 pstack 六列补录 mimi 关键决策（2026-07 至今：goai 归档、mcp 控制面、EvidenceGate 接入、三门接入、
入口判定修复、冻结器、本次结构防线），append-only，evidence 是提交/PR/tag 指针。见 [docs/decisions.md](docs/decisions.md)。

## 四、验收与回滚

- 验收：`python checks/lint.py --selftest` 与 `python checks/lint.py` 都退出 0（规则 A/B 自证会红）；全量 477/477 双编码全绿；decisions.md 六列齐全、evidence 全部可点。
- 回滚：lint 规则与文档都是增量，不改变运行行为；`git revert` 单提交即回上一版。

## 参考来源

- pstack：poteto/plugins（raw.githubusercontent.com/poteto/plugins/main/pstack/...）——principle-encode-lessons-in-structure/SKILL.md、show-me-your-work/SKILL.md + decision-log-template.tsv、correct/SKILL.md、interrogate
- 微信《Grok 土豆姐的 Agent 实战经验，这套 Harness 已开源！》（7I8p5lG4q1swF09ELF1jGw）
- 上一轮深挖结论见记忆日志 2026-11-08 15:27/15:33（pstack 真身、show-me-your-work 即决策账本、interrogate 多模型对抗）

> AI生成
