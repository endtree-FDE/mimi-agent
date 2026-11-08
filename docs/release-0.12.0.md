# v0.12.0 发布说明

版本号是仓库根目录的 `VERSION`：`0.12.0`。发布日期是 2026-11-08。正文不写密钥、群号、open_id、客户名或个人电脑路径。

这一版相对 [v0.11.0](release-0.11.0.md)（`453195f`）。

## 这一版加了什么

旧的 `agents/*.json` 不改也能接着跑。两样新东西都默认关着：不写运行命令、不写配置段，行为就和 0.11.0 一模一样。

- **本地控制面 `mcp_server.py`（默认关，只读）**。给本机的 MCP 客户端（TeleAgent、Claude Desktop 这类）的一条只读通道：客户端把它当子进程拉起，stdin/stdout 逐行 JSON-RPC——不监听端口、不经网络、不发消息，`agentbot.py` 一个字节不改，主程序甚至不知道它存在。三个工具：`get_status` 查版本、心跳年龄和接待桥账目；`list_leads` 翻待审合作意向（最新在前，一页最多 50 段）；`search_leads` 搜关键词（最多 100 段）。边界照抄 OpenMausBot v1 控制面的口径：**故意不能**审批、发送、改配置、删除，密钥永不进输出；参数在门口校验（未知字段、缺必填、类型不对、越界都拒），坏行、未知方法、内部意外都变成一张错误卡，进程不死。待审文件是访客写的内容，出进程前统一再过一遍脱敏与标记中和。为什么做这一条：这台机器没有能对公网开放的端口，但 stdio 是父子进程管道，不需要端口——本机程序想看机器人状态，从此不用进群 @ 它。见 [OpenMausBot对照与升级方案](OpenMausBot对照与升级方案.md)。
- **意向待看提醒 `intake.notify`（默认关）**。接待桥的下一跳：`intake/leads.md` 攒了新东西时私聊主人一条带确认码的提醒，本人回「发意向 123456」才进群、回「不发意向 123456」只记账；一条都没发出去时照实说、留在待看里换码再提醒，不把账记成已处理。见 [agents/CONFIG.md](../agents/CONFIG.md) 的「待看提醒 intake.notify」。
- **文档三份**：[OpenMausBot对照与升级方案](OpenMausBot对照与升级方案.md)（第四个成熟案例的调研与本版取舍）；[多入口对照与方案](多入口对照与方案.md) 长出链路验收矩阵与既有入口对照；[对外口径](对外口径.md) 升到 `voice-v2`（`[[LEAD]]` 交接标记与意向卡片的规矩）。

安全口径沿用现有的那把尺，这一版没有新开口子：控制面没有任何写入口和凭据，读到的每个字节出进程前都当出站正文过脱敏；guard 的标记中和补上带冒号的伪造形状。

## 修了什么

- `guard.neutralize`：`<<TOOL:docs_read>>`（含全角冒号形式）原来会原样漏出去，现在中和成 `〈TOOL〉`，正常文本里的 `1:2` 不误伤。
- 意向提醒发送失败可见：连续次数、日志一行、`/状态` 一句，发成功归零。
- 停机收尾先等接收进程落定、再等 stderr 抽干，正常收尾不再可能撞 `Fatal Python error` 被看门狗读成崩溃。
- 测试闸的守卫：53 处子进程调用超时不再抛穿整套汇总（工程内务）。

## 从 0.11.0 换上

一个实例一个实例地换，另外几个保持运行。看门狗大约每 3 分钟看一次心跳，升级期间放锁，不用停那条计划任务。

```powershell
# 1 先确认这台现在是好的（只读）
python checks\verify_deploy.py --base . -c agents\<名字>.json --no-doctor
# 2 取代码，只接受快进；然后跑离线测试
git fetch origin --tags
git reset --keep v0.12.0
python tests\run_tests.py
# 3 放锁，平滑重启
. scripts\botproc.ps1; Set-DeployLock (Get-Location) 1200 'upgrade-0.12.0'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\reload.ps1 -Config agents\<名字>.json
# 4 复核，通过就释放锁
python checks\verify_deploy.py --base . -c agents\<名字>.json
. scripts\botproc.ps1; Clear-DeployLock (Get-Location)
```

