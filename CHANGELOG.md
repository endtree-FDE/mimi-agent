# 变更记录

用户能看到的变化写在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。版本号只以仓库根目录的 `VERSION` 为准。

设置卡片会读取 `VERSION` 来显示版本号。读不到，或不是 `x.y.z` 这种写法时，卡片上就不写版本。删掉 `VERSION` 不影响开关本身。本文件不参与运行。删掉本文件时，机器人的行为与现在相同。

当前 `VERSION` 是 `0.11.0`，发布日期是 2026-11-05。发布说明见 [docs/release-0.11.0.md](docs/release-0.11.0.md)。下面 [Unreleased] 装的是这次发版之后新攒的改动。说明里不要写密钥、群号、open_id 或客户名。

## [Unreleased]

### 添加

- 意向待看提醒 `intake.notify`，默认关，而且比接待桥多一层：`intake.enabled` 和 `intake.notify.enabled` 都要为 `true` 才跑。补的是「到飞书里的人」这一跳：`intake/leads.md` 攒了新东西时，私聊主人一条「官网那边攒了 N 条」，带上这一批的摘要和一个确认码（位数跟着 `confirm.code_digits`，默认 6 位；默认 24 小时有效，用一次作废）。主人在同一条私聊里回「发意向 123456」才发进 `chat_ids` 里那些群，回「不发意向 123456」只记账。别人拿同一个码、本人在群里回、码过期，都只回一句说明，不消耗码；配置的群不属于本实例服务范围时一条都不发，码作废，但那几条仍留在待看里，下一轮换一个新码再提醒；发送接口一条都没认上时也照实回「没发出去」，不把这批记成已处理。每天最多提醒几条、两条之间至少隔多久、一条里最多带几条都能配，都有界。正文走 `outbound.prepare`，先脱敏再去 @所有人，并且留出余量不撞发送接口那 3500 字的硬上限。接待桥本体仍然一个字节都不发——它内部没有发送通路，这条红线有测试写死。见 [agents/CONFIG.md](agents/CONFIG.md) 的「待看提醒 intake.notify」，回归测试在 [tests/test_intake_notify.py](tests/test_intake_notify.py)（37 条）。

### 变更

