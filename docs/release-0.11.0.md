# v0.11.0 发布说明

版本号是仓库根目录的 `VERSION`：`0.11.0`。发布日期是 2026-11-05。正文不写密钥、群号、open_id、客户名或个人电脑路径。

这一版相对 [v0.10.0](release-0.10.0.md)（`bb7361a`）。

## 这一版加了什么

旧的 `agents/*.json` 不改也能接着跑。新加的接待桥默认关着，不写那一段就和 0.10.0 一样——不拉取、不建目录、`/状态` 也不多那一行。

- **接待桥 `intake`（默认关，只进不出）**。方向和播报相反：播报把人写好的正文发进群，接待桥把外面的东西收进本机一个文件，自己一条消息都不发。到点从配置里那**一个**公网 HTTPS 端点拉访客留下的合作意向（想做什么形式、大概什么时候要、需求小结），按编号去重，追加写进 `intake/leads.md`。要进群得人挑几行复制进 `broadcast/pending.txt`，次日走现成的播报 `body_file`。它不调模型、不读日历、不写飞书。见 [agents/CONFIG.md](../agents/CONFIG.md) 的「接待桥 intake」和 [多入口对照与方案](多入口对照与方案.md)。
- **对外口径第一次只有一份**：[对外口径](对外口径.md)（`voice-v1`）。官网浮层里那个 Mimi 和飞书群里这个 Mimi，以前各写一套口吻、作品清单和保密规矩，已经漂过一次（官网提示词里的开源模板地址还写着改名前的仓库名）。这一版把那套口径抽成仓库里版本化的一份：能介绍哪些作品和路径、口吻与风格锚、保密期作品不复述名字、不报价不承诺档期、成员身份不介绍、`[[COOP]]` 怎么交接。这一版是**人复制引用**，不是运行时抓取——为什么不做成抓取，那一页写了。
- **多入口的对照调研进仓库**：[多入口对照与方案](多入口对照与方案.md)。LangBot（嵌入脚本 + WebSocket + 可选 Turnstile + 连接数上限回 429；HTTP Bot 的 HMAC 签名、202 立即返回、回调地址只从配置读）、AstrBot（适配器只要 `run()`/`meta()`，`webchat` 不自建服务、复用 WebUI 的 FastAPI 走 SSE，会话键 `platform_id:message_type:session_id`）、NoneBot2（Forward/Reverse driver 加 Mixin，服务端 driver 只能有一个）三家怎么做「一个核心 + 多个入口」，对照我们已有的 `channels/` 能力清单和 `p2p_limited` 访客档，列出缺的四样，逐条写清对外入口会怎么坏、现在谁在守。结论三条：不并进程、先并口径、只开一条只进不出的桥。

安全口径沿用现有的那把尺，接待桥没有新开口子：地址内网、带账号密码、URL 里带密钥参数的都拒；钥匙只在配置里写**环境变量名**，配置里不出现它的值，变量空了记 `no_token` 不去拉，值里带换行或控制字符按请求头注入在拼包之前就拒、一个连接都不建；真连之前还要两次 DNS 解析结果一致且都不是内网。拉取最长等 20 秒，所以拿锁分两段，网络等待不占着播报那把五秒的锁。待审文件在 `.gitignore` 里，不进仓库。演练、`--check` 和 `--doctor` 一个文件都不生成，42 条回归测试用假发送落点证明过「只落盘、不发东西」。

## 修了什么

这一版没有面向访客的行为修复。工程内务有一条：`--check` 的回归测试不再拿它的退出码当判据——裸机上没装 lark-cli 时自检本来就以 1 退出，那和接待桥没关系，改成只判接待桥自己那几行。这条在 CI 上把三个 job 判红过，现在绿。

## 从 0.10.0 换上

一个实例一个实例地换，另外几个保持运行。看门狗大约每 3 分钟看一次心跳，升级期间可以放锁，不用停那条计划任务。

```powershell
# 1 先确认这台现在是好的（只读）
python checks\verify_deploy.py --base . -c agents\<名字>.json --no-doctor
# 2 取代码，只接受快进；然后跑离线测试
git fetch origin --tags
git reset --keep v0.11.0
python tests\run_tests.py
# 3 放锁，平滑重启
. scripts\botproc.ps1; Set-DeployLock (Get-Location) 1200 'upgrade-0.11.0'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\reload.ps1 -Config agents\<名字>.json
# 4 复核，通过就释放锁
python checks\verify_deploy.py --base . -c agents\<名字>.json
. scripts\botproc.ps1; Clear-DeployLock (Get-Location)
```

