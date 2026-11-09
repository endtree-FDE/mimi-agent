# OpenMausBot 对照与升级方案

调研日期：2026-11-08。这一页回答两件事：OpenMausBot 这个成熟案例里有什么值得抄的；借它的设计，mimi-agent 的下一版（v0.12.0）升什么、怎么升。前面已有三个案例（LangBot、AstrBot、NoneBot2，见 [多入口对照与方案.md](多入口对照与方案.md)）回答「访客怎么从浏览器进来」，这一页补第四种入口：「本机的程序和操作者怎么进来」。

结论先说：**本轮落两样——一个只读的本地控制面（stdio MCP server）和一个 guard 补洞**；声明式配置、headless CLI 全量对齐记在文末不做。所有引用来自实际读过的仓库文件，链接在每小节末尾。

## OpenMausBot 是什么

[milind-soni/OpenMausBot](https://github.com/milind-soni/OpenMausBot)：开源的 Grok Bot 替代品——「聊天应用形态的多 Agent 团队」。Apache-2.0，17.1k stars、2.4k forks、8,704 commits（2026-11-08 读数）。架构是两个进程：React 聊天界面（5199 端口）+ 本机 harness 服务器（127.0.0.1:8799），每个「联系人」是一个真 agent（Claude/Codex/Grok 的本机 CLI），带各自的人格、模型、云电脑和审批卡片。强调 local-first：转录、密钥、事件都在 `~/.openmausbot`。

与我们同频的三条设计（不需要抄，只是确认方向没走偏）：

1. **能力位缺就降级，不假装成功。** "Unknown drivers degrade to 'unavailable', never crash the fleet"——与我们 `channels/base.py` 的 16 项 `Cap` 和 `_UNAVAILABLE` 一句人话同一哲学。
2. **写入要人点头。** 审批卡片（Allow/Deny/在聊天里回答）加 permission broker，与我们「三道白名单 + 确认码」同一哲学。
3. **密钥 write-only。** "the UI only ever sees 'configured' flags"，与我们 `doctor.secret_keys`「只返回键名不返回值」同一哲学。

来源：[README](https://github.com/milind-soni/OpenMausBot#readme)（How it works、Features 两节）。

## 值得抄的四种设计

| 设计 | OpenMausBot 怎么做 | 我们现状 | 抄不抄 |
|---|---|---|---|
| 有界 MCP 控制面 | stdio MCP server 暴露「查状态、读转录、派活、等完成」，**故意不能**审批、删除、改凭据、控制电脑生命周期；转录分页封顶 200 条、搜索封顶 100 条、截图像素与权限密钥从结果移除、schema 拒绝未知字段 | 全仓库没有一个对外接口；主人之外想看机器人状态只能进群或私聊 | **本轮抄**（只读版，见下） |
| headless CLI 退出码契约 | 每个命令可打一个 JSON 文档，退出码枚举：0 完成 / 1 失败 / 2 参数错 / **3 需要人答** / 4 超时 / 5 连不上 / **6 `--check` 有变更** / 7 主机缺件 | `checks/verify_deploy.py` 已有 JSON 输出但退出码只有 0/1；`--doctor`、`--check`、`--dry-run` 已经覆盖大部分场景 | 记下不抄全（下一版可给 verify_deploy 补 2/6 两档） |
| team apply 声明式配置 | 一个 YAML/JSON 把工作区收敛到期望态：字段级 diff、重复执行打印 `No changes.`、密钥只认 `{env: NAME}` 占位（内联写密钥直接拒绝）、`--check` 发现变更退 6 | `agents/*.json` 手工改，三台实例没有收敛工具 | 记下不抄（三台规模手工可控；工具化等实例多了再说） |
| decision model 的 fail-open | 决策模型挂了、超时、答非所选，一律回退到没有它时的行为，**绝不阻塞主流程**；日志不含消息正文只有状态哈希 | `intake`/`digest`/`broadcast` 的失败路径已是这个形状（写不进就退默认路径、busy 本轮不做） | 已是现状，确认即可 |

来源：[docs/mcp-server.md](https://github.com/milind-soni/OpenMausBot/blob/main/docs/mcp-server.md)、[docs/headless-cli.md](https://github.com/milind-soni/OpenMausBot/blob/main/docs/headless-cli.md)、[docs/decision-model.md](https://github.com/milind-soni/OpenMausBot/blob/main/docs/decision-model.md)。

## 第四种入口：本机操作者

前三家案例都在回答「外部访客怎么进来」，我们的结论一直是「这台机器没有能对公网开放的端口，只进不出」。OpenMausBot 的 MCP server 提供了另一条思路：**有一个入口不需要端口**——stdio 是父子进程管道，MCP 客户端（TeleAgent、Claude Desktop 这类）把 server 当子进程拉起，请求响应走管道，不经网络、不对公网。mimi-agent 的物理限制挡住的是「监听端口」，从来不是「本机进程间通信」。

这也补了一个真实缺口：runbook 里「不要做的事」有一条「不要为了制造 `logs/events.jsonl` 里的一行去群里 @ 机器人」——本机程序想跟机器人交互，目前只能冒充群成员说话。MCP 控制面给出一条不进群、不碰飞书、不碰模型的读通道。

它的安全边界值得整段抄（原文口径）："The v1 server intentionally cannot approve requests, remember permission grants, delete data, import teams, change credentials, or control computer/VM lifecycle. Those actions stay in the human-facing app."——**v1 故意不能**。不是「还没来得及做」，是设计上留在人这边。

## 本轮落了什么

### 一、`mcp_server.py`：只读三件套（默认关）

stdio MCP server，纯标准库，独立进程，只读实例目录里的文件，`agentbot.py` 一个字节不改。**默认关的形状比接待桥更彻底：配置里没有它的任何键，主程序不 import 它**——不写运行命令就不存在。

- `get_status`：版本（重读 `VERSION`，与 `feature_switch.product_version()` 同口径）、心跳年龄（与 `checks/verify_deploy.py` 的 `heartbeat_info` 同口径：读 `state/heartbeat` 的 epoch 秒）、接待桥开关与账目。
- `list_leads`：待审意向段落，最新的在前，`limit`（≤50）/`offset` 分页。
- `search_leads`：关键词搜索（大小写不敏感），封顶 100 段（OpenMausBot 的 `search_messages` 同款封顶）。

照抄的安全细节，一条条列：

| OpenMausBot 的做法 | 我们落成了什么 |
|---|---|
| v1 不暴露审批、删除、改凭据 | 三个工具全是只读；`send_message` 之类名字根本不在清单里，调了回一张 isError 卡 |
| 转录分页封顶、搜索封顶 | `list_leads` ≤50、`search_leads` ≤100 |
| schema 拒绝未知字段与坏值 | `_validate` 在门口拒：未知键、缺必填、类型不对（含布尔冒充整数）、超长、越界 |
| 密钥永不进输出 | 配置只取 `base_dir`/`redact_file`/`intake.out_file` 几个键；输出统一过 `guard.redact`（名单 + 手机号/密钥样子的正则）再加 `guard.neutralize` |
| 坏输入不带走进程 | 坏 JSON 行回 -32700 继续跑；未知方法 -32601；工具内部意外回 -32603 循环不死 |

两个「同一把尺」的复用是有意的：实例根公式与 `agentbot.py` 同款（`base_dir` 优先，否则配置文件所在目录——目录口径必须和主程序一致，否则读到的 state 就不是同一套）；待审文件位置用 `intake._out_file` + `guard.safe_path`（认不认得出，必须和 intake 自己落盘时同一把尺）。借私有函数在这里是故意的，代码里有注释说明。

待审文件里的内容是访客写的，出这个进程的每个字节都当成出站正文看待：写盘时已经过一遍打码，读出时再过一遍——防两件事：`redact.txt` 后来加了名字，以及有人手工往文件里贴过没打码的原文。`seen_total` 只报「拉到过的累计数」，不编一个「待审还剩几条」——发没发由人决定，文件里没有那笔账。

### 二、guard 补洞：`<<TOOL:name>>` 冒号形式

[多入口对照与方案.md](多入口对照与方案.md) 的失败模式表里唯一还开着的一格：`guard._MARK` 只认 `<<tool>>`，不认带冒号的近亲 `<<TOOL:docs_read>>`（官网 `[[FARM:...]]` 那种带参标记的形状），中文输入法的全角冒号 `＜＜tool：xxx＞＞` 同样漏。这一轮按先红后绿补上：`_MARK` 扩出可选的冒号参数段（`[^<>]{0,120}?`，参数整个剥掉只留工具名，占位符仍是 `〈TOOL〉` 不变），`_fold_mark` 补全角冒号折叠。先红：探针里 `<<TOOL:docs_read>>` 原样漏过；后绿：中和成 `〈TOOL〉`，全角形式同样，正常文本里的 `1:2` 不误伤，原有用例全数照过。

### 三、测试与读数

- `tests/test_mcp_server.py`：22 条，全走真子进程 stdio（管道行为本身就是被测对象）。握手回显协议版本、清单只含三件套、分页与倒序、脱敏与存量标记中和、人工抬头行不算段、账本数口径、六种坏参数拒绝、未知工具/方法、坏行不死、配置读不到退出码 2。
- 外层闸里 guard 那格加一条冒号用例；mcp 子模块挂进整套（像 `test_intake_notify.py` 一样一格 1 条）。
- 读数（2026-11-08）：`checks/lint.py` ok（87 个 Python 文件）；`tests/run_tests.py` 两种编码各整跑一遍，UTF-8 `475/475 passed` 退 0、cp936 `475/475 passed` 退 0，均落盘。**分母 466 → 475 的口径**：473（基线）+ guard 冒号 1 条（闸自己的 check）+ mcp 子模块 1 条 = 475，与基线 worktree 现跑的 473 对得上。本日第一趟无落盘读数显示 466，未复盘成案；其后两趟干净读数一致且与结构推算精确吻合，按 475 记。

## 记下不做，和为什么

1. **team apply 声明式收敛**：价值随实例数涨，三台手工可控；等哪天「谁负责在什么时候把它拉上来」那张表超过一屏，再回头抄（`--check` 退 6 那个形状最值得先抄）。
2. **verify_deploy 退出码枚举化**：现值 0/1 够用；若外部调度（CI 之外的看门狗脚本）开始按退出码分支，先补 2（参数错）和 6（有变更）两档。
3. **decision model（多 bot 自动路由）**：单 bot 群聊没有「谁来答」的问题，整条不适用；它的 fail-open 与「日志不含正文只有哈希」两件事我们已有。

## v0.12.0 之后还欠什么

- **线上升级**：本仓库这些改动要进实例，走的仍是 [runbook-升级与回滚.md](runbook-升级与回滚.md) 四步（前置核对 → 取代码并验收 → 放锁平滑重启 → 复核并释放锁），需要一个允许重启的窗口，由主人点头。mimi 这台停在 10-28 的 `49856d2`，仍是最该拉上来的一台。
- **MCP server 的接线**：项目级示例在 [本地控制面.md](本地控制面.md)（仓库根 `.cursor/mcp.json`，`command` 用本机 Python，`args` 为 `mcp_server.py` 加 `agents/<name>.json`，`cwd` 为仓库根，不写 secret、不写 `env`）。v2 若加写入类工具，先抄 OpenMausBot 的配对码 + 可撤销会话那一套，并重新过安全审查——这一版没有任何写入，也就不需要任何凭据。
- **官网三件 patch**：与本案无关，仍在等丽丽审（见 [多入口对照与方案.md](多入口对照与方案.md) 链路验收矩阵）。

> AI生成