- [docs/对外口径.md](docs/对外口径.md) 从 `voice-v1` 升到 `voice-v2`：交接标记那一节补上第二条 `[[LEAD]]`。访客把「想做什么形式」和「大概什么时候要」说清、模型也复述过需求小结之后，最后单独一行写 `[[LEAD]]`，官网上会出现一个「把这几句发给团队」的按钮，**访客点了才算提交**，按钮里只带那三件事；`[[COOP]]` 与 `[[LEAD]]` 一条回复只写一个，两个都不需要就一个也别写。口径同时写明：这两个标记都由服务端剥除，永远不进浏览器，飞书侧没有它们的语义——访客留下的意向落到飞书走的是接待桥那条路（站点存、机器人拉、主人回确认码才进群）。还写明了那张卡片自己的规矩：三格只搬模型复述里带标签的原文、认不到就留空，访客能改，点一下才发、一次点击只发一次，送失败要说明白并允许再点——「不替谁编」这件事原来只写在提示词那一侧，页面这一侧没写。README 的口径版本行跟着改成 `voice-v2`。官网那侧要同步的是四处（提示词、`functions/api/leads.ts`、浏览器侧协议、浮层那张卡片），可审 patch 已随这一版重新生成；**patch 还没贴也没部署，所以在贴齐之前 `voice-v2` 的这一跳只在这份文档里成立**。
- [docs/多入口对照与方案.md](docs/多入口对照与方案.md) 加了一张链路验收矩阵：访客留意向 → 站点存下来 → 机器人拉取 → 私聊提醒 → 确认后进群，每跳写清「看什么算通、现在通到哪、缺谁点头」，并写明两处不在代码里的前置（线上实例还没升，Pages 的 KV 与 secret 只能由有权限的人建）。矩阵第 5 跳原来那句「正文已脱敏」写得太粗，像是每条进群前都会打码；按代码数过实际是两层——带客户名或手机号的在 `intake.normalize` 就整条丢掉（不落待看文件、也就进不了群），`render_body` 里的 `guard.redact` 只是第二层兜底，两层各有一条 `tests/test_intake.py` 钉着；这一版把那行改成两层都写清。同一页另加一张「既有入口对照」：飞书群/私聊对话、`digest`、`broadcast`、`report`、官网对话、`[[COOP]]`、接待桥七行，各写「看什么算通 / 现在 / 缺谁点头」，数字是 2026-11-05 06:01-06:04 当场读的（读配置只取开关，群号与 open_id 没看也没写进文档）——两台的 `bot.pid` 里 PID 都在任务列表里、`digest` 两台都关、`broadcast` 只有 mimi 开且待审文件有 25 行、`report` 两台都开且实现其实在 `usage.py` 而不是同名的 `report.py`（三台都没有那个文件，按文件名找会找空）、`intake`/`intake_notify` 三台都没有这两个文件。官网对话与 `[[COOP]]` 两行明确写「这次没验 / 归丽丽」，不据未验的事下结论。**这一节在同一个早上又被自己纠正了一次**（10:51）：初稿那七行是按记忆列的，漏了 `alerts` 这条——它恰恰是唯一一条线上已经在跑的「没人说话也自己往外发的私聊」。改法是先把代码里所有 `enabled` 开关键数出来（`census_entries.py`：脚本按同行匹配打出 16 行，其中 `text` / `enabled` 是同一行里别的键撞上正则的假阳性、`agent` 那行其实是嵌套键 `agent.crew`，真顶层键 13 个；跨行的 `write` 和 `intake` 靠翻 `agentbot.py` 与 `intake.py:34` 手工补上，合起来 15 个顶层键 + 2 个嵌套键 `agent.crew` / `memory.growth`），再分成「自己往外发」和「回复里的能力」两类。**同一把尺又捞出第二条漏的**：`memory.growth`（记忆成长提案，`agentbot.py:2374` 定时 tick 里带 `_outbound_send`，`deliver` 默认 `p2p`）——它和这次新加的接待桥是同一形状，三台线上却都只开了 `memory.enabled`、`growth.enabled` 根本没写，所以是关着的。补进来的 `alerts` 一行带了不好听的数：两台线上都 `alerts.enabled=true`，日志里 mimi 58 行、幕幕 72 行，首行 2026-10-20，也就是这半个月反复在发；但送达和 ÷ 目标和 = mimi `down` 15/25、`recover` 23/25、`remind` 1/8，幕幕 `down` 18/62、`recover` 31/66、`remind` 1/16——私聊在线上经常没送达，失败只落在那一行日志里。这条对本次改动的意义写进了那一行：`intake_notify` 用同一个 sender 形状，所以它把「一条没认上」当失败、留在待看里换个码再提醒，不照 `alerts` 那样只写日志。同一趟还发现 `broadcast/pending.txt` 是活文件（06:01 数 25 行、10:51 数 13 行，mtime 09:03），文档里的行数都标上读数时刻。**同一趟还重测了官网的底**：矩阵和说明里原先写「三份 patch 在她 `ac22187` + 那 11 个未提交文件的工作树上验过」，10:58 去数时发现丽丽自己又提交了几个 commit——站点本地 HEAD 到了 `24e8bff`（比 `origin/main` 领先 3）、未提交只剩 3 个（`ChickenFarm.astro` / `coop/coop.js` / `coop/pack.json`，和这三份 patch 改的文件不重叠）。在她当前工作树上逐条 `git apply --check`（只读，退出码一条条抓，不再拿管道尾巴冒充）三份各自 rc=0、叠贴 rc=0；顺带写明那份留着对读的旧 `chat.patch` 已被 `bridge-20261105.patch` 覆盖，**别和第一份一起贴**。**17 分钟后这个底又换了一次**（11:15 再更正）：丽丽把那 3 个未提交文件自己提交成 `1ca55e6`，工作树当场干净（`git status --porcelain` 0 行），本地 HEAD 从 `24e8bff` 走到 `1ca55e6`、比 GitHub 的 `origin/main`（`740c58b`）领先 4；`git merge-base --is-ancestor 740c58b 24e8bff` 退 0 说明她本地 `main` 已包住上游那份，所以 patch 在她本地 `main` 上验过就等于在 GitHub 内容上验过。新底上重跑：三份各自 rc=0、旧 `chat.patch` rc=0、叠贴 rc=0，另外从一个跑完即删的只读临时克隆里对她本地 `main` 也验了一遍同样 rc=0，没碰她的工作树。这一页因此把话改口：给丽丽的东西不引用这里的读数，让她自己现跑一次 `git apply --check`。同一时刻（11:14）离线整链又跑了一次：`run_all.py` 十三步一次过并打 `ALL_SITE_CHECKS_OK`（叠贴与逐字节比对 rc=0、口径对读 SAME、`takeVisible` 12/12、协议层 17 条 FAIL 0 且底稿那条 FAIL 16 才算对、假 DOM 卡片 27/27、真 socket 15/15、第 3-5 跳 `pull=polled blocks=1 notify=notified`、第 1→5 跳同一份数据 9/9、反向闸 `0 处认错`），矩阵开头因此记了「最近一次整链重跑」的时刻和这套数，`tests/run_tests.py` 471/471 在 UTF-8 与 cp936 两种编码下都过。官网侧那一份现在写清是四份改动、五个文件、三个 patch：服务端 `chat.ts` + 新建 `leads.ts`，浏览器侧协议 `src/scripts/mimi-core.js`，和 03:59 补的按钮本体——新建 `src/scripts/mimi-lead.js` 加 `MimiChat.astro` 的 5 处接线。少第一份的话 `lead: true` 没人读，`[[LEAD]]` 会以方括号裸字出现在页面上；少第三份的话页面知道有这条意向，但那个按钮根本没人生出来。三份都在站点当时的提交（`ac22187`）和它主人当时那 11 个未提交文件的工作树上只读验过 `git apply --check`，叠着贴也不冲突——这个底 10:58 重测时已经换过一次，见上面那段；第 1 跳另外补了一条真 socket 的端到端（打过 patch 的卡片用真 `fetch` POST 进编译出的 `onRequest`，再带 Bearer 取回，15/15），并把它的取回结果当输入喂进接待桥，第 1→5 跳用同一份数据串完一次（`check_socket.py` 9/9：访客填的三样落到待看文件、小结进确认后那条正文、别人回码被拒、这批确认后不再留待看）；**这一版另记一笔自己发现的坑**：那 9 条一开始判不出假——e2e 那三格抄了另一批探针的措辞，所以拿 socket 那条去比假输入那批照样比中，等于白比。改成两边各用互不包含的措辞，并加一道双向反向闸（`chain/negative_check.py`，六格全判不出才退 0；`run_all.py` 从 9 步变 13 步，把它和现场重造的假输入料一起跑）；一个都没贴、没提交、没部署。
- [docs/多入口对照与方案.md](docs/多入口对照与方案.md) 的 `alerts` 那一行又添了一条当天下午的只读实测（12:44 看日志，同样没发消息、没碰进程）：两台当天各两对 `down / recover`，09:55-09:56 一对（约 3 分钟）、12:05 一对，而 12:05 那条 `down` 正文自己写着「中断了大约 33 分钟」、5 秒后就 `recover`——真实中断是 11:32 前后开始，到下一个检查点才被记下，**主人看到私聊时事情已经结束了**，这条路的短板不只是送不送得到，还有「晚半小时」。两台一起抖、一起回，更像机器级或本地代理级的网络停顿，不是单只 bot。幕幕这两条仍是 `feishu=1/2`（两个主人只送到一个），mimi `1/1`。这一条反过来照到自己身上：`intake_notify` 用同一个 sender 形状，cadence 和「没认上就留在待看里换码再提醒」是对着这个坑设计的，但它自己的最坏延迟**线上从没实测过**，因为线上还没装这两个文件，只能归「代码就绪、线上未落地」。同一趟也记下自己的嫌疑：11:26 起我在本机整串重跑离线测试（会起真 subprocess），12:05 那对告警落在这段里——时间重合，没证据说是我跑出来的，也不能断言一定无关，以后盯线上健康的那段时间避开整串重跑。
- **闸自己坏过一次，记在这儿**：这一轮 cp936 那一趟跑了 39 分钟（正常约 10 分钟）后在 `tests/run_tests.py:37` 那条 `timeout=240` 上抛了未捕获的 `subprocess.TimeoutExpired`，整个套件直接中止、连「N/N passed」那行都没打出来，退出码 1。当时它不算代码问题也不能就这么放过：同一份树单独重跑 cp936（12:44 起，10 分钟）`471/471 passed` 且 rc=0，UTF-8 那趟 11:26 也是 471/471、rc=0，所以判为机器被拖慢时那条 240 秒上限被撞穿。**但这个闸的形状是脆的**——任何一条 subprocess 慢过 240 秒都会让整串测试没有汇总、只能靠 traceback 猜挂在哪。这一版没改它：改它得先写一条能把「单条超时不该吞掉整套汇总」按住的失败测试（本仓库的规矩是先红后绿），而手头这一轮全是文档改动，不混在一起。
- [docs/确认方式.md](docs/确认方式.md) 补一段：除「确认 NNNN」之外，另有两处用各自的话回码（「确认记忆 / 驳回记忆」、「发意向 / 不发意向」），规矩和位数与原来一致。
- 上一版之后由别人合进来的两项，记在这里补上账：新增 [AGENTS.md](AGENTS.md)（agent 进入仓库时的说明书）和 [renovate.json](renovate.json)（依赖机器人配置对齐样板间）。都不影响运行。
- [docs/多入口对照与方案.md](docs/多入口对照与方案.md) 的第 2 跳和「两个已知的前置」那一段，13:10 被自己收窄了一次。原先那句「KV/secret 只能由有权限的人建」读起来像「不先建好绑定就不能把 patch 交出去」，而这一点当时只是读代码推的，没实测。现在补了一条只跑的探针（`v3-upgrade-work/site-bridge-20261105/chain/no_kv.mjs`，记录 `no-kv-check.txt`，12/12）：把打过 patch 的 `leads.ts` 转译产物，在 `env` 全空、只给 `LEAD_TOKEN`、只给 `LEADS` 三种缺件组合下各打一遍 `onRequest`，六种情况**一个抛出的都没有**——提交回 `501 {"error":"storage"}`、拉取回 `501 no_token`，缺件那几跑一条也没落进内存 store；同一份代码两样配齐则 `202` + `200` 取回那条。所以顺序可以是「先贴代码、后建绑定」，中间那段聊天照常，只有那个按钮拿到 501。矩阵那一格和前置那一段都按这个改口：绑定是「这一跳通起来」的前置，不是「把代码交出去」的前置。这一步同时进了 `run_all.py`，整链从十三步变十四步（13:10 一次过、`ALL_SITE_CHECKS_OK`），文档里「最近一次整链重跑」的读数和步数一并换了，11:14 那次十三步的数留在原处当上一次的记录。丽丽那一页（`说明.md`）同步改了：除了这条，还更正了它「那个仓库正有 11 个未提交文件」——那是今天更早的读数，她已把剩下的提交成 `1ca55e6`、工作树干净。
- [docs/多入口对照与方案.md](docs/多入口对照与方案.md) 那一节从「两个已知的前置」添成**三个**（13:32）。第三条是这一轮代码怎么落进 `main` 这件事本身：PR #89 在四条必需检查全绿（ubuntu/windows 的 `test`、`secret scan`、`Windows PowerShell 5.1`，两个 suite 各一份）的情况下，`gh pr merge 89 --merge` 仍回「the base branch policy prohibits the merge」，`mergeable_state` = `blocked`。读过的配置里能排除的都排除了——不是草稿、不要审批（`required_approving_review_count: 0`、`require_code_owner_reviews: false`、`reviewDecision` 空）、不要签名（`required_signatures.enabled: false`）、没有 ruleset、分支不落后（PR base `63b7cd0` 就是 `origin/main` 当前值）。一度怀疑是 `cursor` / `trae-ai-cn` / `sentry` / `renovate` 那四个第三方 check suite 一直挂在 `queued`，**这条被自己的对照否掉了**：`origin/main` 自己头上和昨夜顺利合进去的 #87 头上也挂着同样那四个 queued，queued 不是原因，怀疑作废。剩下的事实是：今天 02:53 之后落到 `main` 的九个提交都是非 merge 的直线提交（`enforce_admins` 关着，管理员推得动 `main`，PR 那个按钮反而按不动）。往下只有两种走法，看一眼仓库设置里的禁用原因，或者授权按同一把尺直接推 `main`——两条都不是我一个人该替主人定的，所以只把话写进文档，不动手。同一节第一条也跟着换了读数：`git fetch` 后 `git rev-list --count 49856d2..origin/main` = **42**（05:31 那次数的 41 是 main 还在 `7c7de83` 时的），并且把原先那句「这一轮提交贴上去之后还会再 +1」改口——这一轮全在 `docs/entry-census` 上，`main` 没动，落不进去就还是 42。矩阵第 4 跳另外补了一个能从代码算出来的数：`maintenance_tick` 约 15 秒一转（`agentbot.py:2268`），但拉取自己有 `interval_min`（默认 30 分钟、下限 15，`intake.py:12`/`intake.py:219`），提醒另有 `min_gap_min`（默认 60 分钟、下限 5，`intake_notify.py:70`/`intake_notify.py:300`），所以「访客留下 → 主人收到私聊」最坏默认约 90 分钟、调到下限也要 20 分钟。上一条那段说「`intake_notify` 自己的最坏延迟线上从没实测过」仍然成立——**这次是算出来的，不是量过的**，量它得先把这两个文件装进某个实例。
- [docs/多入口对照与方案.md](docs/多入口对照与方案.md) 矩阵上方那句「最近一次整链重跑」的读数换到 **13:51**（十四步一次过、`ALL_SITE_CHECKS_OK`，记录 `runall-wait.log`：这一趟是 13:35:54 起的两种编码仓库测试落定之后自动接跑的；仓库侧两边仍 `471/471 passed` 退 0，接待桥那一格 `43/43`），第 1 跳那一格补了一条 13:48 的实测。这条是因为发现一个真会踩的坑：丽丽那三份 patch 一直在她**本地分支尖** `1ca55e6` 上验，可她一旦切回 GitHub 的 `main`（`740c58b`）再贴，底就不一样了——而那 4 个还没推的提交里正好动了 `functions/api/chat.ts` 和 `src/components/MimiChat.astro`，第一、三份 patch 也动这两个文件。做法是从一个跑完即删的临时克隆里 `git checkout 740c58b`（她的工作树一个字没动），逐份 `git apply --check` 三份 rc=0，按 bridge → core → card 叠贴也全 rc=0，贴完 `functions/api/leads.ts` 与参考件 `cmp` 逐字节一致（159 行），还原后 0 个脏文件（底稿 `patch-on-main.txt`）。**结论换成两份底都贴得干净**，她在哪一份上贴都行；但仍然只是「贴得上去」，测试、预览、部署得她自己跑。顺带把前置第三条又核了一遍：PR #89 的 `mergeable` 是 `MERGEABLE`、`mergeStateStatus` 仍是 `BLOCKED`，`headRefOid=ddd5fb7` 确实包住 `origin/main`（`git merge-base --is-ancestor 63b7cd0 ddd5fb7` rc=0，所以 `strict: true` 那条「必须先跟上 main」也排除了）；把 `protection.json` 十个键逐个摊开看过，除了四个必需 check 上下文没有别的限制。合不动的原因还是只能从仓库设置那个按钮的禁用提示看，或者授权直接推 `main`——照旧不动手。
- 上一条里「整链十四步一次过」那句 **13:59 又纠了一次自己**：贴 patch 那步（`v3-upgrade-work/site-bridge-20261105/verify_patches.py`）的临时克隆一直钉在旧底 `ac22187`，而丽丽 11:15 之后又提交了 4 个（现在 `1ca55e6`），其中两个动了 `functions/api/chat.ts` 和 `src/components/MimiChat.astro`——她自己加了 `[[FARM:event]]` 那条标记。也就是说 13:51 那趟虽然照样打 `ALL3_OK`，验的其实是旧底，而「落地后五个文件与我的改后副本逐字节一致」这句判据已经不成立（她新加的那 6 行 / 4 行本来就不在我的副本里）。脚本改了三件事：每次跑之前先 `git fetch` 她仓库的当前 `HEAD` 再把临时克隆 detach 过去（只读她的仓库，工作树一个字没动）；判据拆两道——两个新建文件（`functions/api/leads.ts`、`src/scripts/mimi-lead.js`）仍逐字节比，三个改动文件改验「patch 自己新增的那几行原样在场」；再顺手在她的工作树上只跑 `git apply --check`（不落盘）。13:59 重跑整链仍是十四步 `ALL_SITE_CHECKS_OK`（`runall-1359.txt`）：底报 `1ca55e6`、新建两份 SAME、加行在场 `30/30`+`159/159`+`33/33`+`72/72`+`102/102`（396 行全在场）、她工作树 1 个未提交文件（`src/lib/coop/coop.js`，+92/−55，不在这五份里）三份逐份和叠贴仍 rc=0、还原后 0 个脏文件。**这条是给「仪表不能自己说谎」补的账**：旧的那句已经在文档里挂了几小时，现在按 13:59 的口径改写，旧读数留在原处不当现值用。