`git reset --keep` 留下配置、`state`、`kb`、`memory`、`redact.txt` 和 `logs`。不要用 `git reset --hard`，也不要 `git clean`。第 4 步看 JSON 里的 `status` 是不是 `PASS`、`topology.serving` 是不是 1；`warns` 条数不固定，别拿它当闸门。顺序和停手判据见 [runbook-升级与回滚](runbook-升级与回滚.md)。

换上之后**先别开**接待桥。开它的前提是那根管子两头都在：官网侧 `/api/lead` 那个端点真的存在并且能读，Pages 项目里 KV 绑定和 `LEAD_TOKEN` 那个 secret 已经建好，机器人这边的环境变量也已经设。三样少任何一样，`--check` 会把不会拉、不会写的原因一行行说出来——那就是你想要的状态。测试写法：先在只有 `enabled` 的假配置上跑 `python agentbot.py agents\<名字>.json --check`，确认它报的是「url 不是可连的公网 http(s) 地址」而不是别的。

## 退回 0.10.0

退回目标是 `v0.10.0`（`bb7361a`）。回滚比重启更危险：先停看门狗，再动代码，失败时让它留在停用状态。

```powershell
python checks\verify_deploy.py --base . -c agents\<名字>.json --no-doctor
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop.ps1
git reset --keep v0.10.0
python agentbot.py agents\<名字>.json --check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1 -Config agents\<名字>.json
python checks\verify_deploy.py --base . -c agents\<名字>.json
```

`intake/leads.md` 和 `state/intake_state.json` 留着不碍事，0.10.0 不读它们；`.gitignore` 里那两行退回后也留着，不影响任何东西。

## 还没做

- **接待桥在任何一台线上机器上都没运行**。这一版是发版，不是上线；mimi 那台线上实例还停在 2026-10-28 的提交上，落后 main 24 个提交（连 v0.10.0 都不在它上面）。谁负责在什么时候把它拉上来，写在 [runbook-升级与回滚](runbook-升级与回滚.md) 的版本对齐那一节。
- **官网侧没落地**。给 `functions/api/chat.ts` 的可审 patch（口径来源注释、旧仓库名改成 `mimi-agent`、`[[LEAD]]` 的提示词与剥除）和 `/api/lead` 端点草案都在运维副本里，没贴、没提交、没部署。官网那个仓库有另一条工作流正在改同一个文件，贴之前必须重跑一次 `git apply --check`。
- **口径还是人复制引用，不是机器引用**。官网构建时抓不到这个私有仓库，运行时抓又会让访客看到的口吻跟着仓库漂移。前置条件写在 [对外口径](对外口径.md) 的「下一步」。
- **不做入站**。接待桥是拉的，不是被推的。真要做浏览器能连进来的入口，顺序和理由在 [多入口对照与方案](多入口对照与方案.md) 的最后一条建议里：先在 `channels/` 加一个默认关的适配器，不在 `agentbot.py` 里加 `if http:` 分支。
- 一个已知没补的清洗缺口：`guard` 的工具标记清洗只认小写形状，模型写成 `<<TOOL:name>>` 时不会被中和。这一版没动它，避免顺带改掉播报的行为。

## English

`VERSION` is `0.11.0`, released on 2026-11-05. Existing config files keep working unchanged; the new intake bridge is off until you add its block.

New: `intake` pulls visitor collaboration leads from one public HTTPS endpoint into a local review file (`intake/leads.md`, gitignored) and sends nothing at all — a human copies chosen lines into `broadcast/pending.txt` for the next day. It reuses the existing URL guard (internal addresses, credentials and key-bearing URLs rejected; tokens only ever named as an environment variable; control characters in a header value rejected before any connection; two matching DNS resolutions required before connecting). It takes the lock in two phases so a 20-second fetch never holds the broadcast's 5-second lock. `--dry-run`, `--check` and `--doctor` generate nothing; 42 regression tests prove the file lands and no message goes out. Two new docs: `docs/对外口径.md` (voice-v1) is now the single versioned source for what the bot and the website may say about works, tone, embargo, pricing and the `[[COOP]]` handoff; `docs/多入口对照与方案.md` compares LangBot, AstrBot and NoneBot2 multi-entry designs, lists the four things we lack, and concludes: don't merge runtimes, merge the wording first, and only open a one-way intake bridge.

Housekeeping: regression tests no longer treat `--check`'s exit code as a verdict (a bare runner without lark-cli exits 1 for unrelated reasons).

Not in this release: no live instance runs the bridge yet (release and deployment are separate; the mimi instance is 24 commits behind), and the website-side patch stays unapplied and awaiting review.