`git reset --keep` 留下配置、`state`、`kb`、`memory`、`redact.txt` 和 `logs`。不要用 `git reset --hard`，也不要 `git clean`。第 4 步看 JSON 里的 `status` 是不是 `PASS`、`topology.serving` 是不是 1；`warns` 条数不固定，别拿它当闸门。顺序和停手判据见 [runbook-升级与回滚](runbook-升级与回滚.md)。

换上之后**先别开**接待桥与意向提醒，理由和 0.11.0 一样：官网那根管子两头还没接通（端点、KV 绑定、secret），`--check` 会把不会拉的原因一行行说出来。本地控制面想用时，在 MCP 客户端配置里加一段（`command: python`、`args: [mcp_server.py, agents\<名字>.json]`）就行；不用它就什么都不用做。

## 退回 0.11.0

退回目标是 `v0.11.0`。回滚比重启更危险：先停看门狗那条计划任务，再动代码，失败时让它留在停用状态。

```powershell
python checks\verify_deploy.py --base . -c agents\<名字>.json --no-doctor
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop.ps1
git reset --keep v0.11.0
python agentbot.py agents\<名字>.json --check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1 -Config agents\<名字>.json
python checks\verify_deploy.py --base . -c agents\<名字>.json
```

`mcp_server.py` 退回后不存在了，MCP 客户端那段配置删掉即可；`intake/` 目录和 `state/intake_state.json` 留着不碍事。

## 还没做

- **官网侧没落地**：三份可审 patch（`functions/api/chat.ts` 的口径与 `[[LEAD]]`、新建 `functions/api/leads.ts`、浏览器侧 `mimi-core.js` / `mimi-lead.js` 与 `MimiChat.astro` 接线）没贴没部署，Pages 的 KV 绑定 `LEADS` 和 secret `LEAD_TOKEN` 没建。贴与不贴归官网仓库的主人；缺件时拉取端点回 501，聊天不受影响。
- **接待桥与意向提醒在任何一台线上机器上都没开**：发版不是上线。哪台什么时候拉上来、谁负责，写在 [runbook-升级与回滚](runbook-升级与回滚.md) 的版本对齐一节。
- **本地控制面是 v1**：故意没有写入类工具。哪天要加，先做配对码与可撤销会话，再重新过安全审查。
- 分支保护里四个必需检查上下文的名字带 `CI / ` 前缀，与 Actions 报的 check-run 名字对不上，PR 的合并按钮因此按不动；合并沿用 `--admin`（#89、#92 先例）。要长期修是仓库共享配置，没点头没动。

## English

`VERSION` is `0.12.0`, released on 2026-11-08. Existing config files keep working unchanged; both new features are off until you opt in.

New: a read-only local control plane (`mcp_server.py`, launched by an MCP client as a child process speaking stdio JSON-RPC — no port, no network, no messages; three tools: status, list pending leads, search leads; deliberately cannot approve, send, change config or delete anything; secrets never appear in output; every byte leaving the process is redacted like outbound text); a lead-review reminder (`intake.notify`, two switches deep) that pings the owner in private chat with a confirmation code — leads enter a group only after the owner replies with the code in that same chat, and a failed send is reported honestly and retried with a fresh code; and three documentation additions (the OpenMausBot case study, the multi-entry acceptance matrix, and voice-v2 of the shared wording).

Fixed: `guard.neutralize` now also neutralizes colon-form fake tool markers (`<<TOOL:name>>`, full-width colons included); lead-reminder send failures are visible (counter, log line, a `/status` note); shutdown drains the receiver's stderr before exit so a clean stop can no longer crash; the test harness guards all 53 subprocess calls so a timeout can no longer swallow the whole summary.

Not in this release: the website-side patch remains unapplied (KV binding and secret unbuilt), no live instance runs the intake bridge yet, and the control plane is v1 — no write tools by design.

> AI生成