### 修复

- **补一条漏账**（13:41 用 `changelog_coverage.py` 对着 48 个提交逐条过了一遍发现的）：`fa85f5b`（11-05 01:52，`fix(ci): 自检用例给子进程造假 lark-cli，修基线红（Fixes #86）`）在 `[Unreleased]` 和 `[0.11.0]` 两节里都找不到。它比发版提交 `453195f`（01:56）早 4 分钟、已经在 0.11.0 那棵树里，是发版切分时漏写的。已经发出去的版本小节不改，这笔账记在 `[Unreleased]` 这儿：那一改的内容是给自检里被当作子进程拉起的 `lark-cli` 造假，让「没有真 lark-cli 也能跑离线自检用例」这条路在 CI 上稳定下来，不影响任何对外行为。
- 接待桥的自检有一句话是假的，13:17 顺着一趟只读探针抓出来：`intake.out_file` 写成绝对路径、盘符或 `..` 时，`settings()` 早就把它换成默认的 `intake/leads.md`，所以 `hints()` 里那句「out_file 认不出来（绝对路径、盘符或 ..）。待审文件不会写。」**永远不会被触发**，而它说的内容还正相反——文件照写，只是写在默认路径。也就是说主人自己配的落盘位置被换掉了，`--check` 一声不吭，这一跳的验收面是虚的。现在改成按事实说：把你原样写的那个路径点出来，并说这一版按默认 `intake/leads.md` 落（`agents/CONFIG.md` 的 `out_file` 那条同步写明「退回不是静默的」）。走的是先红后绿：[tests/test_intake.py](tests/test_intake.py) 新增那条「待审文件路径认不出时要说清按默认落，不能说不写」，加完当场跑是 `42/43 passed`、红的就是它；实现完 `43/43`，[tests/test_intake_notify.py](tests/test_intake_notify.py) 那 37 条没动也仍 `37/37`。这一版之后两种编码又各整跑了一遍（UTF-8 13:26 起、cp936 紧跟其后），两边都是 `471/471 passed` 且退 0——**总数没跟着涨不是漏跑了**：`tests/run_tests.py:3478` 那句汇总是按 `results` 里一条一项算的，而每个子模块的整套用例只作为一个项目记进去（`run_tests.py` 里那一行 `results.append(("接待桥", _ik.returncode == 0))`），所以子模块里加一条测试，动的是它自己那行的 `42→43`，外面的 `471` 一动不动。顺带弄清了另一件：`--check` 那句「url 不是可连的公网 http(s) 地址」是真的会去解析域名的（测试里用 `AGENTBOT_FAKE_DNS` 桩住），手工拿 `https://ok.example.com` 试会得到这句提示——那不是 bug，是我那次没桩 DNS。13:34 又拿真子进程复核了一遍这一跳的验收面（本机临时目录起 `agentbot.py <cfg> --check`，没碰线上、没发消息，记录 `v3-upgrade-work/chk-outfile-real.txt`）：四条 HINT 各说各的事，`out_file` 那条把 `C:/somewhere/else.md` 原样点出来并说按默认 `intake/leads.md` 落，旧的假话「待审文件不会写」在输出里一个字都没有，`base_dir` 下也确实没建 `intake/` 目录（自检既不拉也不写）。

- 机器人停机收尾时可能自己把自己弄崩。收消息那条路每起一个接收进程，就另开一个线程把它的错误输出抽进日志；原来在「不再重启、直接收尾」这条路上没等那个线程，主线程一退、解释器开始收尾，线程随后那笔写入会撞上 stdout 锁，报 `Fatal Python error: _enter_buffered_busy`，进程退出码变成非 0——一次正常收尾被看门狗读成崩溃。windows 上的 CI 真挂过一次（同一份代码本地跑不出来，因为那笔写入慢不过本地机器）。现在收尾那一趟先等接收进程落定、再等这一路 stderr 抽干（各给 2 秒和 5 秒的余量，超了照样走，不把人卡住），并加了一条能把这个竞态按住的回归测试。见 [tests/test_link.py](tests/test_link.py) 的「收尾时等这一路的 stderr 抽干」。

## [0.11.0] - 2026-11-05

发布说明见 [docs/release-0.11.0.md](docs/release-0.11.0.md)。旧的 `agents/*.json` 不改也能接着跑；这一版新加的接待桥 `intake` 默认关着，不写那一段就和 0.10.0 的行为一样。

### 添加

- 接待桥 `intake`，默认关。不写这一段或 `enabled` 不是 `true` 时，不拉取、不建目录、`/状态` 也不多这一行。方向和播报相反：只收不发。到点从配置里那一个公网 HTTPS 端点拉「合作意向」（访客想做什么形式、大概什么时候要、需求小结），按编号去重，追加写进本机的 `intake/leads.md`。它不调模型、不读日历、不写飞书，一条消息都不发；要进群得人挑几行复制进 `broadcast/pending.txt`，次日走现成的播报 `body_file`。地址用播报同一把尺判（内网、带账号密码、带密钥参数、控制字符都拒），钥匙只写环境变量名，配置里不出现它的值；变量空了记 `no_token`，值里带换行当请求头注入直接拒。拉取最长等 20 秒，所以拿锁分两段，网络等待不占着播报那把五秒的锁。待审文件在 `.gitignore` 里。演练、`--check` 和 `--doctor` 一个文件都不生成，回归测试用假发送落点证明过。见 [agents/CONFIG.md](agents/CONFIG.md) 的「接待桥 intake」和 [docs/多入口对照与方案.md](docs/多入口对照与方案.md)。
- 新增 [docs/对外口径.md](docs/对外口径.md)（`voice-v1`）：官网浮层和飞书群共用的对外口径唯一来源——可介绍的作品清单与路径、口吻与风格锚、保密期作品不复述名字、不报价不承诺档期、成员身份不介绍、`[[COOP]]` 交接协议。这一版是人复制引用，不是运行时抓取；为什么先不做抓取，里面写了。同时记录一处已经漂了的事实：官网提示词里的开源模板地址还写着旧名 `feishu-group-agent`，301 跳到新名，链接没坏，但访客听到的介绍落后。
- 新增 [docs/多入口对照与方案.md](docs/多入口对照与方案.md)：LangBot（Web Page Bot 的嵌入脚本 + WebSocket + 可选 Turnstile + 连接数上限回 429、HTTP Bot 的 HMAC 签名 + 202 + 回调地址只从配置读）、AstrBot（适配器只需 `run()`/`meta()`，`webchat` 不自建服务、复用 WebUI 的 FastAPI 走 SSE，会话键 `platform_id:message_type:session_id`）、NoneBot2（Forward/Reverse driver + Mixin，服务端 driver 只能有一个，传输归 driver、协议归 adapter）三家怎么做多入口，对照我们已有的 `channels/` 能力清单和 `p2p_limited` 访客档，列出缺的四样，逐条写清对外入口会怎么坏、现在谁在守，结论是三个建议：不并进程、先并口径、只开一条只进不出的桥。

## [0.10.0] - 2026-11-04

发布说明见 [docs/release-0.10.0.md](docs/release-0.10.0.md)。旧的 `agents/*.json` 不改也能接着跑；播报 `broadcast` 和这一版新加的其它开关一样，默认关着。

### 变更

- 飞书私聊发「设置」只发一张卡片，不再先发一段「先看这一项」。卡片按「通知与推送」「回答能力」「记忆与学习」分组。功能名用产品里的说法，例如「用量周报」「离线告警」「技能（工作流）」。以前的叫法仍能用，回复「打开用量周报」或「打开断线提醒」还是原来那一项。
- 每一行是彩色标准图标、功能名、一句不超过 16 个字的说明和右侧勾选。卡片上不写序号，也不再写「开 / 关」。标题下写着「变更需确认后生效」。「技能自动迭代」缩在「技能（工作流）」下面；父项未启用时这一行变灰，点它不会单独记下。在卡片上关掉父项时，还开着的子项会一起待保存。「长期记忆」和「任务复盘」仍是两项。
- 点勾选后，原来那张卡片当场变成待保存。底部主按钮是「保存 N 项改动」，次按钮是「全部推荐设置」，还有「取消」。可以一次勾几项，只保存一次。点保存才备份、写入、检查并重启。失败仍会改回备份。没有改动时主按钮停用。长说明点这一行的小箭头展开。配置名字和确认方式收在底部「高级」里，默认不展开。
- 卡片顶部是大号的已开项数、一行小字、绿点和九格进度，并带版本号和上次启动时间。版本来自仓库根目录的 `VERSION`。标题用飞书预设的蓝色主题。没有可用的头图钥匙，所以不加横幅。
- 卡片回调没连上时，改发一条短文字，仍带序号 1 到 9。回复序号，多个用空格，例如 `1 5`。回复 `0` 是推荐设置。确认仍不能关掉。密钥、模型接口、私聊范围仍不能在对话里改。只有主人能改。

示意图和示例 JSON 在 [docs/demo/](docs/demo/README.md)。

### 添加

- 播报 `broadcast`，默认关。不写或 `enabled` 不是 `true` 时不发，`/状态` 也不多这一行。不读日历，不读任务表，不调用模型。早晨摘要照旧。
- 打开后，到点往 `broadcast.chat_ids` 里、并且已经在服务范围内的每个群发一条。每个群每个本地日最多一条，记在 `state/broadcast_state.json`，和早晨摘要的名额分开。重启不重发。发送明确失败会放掉名额；超时或看不懂结果就保持占坑。
- 不写 `source` 时，`urls`（站点健康）、`body_file`（例如待审名单）、`command` 的标准输出和 `text` 可以进同一条。命令是参数数组，不经过 shell，有超时，环境里不带密钥。公网地址只取状态码和限长摘录。不点名所有人。演练、`--check` 和 `--doctor` 不发。AI 资讯抓取不在这一版。转塘艺讯这类群保持 `digest.enabled` 为 false，只开播报。见 [docs/断线提醒与晨报.md](docs/断线提醒与晨报.md)。

- 部署核对：`python checks\verify_deploy.py --base <目录>` 一条命令给出机器可读的结论（HEAD 与部署标注 tag、心跳年龄、进程拓扑、配置哈希与定时输出、`deploy.lock`、`kb` 目录、`--doctor` 每一行）。全程只读，不发消息、不写心跳、不动进程。结论 `PASS` 退出 0，`FAIL` 退出 1，参数或目录不对退出 2。`agents` 里只有一个 json 时会自动选中。见 [docs/部署后验证.md](docs/部署后验证.md)。
- 升级或回滚期间在实例目录放 `state\deploy.lock`（`created=<Unix 秒>`，可再写 `ttl=<秒>`，默认 900 秒），看门狗读到就不重启也不发提醒；锁过期自动恢复保护，锁文件读坏也照常重启。`scripts\botproc.ps1` 新增 `Get-DeployLock` / `Set-DeployLock` / `Clear-DeployLock`。不用再停计划任务，见 [docs/升级已有智能体.md](docs/升级已有智能体.md)。
- consumer 每次真实退出都在 `logs\events.jsonl` 记一行 `kind=consumer`：事件名、退出码、结束原因、按日志归类的原因（域名解析失败算 `dns`，不再被算成鉴权）和打码截断后的 stderr 尾部。`--doctor` 因此新增一行 `restart`，按窗口累计退出次数并分开数原因：连续失败计数会在连上之后清零，只看当场那一次永远看不见「一天重启二十次」。够阈值只是 `WARN`，不判失败。
- `/状态` 在早晨摘要、播报、用量周报三项都关着时明说一句「这个实例不会主动发任何定时消息」。以前那几行直接不出现，很容易被读成漏写。
- 部署核对还会提醒三件事，都不改结论：这个 HEAD 上没有标注 tag、或者工作区还有未提交改动（说不清这台跑的是哪版）；`kb_dir` 指的目录不存在、或一个能检索的文件都没有（知识库检索和目录都关着时不提醒，那是正常配置）。数的条数和提示词里那份目录同一个口径。
- 部署核对新增 `runtime`：把本目录服务进程的启动时间和顶层 `.py` 最新的改动时间比一比，进程比代码旧就提醒「要重启才生效」。合并完代码没重启的那段窗口以前看不出来，`git` 和 `topology` 都各自正常。读不到启动时间时不猜。
- 新增 [docs/runbook-升级与回滚.md](docs/runbook-升级与回滚.md)：把真机上跑通的升级顺序（对外四步、内部八条命令）、每一步的停手判据、含看门狗的开与关的回滚顺序，还有备份和长任务自动化的几个坑写成一页。与 [docs/部署后验证.md](docs/部署后验证.md) 分工：那一页讲每一项看什么，这一页讲按什么顺序做、哪一步不过就停手。
- CI 的 Lint 那一格多了一条核对：测试里出现 Windows 形状的绝对路径字面量（`C:/x` 或 `C:\x`）必须先声明。这种串在 Windows 上是绝对路径、在 Linux 上是普通相对路径，`os.path.join` 两种走法不同，同一行断言在两个系统上测的不是同一件事。确实要 Windows 形状（假进程表、假命令行、盘符拒绝用例）时，在文件开头写一行 `# win-path-fixture：<原因>`，或者在那一行末尾加 `# win-path`。见 [docs/runbook-升级与回滚.md](docs/runbook-升级与回滚.md)。

### 修复

- 旧目录留下的 pid 文件里只有一个进程号，那个号 Windows 已经分给了别人（甚至分给正在启动的自己）时，启动不再被误判成「旧实例还在跑」而拒绝。放行时在日志里留一行 `stale pidfile`，不再只看到一句 REFUSED。判据是三条：号就是我们自己、pid 文件写的创建时间和现在的进程对不上、那个进程本来就是本目录的 `agentbot.py`。仍读不到命令行时照旧拒绝，不会因此开出两个接收进程。`python agentbot.py` 和 `scripts\start.ps1` 同一套口径。
- `scripts\reload.ps1` 停完之后等多久改成按秒算（`-StopWaitSec`，默认 45 秒），不再按「查 20 次」——每一轮都要问一次进程表，机器慢一点，实际等的时间能差好几倍。真拒绝启动时把那一个还留着的进程号和命令行前 160 个字符一起打出来，不再只有一句 `refused: receiver still running`。结束进程的范围没变，仍然只由 `stop.ps1` 做。
- Windows 上播报的 `command` 可以启动 `C:\...\python.exe` 这种解释器。盘符路径不再被当成密钥挡住。参数或路径里如果还有密钥、手机号或客户名，仍然不会启动。

## [0.9.0] - 2026-10-20

下面是用户能看到的变化。没写进旧配置的键，仍用各项自己的默认值。发布说明见 [docs/release-0.9.0.md](docs/release-0.9.0.md)。

### 添加

- 调用记录。每轮回答在本机 `logs/calls.jsonl` 记一条调用链：收到的消息、用过的技能和工具、每步耗时和 token、结果。写入前脱敏，客户名写成「某客户」，不记密钥。默认开。`observability.calls.retain_days` 不写是 30 天。主人私聊发「最近调用」或「这条怎么答的」可看。用量周报在有记录时多一段合计。不新开收消息进程。见 [docs/调用记录.md](docs/调用记录.md)。
- 复盘写回。一轮群聊做完后，把「做了什么、哪里出错、下次怎么做」写成一条记忆提案，走现有的「确认记忆」。点头才写入这个群，驳回或不回复不写。客户名写成「某客户」。默认关，在私聊「设置」里开。不另调模型，不新开收消息进程。见 [docs/复盘写回.md](docs/复盘写回.md)。
- 技能自动改进。技能有版本和基线哈希。主人私聊发「改进技能」时，根据失败的调用和复盘提议下一版。`evals/run.py` 的分数必须更高，并且用原来的确认方式点头，才替换 `SKILL.md`。发「回滚技能 名字」并确认，可回到上一版。默认关。不执行技能脚本，不新开收消息进程。见 [docs/技能自动改进.md](docs/技能自动改进.md)。
- 主理人加专员。复杂问题拆成查资料、读文档、起草，再汇总。专员只有只读工具，写入仍走白名单和确认。总预算和每一步的轮数、额度、时间都有上限，不写时用较宽的默认值。默认关。不新开收消息进程。见 [docs/主理人与专员.md](docs/主理人与专员.md)。

旧配置不用改。调用记录默认开，另外三项默认关。

## [0.8.1] - 2026-10-20

下面是用户能看到的变化。没写进旧配置的键，仍用各项自己的默认值。发布说明见 [docs/release-0.8.1.md](docs/release-0.8.1.md)。

### 修复

- 飞书后台没开通卡片回调时，`card.action.trigger` 接收进程会以 `failed_precondition`（退出码 2）马上退出。0.8.0 大约每 60 秒重启一次，并且任何接收进程退出都会把共用的连接状态记成断线。收消息的长连接还在，断线提醒却反复发给主人。
- 连接状态按接收进程分开记。只有 `im.message.receive_v1` 断了才算机器人断线。卡片进程异常只记一条警告，不发断线提醒。
- 启动前先探测卡片回调。已经能确认没订阅（`failed_precondition`、`not subscribed` 或退出码 2）时，这次运行不再启动、也不再重启卡片进程。确认自动改回确认码，并只私聊提醒主人一次，说明怎么开通。
- `--doctor` 会说明：没开通卡片回调不算断线，接收进程数量也不把 `card.action.trigger` 算进去。

### 添加

- `confirm.card_callback`：`auto`（默认）、`on`、`off`。`on` 仍会去启动，没订阅则退出后不再重启。`off` 不启动卡片进程，确认用确认码。

旧配置不用改。没写这项时按 `auto`。本说明不打 tag。

## [0.8.0] - 2026-10-20

下面是用户能看到的变化。没写进旧配置的键，仍用各项自己的默认值。发布说明见 [docs/release-0.8.0.md](docs/release-0.8.0.md)。

### 添加

- Windows 上一键安装向导。入口是 `scripts/setup.ps1`，提问在 `setup_wizard.py`，Mac 和 Linux 也可以直接跑这个 Python 脚本。一次只问一个问题，并说明为什么、去飞书开放平台的哪一页、直接回车用什么。说明见 [docs/一键安装.md](docs/一键安装.md)。
- 向导会检查 Python、Git、飞书命令行和 Cursor 在不在、登录了没有。缺了只给指引，不自动安装，也不改已有登录。
- App Secret 只从标准输入交给 `lark-cli config init --name <profile> --app-secret-stdin`。配置、草稿和屏幕上都不留密钥。模型如果改成 OpenAI 兼容接口或 Claude，配置里只写环境变量名。
- 可以列出机器人所在的群和成员来选择；查不到就手填。人设有通用、黑客松小组、工作室、课题组。用量周报、知识检索、记忆成长、早间待办、断线提醒、技能默认关闭，装好后在私聊里发「设置」再开。
- 已有配置先备份再改，不删除原文件和备份。中途关掉可以接着填，草稿不存密钥。`--dry-run` 不写文件；`--answers` 给非交互检查用。
- 写完会跑配置检查和 `--doctor`，每条失败和提醒都用白话说明怎么处理。可选创建登录计划任务和看门狗。同一个应用已经有接收进程时拒绝再启动。启动后由机器人私聊主人做自我介绍。
- 写入确认默认改成飞书卡片上的「确认」「取消」。卡片用大白话写要做什么、改哪里、影响谁。只有发起人本人点了才算，服务端核对人、会话、动作有没有被改过，以及有没有过期。点完卡片变成已确认或已取消，再回报结果。飞书没开通卡片回调时，自动改回确认码。`--doctor` 会给出警告和开通步骤。要在飞书后台用长连接添加 `card.action.trigger`。说明见 [docs/确认方式.md](docs/确认方式.md)。
- 可以配置 `confirm.mode`：`button`（默认）、`code`、`button_or_code`、`button_and_code`。批量写入、改功能开关、重启可以用 `confirm.high_risk_mode` 单独指定。确认码位数和有效期也可以改。主人在私聊里回复「确认方式」就能换，但不能关掉确认。

### 安全

- 确认仍然不能跳过。别人点按钮、过期、重放、改掉卡片上的动作，都不会执行。写入日志不留确认码、按钮记号和人的编号。

旧配置不用改。没写 `confirm` 时按点按钮；权限不够时自动退回确认码。从 0.7.0 升上来见 [docs/升级到0.8.0.md](docs/升级到0.8.0.md)。

## [0.7.0] - 2026-10-20

下面是用户能看到的变化。没写进旧配置的键，仍用各项自己的默认值。这一版新加的键默认关着，或不写就保持 0.6.0 的行为。发布说明见 [docs/release-0.7.0.md](docs/release-0.7.0.md)。

### 添加

- 可替换的模型提供方。不写 `model` 时仍是 Cursor（`cursor-agent`，配置里 `agent.mode` 为 `acp` 时仍是常驻进程），行为与现在相同。`model.provider` 可写成 `openai_compatible`（OpenAI Chat Completions 兼容，含 DeepSeek、通义、Kimi、OpenRouter、本机 Ollama）或 `anthropic`（Claude Messages API）。地址、模型名、温度、超时和最大 token 写在 `model` 里。密钥只写环境变量名（`model.api_key_env`），不能写进配置。说明和四份示例见 [docs/换模型.md](docs/换模型.md)。
- 这两个新接口走原来的工具循环：读群历史和知识库、记忆提议、写入确认码。没有自带联网。可选 `search`（Tavily 或 SearXNG）默认关，打开后用 `web_search`。流式进度仍在；有思考才放收起的思考摘要，没有就跳过。多轮上下文仍按话题拼进提示词。接口若返回 token 数，会计入用量周报的「模型用量」，没有则不写这一行。
- 主人可以在飞书私聊里开关功能。发「设置」或「/设置」会看到一张清单：用量周报、知识检索、记忆成长、早间待办、断线提醒、技能。每一项写着现在开没开、有什么用、打开后会不会主动发消息、要不要先准备资料。点「第 N 项」或回复数字，先看改动摘要，再用原来的 6 位确认码。确认码只认发起人、原来的私聊和原来的话题。说明见 [docs/新手开关功能.md](docs/新手开关功能.md)。
- 确认之后先备份配置，再写入，再跑配置检查，然后按停止再启动的方式重新拉起，并且不会同时留下两个接收进程。检查或重启失败会改回备份，并用大白话说明原因和下一步。
- 第一次被主人私聊，或刚启动且已经写了主人时，私聊发一段短介绍。不发到群里。群里有人问怎么开，只会请对方找主人到私聊里发「设置」，不讲配置细节。
- 对话不能改密钥、模型配置、谁可以私聊。这些只提示去改配置文件。改动记在 `logs/feature_switch.jsonl`，不含编号、确认码和密钥。

### 安全

- 密钥不进日志。`python checks/check_config.py`、`--check` 和 `--doctor` 在密钥变量没设置时失败，并说明在当前窗口怎么设。只读回答和白名单写入确认码不变。
- 私聊开关只改用量周报、知识检索、记忆成长、早间待办、断线提醒、技能。不能改模型配置、密钥和谁可以私聊。

旧配置不用改。从 0.6.0 升上来见 [docs/升级到0.7.0.md](docs/升级到0.7.0.md)。

## [0.6.0] - 2026-10-20

下面是用户能看到的变化。没写进旧配置的键，仍用各项自己的默认值。发布说明见 [docs/release-0.6.0.md](docs/release-0.6.0.md)。这一版新加的开关默认都关着。

### 添加

- 回答质量回归 `python evals/run.py`。用例在 `evals/cases/suite.json`，假模型基线在 `evals/baseline/ci.json`。说明见 [docs/回归测试.md](docs/回归测试.md)。不改默认配置。正式运行仍不读这些文件。CI 只跑假模型那一档，不连接飞书，也不拿单实例锁。
- 用量周报 `report`，默认关。不写或 `enabled` 为 `false` 时不发私聊，`/状态` 也不多这一行。打开后，按 `weekday` 和 `time`（不写是周一 09:00、`Asia/Shanghai`）把上一周的合计私聊给主人，每周一次，重启不重发。接收人优先用 `report.owner_open_ids`，空着再用 `alerts.owner_open_ids`。正文只有合计：问题与完成数、响应时间中位数和 P90、工具和文件类型、写入提议与确认、脱敏次数、错误、连接中断和健康提醒、粗问题类别。没有问题原文、人名、open_id 或群编号。
- 主人可以在私聊发 `/report` 再看一份，不占每周名额。群里发这条只回一句已私聊，明细不进群。没打开时，`/report` 仍交给模型。
- `python agentbot.py <配置> --report [--week 2026-W42] [--out 文件.md|文件.csv]` 只打印或导出，不发送。`enabled` 为 false 时也能用。
- 读文件的审计和用量只记扩展名，不记原文件名。脱敏命中只记次数。`--dry-run`、测试替身和停机补答会标成演练或补答，周报不把它们算进真实用量。
- 分群知识库检索，默认关。没写 `knowledge` 或 `enabled` 为 `false` 时，不收录、不检索，提示词、工具和 `/状态` 与现在一样。打开后，每个群或私聊一份本地 SQLite 索引：本地 `kb/`、可选的群文件，以及配置或群里出现的飞书云文档、知识库和多维表格。中文用字双字进 FTS5。配了 OpenAI 兼容的向量地址才做混合检索，否则只用关键词。模型用 `kb_search` 查，也可以打开 `auto_retrieve` 自动附上片段。回答按标题、章节或页码引用，飞书文档带链接。白名单成员发「/kb refresh」更新；「/kb」或「/kb status」查看。`refresh_min` 大于 0 时按间隔补一次，一个周期只更新一个会话。说明见 [docs/知识库.md](docs/知识库.md)。
- 记忆成长 `memory.growth`，默认关。不写或 `enabled` 为 `false` 时，不调用模型，不发提案，也不改「记一下」、`/记忆`、`/忘记`。长期记忆和成长都打开后，才会在配置的时间（不写是 03:00）或一段对话闲下来时，对照本群近期消息提议新事实、更新或作废。提案默认私聊 `approver_open_ids`，也可以改成发在本群。每条用单独的 6 位码，审批人才能 `确认记忆`、`改记忆` 或 `驳回记忆`。别人、别的群、过期和用过的码都不会写入。事实会记下日期、会话、消息编号和把握。客户名、手机号、证件号、邮箱和密钥整条不提议。群与群仍然分开。`/搜记忆` 只在长期记忆开着时可用。成长打开后，`/忘记` 要本人再确认；关着时仍是立刻删除。见 [docs/记忆成长.md](docs/记忆成长.md)。

旧配置不用改。说明见 [docs/用量周报.md](docs/用量周报.md)。从 0.5.0 升上来见 [docs/升级到0.6.0.md](docs/升级到0.6.0.md)。

### 安全

- 知识库按会话分开，检索不能指定别的群。收录前和送出前都打码，并消掉工具标记和伪造确认码。资料里的网址不会被拿去访问，只把飞书文档、知识库、多维表格的编号交给原来的只读命令。压缩包、PDF 页数和单文件大小仍用附件那一套上限。向量地址只来自配置，密钥只读环境变量。需要的飞书权限都是只读，没打开这项时 `--doctor` 不多要权限。

## [0.5.0] - 2026-10-19

下面是用户能看到的变化。没写进旧配置的键，仍用各项自己的默认值。发布说明见 [docs/release-0.5.0.md](docs/release-0.5.0.md)。这一版新加的开关默认都关着。

### 添加

- 六份创作流程技能，沿用原来的 `skills/<名字>/SKILL.md`、目录和触发词预放。分别是选题打分（`topic-ideation`）、短视频口播稿（`short-video-script`）、分镜表（`storyboard`）、不绑定某一家工具的提示词包（`aigc-prompt-pack`）、项目策划书（`creative-brief`）、创作复盘（`post-mortem`）。用户明确要求保存时，才提议已有的 `docs_create`、`docs_append` 或 `base_create`，确认码和写入白名单不变。
- `agents/example.json` 的 `skills.enabled` 仍是 `false`，`skills.only` 仍是 `[]`。不改配置时，提示词和没有这些文件时一样。只启用创作技能的写法在 [docs/技能.md](docs/技能.md) 和 [agents/CONFIG.md](agents/CONFIG.md)。
- 渠道适配器。收事件、发消息、改卡片、读历史和附件、查成员、认身份都从 `channels/` 出去。飞书（lark-cli）是第一个适配器。没写 `channel` 的旧配置仍走飞书，命令和配置键不变。渠道缺少的能力（例如卡片刷新或日历）不会进提示词，模型硬调用时直接说明，不打到传输层。测试用内存渠道。企业微信只放了实验骨架和设计说明，默认不加载，也不连接。见 [docs/渠道.md](docs/渠道.md) 和 [docs/渠道-企业微信.md](docs/渠道-企业微信.md)。
- 断线提醒 `alerts`，默认关。不写或 `enabled` 为 `false` 时不发消息，也不写 `logs/alerts.log`。打开后，长连接连续中断或心跳超过 `unhealthy_after_sec`（不写是 180 秒）才私聊 `owner_open_ids`，恢复后再发一条。`repeat_sec` 不写是 1800 秒。私聊和早晨摘要都交给当前渠道的 `push_text`。飞书在适配器里调用 `im +messages-send`，不依赖事件长连接，也不启动收消息的进程。企业微信骨架这项直接失败，不会去连接。看门狗仍按 3 分钟重启；只有这项开着时，才在重启前通知，失败也不挡住重启。`windows_toast` 默认 `false`。
- 早晨摘要 `digest`，默认关。这是框架会主动发到群里的唯一一种消息。`enabled` 为 `true` 时，按 `time` 和 `timezone`（不写是 08:30、`Asia/Shanghai`）往 `chat_ids` 里、并且已经在服务范围内的群发一条今天的日历和未完成任务。每个群每个本地日最多一条，重启也不再发。不点名所有人。正文先走原来的脱敏。没配日历或任务表就不读。打开后，提示词稳定前缀里多一句固定说明，不随问题和日期变化。

旧配置不用改。`/状态` 只在对应开关打开时多一行。

## [0.4.1] - 2026-10-19

下面是用户能看到的变化。没写进旧配置的键，仍用各项自己的默认值。发布说明见 [docs/release-0.4.1.md](docs/release-0.4.1.md)。

### 安全

- （#58）写入确认码绑定发起人、会话和话题。主聊天的码不绑单条消息编号。别人、别的群、别的私聊、别的话题都不能确认，错误尝试不会把码用掉。发送人或消息编号为空时不能发起或确认。用过或取消过的码先记入已用名单，重启后也不能再执行。还没使用且未过期的码，重启后仍然有效。新码不会覆盖还没确认的操作。`state/state.db` 会自己建 `used_writes` 表，不用手工迁移。
- （#58）引用、历史、网页说明、飞书文档、PDF、Word、PPT、Excel、压缩包、图片说明、长期记忆和工具结果里的工具标记、伪造确认码会被消掉。当前这条用户问题仍可正常调用工具。
- （#58）上网前的跳转探测只连接已经检查过的地址。域名解析到 `198.18.0.0/15` 的假 IP 代理仍然放行，裸 IP 和跳进内网仍然拒绝。
- （#58）Word、PPT、Excel 和知识库压缩包成员超过体积或压缩比时跳过。PDF 页数异常时整份跳过，不执行里面的脚本。启动时清掉超过一小时的临时文件。
- （#58）客户名多认全角空格、组合附加符号、拆开的短名，以及名单里拼音的声调和连字符。没有写进名单的拼音仍不自动隐藏。带空格或连字符的手机号、`Bearer` 和 `sk-` 样子的密钥会打码。日志里的接口错误和模型报错也会打码。
- （#58）同一个飞书应用只能有一个接收进程。另一个目录再启动会被拒绝，不会结束已经在跑的那个。`stop.ps1` 仍按本目录和 profile 判断，不会误杀别的机器人。
- （#58）单实例锁和按应用的锁先写完整内容，再让别的进程看见。启动的一瞬间，另一个进程不会把还没写完的空文件当成过期锁并接管。
- （#58）确认、状态、帮助和记忆命令不再受单人提问间隔限制，但每分钟有命令次数上限。不写 `rate_limit.max_commands_per_min` 时是 40。写成 `0` 表示不限这条。
- （#58）GitHub Actions 固定到 commit SHA，并校验 gitleaks 压缩包的 SHA256。
- （#58）`.github/dependabot.yml` 跟踪 github-actions 和 pip。`requirements.txt` 只列出可选的 `pypdf`。
- （#58）`CODEOWNERS`。安全上报写明使用 GitHub 私密漏洞上报。
- （#58）文档里的 `lark-cli config init` 都带 `--name <profile>`，并说明不写会覆盖这台电脑上其他机器人的 profile。

### 添加

- （#59）私聊可以按群成员放行。`p2p.allow_group_members` 默认 `false`，不写时不查群成员，和 0.4.0 一样。设为 `true` 后，当前在所服务群里的成员可以私聊；`allow_open_ids` 或写入白名单里的人仍然可以。`open_to_all` 优先。成员名单默认缓存 600 秒（`p2p.member_cache_ttl_sec`）。查成员失败、超时、缺权限或名单不完整时拒绝，不回复群外的人。需要 `im:chat.members:read`。

## [0.4.0] - 2026-10-19

下面是用户能看到的变化。没写进旧配置的键，仍用各项自己的默认值。

### 修复

- （#57）`--doctor` 只在 `lark-cli auth scopes` 给出应用或 tenant 权限时才核对，缺了才失败。`lark-cli` 1.0.98 不接受 `--as bot`；已经登录时这条命令返回 `tokenType` 为 `user` 的 `userScopes`（用户 token，可能只有 `offline_access`）。这不再被当成应用权限，改为警告，并请到开放平台核对。
- （#57）文本文件读写写明 UTF-8，子进程按 UTF-8 解码。标准流被管道或重定向接走、且当前不是 UTF-8 时会改成 UTF-8。中文 Windows 不设置 `PYTHONUTF8` 和 `PYTHONIOENCODING` 也能跑测试。直接看控制台时仍用原来的代码页。

### 添加

- 话题回复同时带了不同的 `root_id` 和 `thread_id` 时，仍算同一段对话。引用里的文件在追问时仍看得到正文，别的会话读不到。停机补答的文件消息不再把 `file_key` 当成提问。
- 语音、表情、群名片和联系人名片直接说明，不把内部编号交给模型。系统消息和撤回事件不回答。飞书限流码 `99991400` 说成稍后再试。
- 长期记忆写入、注入和 `/记忆` 会消掉工具标记。人工档案在磁盘上仍保留原文。常驻模式里，联网搜索已经放行但没有正文时，回退到一次性回答。
- 同一轮可以按顺序执行多条只读工具，每条仍做原来的校验。`message_attachment` 可以传 `message_ids`，逐条核对当前会话后再读，结果分开标注。每轮提示词写明还剩几轮只读工具。
- 扫描 PDF 交给模型的图片说明使用配置里的 `pdf_max_images`（不写是 3）。`docs_read` 只有正文真的被截断时才标「节选」。
- 这些上限不写时和以前一样：`tools.history.page_size` 50（停机补答拉消息也用它）、`tools.history.max_lines` 150（超出注明还剩几行，`0` 不截）、`tools.docs_search.max_chars` 4000、`tools.calendar_read.max_chars` 4000、`tools.base_read.max_chars` 5000、`memory.max_turn_chars` 2000（只留开头，`0` 留整段）、`agent.tool_context_budget_chars` 120000（多轮工具结果超预算时先压缩较早的结果，仍超就截断并注明，不报错；`0` 不设预算）。
- `skills.only`：不写、`[]` 或 `false` 时，文件夹里合法的技能仍然全部可用。写成名字列表后，目录、触发词预放和 `skill_read` 只认这些名字。写错的名字在 `--check` 里提示，不因此失败。
- `commands.status`：不写或为 `true` 时，`/状态`、`/status` 或单独一个「状态」直接回复当前开关，不调用模型。写成 `false` 时，这几个字仍交给模型。「状态怎么样」不是这条命令。
- `memory.trim_note`：不写或为 `true` 时，短期对话超过字数预算会在提示词里注明省略了几条，本地记录还在。写成 `false` 时仍丢掉旧对话，但不再写这句话。没超过预算时不加。
- 只读工具连续多轮（`agent.max_tool_rounds`，不写是 4）、当前会话历史附件（`tools.message_attachment`）、`stall_sec`、`shutdown_wait_sec`、`link_jump_sec`、`catchup.max_age_sec`、`logs/events.jsonl`、`--doctor`、`scripts/verify_windows.ps1`。旧配置没写这些键时行为与现在的默认相同。
- 模型预设 `deepseek`、`dashscope`、`zhipu`、`pangu`。只补空着的地址、模型名和变量名。密钥仍只读环境变量。没写 `model_provider` 时仍是 Cursor。
- 新人 15 分钟说明、排障、行为准则，以及 v0.4.0 发布说明。例子都是编的。
- GitHub Actions 增加 `windows-latest` 作业：用 Windows PowerShell 5.1（`powershell.exe`）解析 `.ps1`、干跑不改系统的函数，并检查含中文的脚本带 UTF-8 BOM，然后跑测试。
- `python checks/check_config.py` 按 JSON Schema 检查配置类型。密钥写进 `api_key_env` 或 `base_url` 会失败。缺了的键和不认识的键不失败。
- `python setup_agent.py` 可以干跑生成 `agents/<名字>.json`，并打印计划任务命令。不加 `--write` 不写文件，也不注册任务。
- 架构图补上现在实际走的路，以及 Cursor 与 OpenAI 兼容接口二选一。每晚整理记忆仍标为设计，默认不跑。
- 增加「用本框架参赛」说明：把 openJiuwen / JiuwenSwarm 的地址和模型名映射到现有配置，密钥仍只读环境变量。
- 知识库目录和 `kb_read`。旧配置没写时，空目录不改变提示词。
- 本机 `logs/journal.jsonl`，只记工具名、字数和耗时，不记问题原文。`observability.journal` 为 `false` 时不写。
- 长期记忆开着且档案被字数预算截断时，按本群问题召回命中的事实。`memory.recall` 为 `false` 时不召回。
- GitHub Actions：Windows 和 Linux 上跑测试与编译检查；另有 Windows PowerShell 5.1 作业检查脚本；Linux 上再跑 gitleaks 和 `checks/history_scan.py`。
- Issue 模板、Pull Request 模板、贡献说明里的代码风格。
- 可选的宽松读数见 [docs/宽松配置示例.md](docs/宽松配置示例.md)。只读轮数、一次回答里的附件数、PDF 页数、文档字数，以及 `history.max_lines`、`docs_search` / `calendar_read` / `base_read` 的 `max_chars`、`memory.max_turn_chars`、`agent.tool_context_budget_chars` 都可以调大。`agents/example.json` 和程序默认值不变。确认码和写入白名单也不放宽。

### 安全

- 公开前扫描只报告打码结果，不改写 Git 历史。

## English

The version is the `VERSION` file (`0.8.1`), released on 2026-10-20. Do not put secrets or Feishu IDs in release notes. The program does not read this file. If `card.action.trigger` is not subscribed, that consumer is not restarted, confirmation falls back to the code, and the owner is notified once. Only the message consumer marks the bot offline. `--doctor` does not count the card consumer until callbacks are connected. `confirm.card_callback` defaults to `auto`. Old config files do not need new keys. Rollback target is `8604f62` (`0.8.0`). This note does not create the tag.

The previous version is the `VERSION` file (`0.8.0`), released on 2026-10-20. Do not put secrets or Feishu IDs in release notes. The program does not read this file. This release adds a one-question-at-a-time install wizard and makes write confirmation a card button by default. `confirm.mode` can be `button`, `code`, `button_or_code`, or `button_and_code`. Confirmation cannot be turned off. If the app has not subscribed to `card.action.trigger` on the long connection, new writes fall back to the confirmation code and `--doctor` warns with the enable steps. Old config files do not need new keys. Upgrade steps are in `docs/升级到0.8.0.md`. Rolling back to `26f37c5` keeps the wizard and drops the card buttons; that commit still says `VERSION` `0.7.0`. This note does not create the tag.

The previous version is the `VERSION` file (`0.7.0`), released on 2026-10-20. Do not put secrets or Feishu IDs in release notes. The program does not read this file. Omitting `model` keeps the Cursor path from 0.6.0. `search` stays off when omitted. Owners can toggle the existing usage report, knowledge search, memory growth, morning digest, disconnect alerts, and skills in a private chat. That switch cannot change model settings, secrets, or who may use private chat. Upgrade and rollback steps are in `docs/升级到0.7.0.md`. Rolling back to v0.6.0 (`4da9e42`) drops the model providers and the private-chat switch. This note does not create the tag.

The previous version is the `VERSION` file (`0.6.0`), released on 2026-10-20. Do not put secrets or Feishu IDs in release notes. The program does not read this file. 0.6.0 adds answer-quality evals, an optional weekly usage report, optional per-chat knowledge search, and optional memory growth. All four stay off when omitted. Evals do not connect to Feishu. The report is a weekly owner DM with totals only. Knowledge search indexes one chat and cites sources. Memory growth writes nothing until an approver confirms. Upgrade and rollback steps are in `docs/升级到0.6.0.md`. Rolling back to v0.5.0 (`e842684`) drops these four. This note does not create the tag.

The previous version is the `VERSION` file (`0.5.0`), released on 2026-10-19. Do not put secrets or Feishu IDs in release notes. The program does not read this file. Missing keys keep the previous behavior. 0.5.0 adds six creative-workflow skills, a channel adapter (Feishu is the first implementation; WeCom is an experimental skeleton and does not connect), optional disconnect alerts, and an optional morning digest. `skills.enabled`, `alerts.enabled`, and `digest.enabled` stay false when omitted. An empty `skills.only` still means every valid skill once skills are turned on. Writes still need the allow-list and a confirmation code. Alert DMs and digest posts go through the channel `push_text` method. On Feishu that is `im +messages-send` and does not start the event consumer. The digest posts at most once per local day per configured chat and never mentions everyone. Upgrade and rollback steps are in `docs/升级到0.5.0.md`. Rolling back to v0.4.1 (`deb498f`) also drops the channel adapter and the creative skills.

0.4.1 remains the previous release. (#58) Confirmation codes are bound to the initiator, chat, and topic. Used or cancelled codes are stored in `used_writes` before they run and cannot be replayed after a restart. Untrusted text cannot become a tool call or a confirmation code. Redirect checks connect only to addresses that were already validated. One Feishu app has one receiver. Lock files become visible only after they are fully written. Confirm, status, help, and memory commands skip the per-user gap and use `rate_limit.max_commands_per_min` (default 40). (#59) `p2p.allow_group_members` defaults to false. When enabled, current members of served groups may use private chat, which needs `im:chat.members:read`. `open_to_all` still wins, and a failed or truncated member list fails closed. Those upgrade steps are in `docs/升级到0.4.1.md`. 0.4.0 still includes several read-only tool calls per round, configurable read caps, and the (#57) doctor and UTF-8 fixes.
