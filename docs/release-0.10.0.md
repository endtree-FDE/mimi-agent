# v0.10.0 发布说明

版本号是仓库根目录的 `VERSION`：`0.10.0`。发布日期是 2026-11-04。这一版开始，主人在私聊发「设置」时，卡片顶部会读 `VERSION` 显示版本号；读不到，或者不是 `x.y.z` 这种写法，卡片上就不写版本，开关本身不受影响。正文不写密钥、群号、open_id、客户名或个人电脑路径。

这一版相对 [v0.9.0](release-0.9.0.md)（`51da849`）。

## 这一版加了什么

旧的 `agents/*.json` 不改也能接着跑。新加的播报默认关着，不开就和 0.9.0 一样。

- **设置卡片重做**（原来发两段，现在只发一张）。按「通知与推送」「回答能力」「记忆与学习」分组，功能名用产品里的说法（「用量周报」「离线告警」「技能（工作流）」）。一行是图标、功能名、不超过 16 个字的说明和右侧勾选，卡片上不写序号。勾几项一次保存，底部主按钮是「保存 N 项改动」，点保存才备份、写入、检查并重启，失败改回备份。「技能自动迭代」缩在「技能（工作流）」下面，父项没开时这一行变灰。配置名字和确认方式收在底部「高级」。卡片回调没连上时改发一条带序号 1 到 9 的短文字，回复序号例如 `1 5`，回复 `0` 是推荐设置。确认仍然不能关掉。以前的叫法照用，回复「打开用量周报」还是原来那一项。见 [新手开关功能](新手开关功能.md)。
- **播报 `broadcast`**（默认关，`broadcast.enabled`）。到点往 `broadcast.chat_ids` 里、并且已经在服务范围内的每个群发一条，每个群每个本地日最多一条，记在 `state/broadcast_state.json`，和早晨摘要的名额分开，重启不重发。不读日历、不读任务表、不调用模型。不写 `source` 时，`urls`（站点健康）、`body_file`、`command` 的标准输出和 `text` 可以进同一条；命令是参数数组，不经过 shell，有超时，环境里不带密钥。演练、`--check` 和 `--doctor` 不发。见 [断线提醒与晨报](断线提醒与晨报.md)。
- **一条命令拿到部署结论**：`python checks\verify_deploy.py --base <实例目录>`。输出机器可读的 JSON——HEAD 与这一版上的标注 tag、心跳年龄、进程拓扑、配置哈希与定时输出、`deploy.lock`、`kb` 目录、`--doctor` 每一行。全程只读，不发消息、不写心跳、不动进程。`PASS` 退出 0，`FAIL` 退出 1，参数或目录没给对退出 2。`agents` 里只有一个 json 时会自动选中。见 [部署后验证](部署后验证.md)。
- **升级期间放 `state\deploy.lock`，不用停计划任务**。看门狗读到没过期的锁就不重启、也不发断线提醒；锁过期自动恢复保护，锁文件读坏了也照常重启（宁可多拉一次，不要没人拉）。`scripts\botproc.ps1` 因此有 `Get-DeployLock` / `Set-DeployLock` / `Clear-DeployLock`。见 [升级已有智能体](升级已有智能体.md)。
- **接收进程每次真实退出都记账**，`logs\events.jsonl` 多一行 `kind=consumer`：事件名、退出码、结束原因、按日志归类的原因（域名解析失败算 `dns`，不再被算成鉴权）和打码截断后的 stderr 尾部。`--doctor` 因此新增一行 `restart`，按窗口累计退出次数并分开数原因。连续失败计数会在连上之后清零，只看当场那一次永远看不见「一天重启二十次」。够阈值只是 `WARN`，不判失败。`alerts.restart_window_sec` 不写是 21600 秒（6 小时），`alerts.restart_warn_after` 不写是 3 次。
- **`/状态` 在三项定时输出都关着时明说一句**「这个实例不会主动发任何定时消息」。以前那几行直接不出现，很容易被读成漏写。
- **运维手册进仓库**：[runbook-升级与回滚](runbook-升级与回滚.md)。真机上跑通的升级顺序（对外四步、内部八条命令）、每一步的停手判据、含看门狗开与关的回滚顺序，还有备份和长任务自动化的几个坑。与 [部署后验证](部署后验证.md) 的分工：那一页讲每一项看什么，这一页讲按什么顺序做、哪一步不过就停手。
- **CI 多一条测试写法核对**。测试里出现 Windows 形状的绝对路径字面量（`C:/x` 或 `C:\x`）必须先声明。这种串在 Windows 上算绝对路径、在 Linux 上只是普通相对路径，`os.path.join(base, "C:/x")` 在前者直接丢掉 `base`、在后者把两段拼起来，同一行断言两个系统测的不是同一件事。要「一个绝对路径」就用 `tempfile.gettempdir()` 现取；确实要 Windows 形状（假进程表、假命令行、盘符拒绝用例）时写明原因。

## 修了什么

- 旧目录留下的 pid 文件里只有一个进程号，那个号系统已经分给了别人（甚至分给正在启动的自己）时，启动不再被误判成「旧实例还在跑」而拒绝。这是 2026-11-03 那次线上停机的根因。放行时日志留一行 `stale pidfile`。判据是三条：号就是我们自己、pid 文件写的创建时间和现在的进程对不上、那个进程本来就是本目录的 `agentbot.py`。仍读不到命令行时照旧拒绝，不会因此开出两个接收进程。`python agentbot.py` 和 `scripts\start.ps1` 同一套口径。
- `scripts\reload.ps1` 停完之后等多久改成按秒算（`-StopWaitSec`，默认 45 秒），不再按「查 20 次」——每一轮都要问一次进程表，机器慢一点，实际等的时间能差好几倍。真拒绝启动时把那一个还留着的进程号和命令行前 160 个字符一起打出来。结束进程的范围没变，仍然只由 `stop.ps1` 做。
- Windows 上播报的 `command` 可以启动 `C:\...\python.exe` 这种解释器。盘符路径不再被当成密钥挡住。参数或路径里如果还有密钥、手机号或客户名，仍然不会启动。

## 从 0.9.0 换上

一个实例一个实例地换，另外几个保持运行。看门狗大约每 3 分钟看一次心跳，这一版起可以在升级期间放锁，不用停那条计划任务。

```powershell
# 1 先确认这台现在是好的（只读）
python checks\verify_deploy.py --base . -c agents\<名字>.json --no-doctor
# 2 取代码，只接受快进；然后跑离线测试
git fetch origin --tags
git reset --keep v0.10.0
python tests\run_tests.py
# 3 放锁，平滑重启
. scripts\botproc.ps1; Set-DeployLock (Get-Location) 1200 'upgrade-0.10.0'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\reload.ps1 -Config agents\<名字>.json
# 4 复核，通过就释放锁
python checks\verify_deploy.py --base . -c agents\<名字>.json
. scripts\botproc.ps1; Clear-DeployLock (Get-Location)
```

`git reset --keep` 留下配置、`state`、`kb`、`memory`、`redact.txt` 和 `logs`。不要用 `git reset --hard`，也不要 `git clean`。从上游标签取用就是上面这条 `reset --keep`；从本机另一个开发副本取用改成 `git fetch <副本> main` 再加 `git merge --ff-only FETCH_HEAD`，两条不要混着用。第 4 步要看的是 JSON 里的 `status` 是不是 `PASS`、`topology.serving` 是不是 1；`warns` 条数不是固定的，别拿它当闸门。四步的顺序和停手判据见 [runbook-升级与回滚](runbook-升级与回滚.md)。

这一版没动消息解析、人设和写入确认，配置不用改。播报按需要再开；三项定时输出都关着时 `/状态` 会明说「这个实例不会主动发任何定时消息」，不用猜。

## 退回 0.9.0

退回目标是 `v0.9.0`（`51da849`）。回滚比重启更危险：先停看门狗，再动代码，失败时让它留在停用状态，宁可没人拉也不要反复拉起坏实例。

```powershell
python checks\verify_deploy.py --base . -c agents\<名字>.json --no-doctor
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop.ps1
git reset --keep v0.9.0
python agentbot.py agents\<名字>.json --check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1 -Config agents\<名字>.json
python checks\verify_deploy.py --base . -c agents\<名字>.json
```

0.9.0 的看门狗认不出 `state\deploy.lock`。如果退回前放过锁，退回后要么把那个文件删掉，要么停掉那条计划任务再启动——留着不管的话，它只是不挡重启，但这一版的看门狗根本不看它。`state/broadcast_state.json` 留着不碍事，0.9.0 不读它。含看门狗开关的完整回滚顺序见 [runbook-升级与回滚](runbook-升级与回滚.md)。

## 还没做

- 企业微信不能拿来收消息。
- AI 资讯抓取不在这套代码里。播报只发你给它的那段正文和站点健康检查。
- `kb` 迁出仓库的迁移脚本还在运维侧，这一版只把核对做了（目录在不在、能检索到几条，与提示词里那份目录同一个口径）。

## English

`VERSION` is `0.10.0`, released on 2026-11-04. Old config files keep working without new keys; the broadcast stays off until you turn it on.

New: the settings card is one grouped interactive card (notifications, answering, memory) with checkboxes and a single "save N changes" action, falling back to a numbered text message when card callbacks are not wired up. `broadcast` sends one prepared message per chat per local day, with an idempotency state file, no model call, and no calendar/task reads. `checks/verify_deploy.py` returns a machine-readable verdict after any upgrade or rollback (read-only: HEAD and deploy tag, heartbeat age, process topology, config hash and scheduled outputs, `deploy.lock`, `kb` directory, doctor rows). `state/deploy.lock` now makes the watchdog yield during maintenance instead of disabling the scheduled task. Consumer exits are logged with code and redacted stderr tail, and `--doctor` adds a `restart` row counting them per window. `/status` says explicitly when no scheduled output is on. A runbook (`docs/runbook-升级与回滚.md`) records the four-step upgrade, its stop gates, and a rollback order that includes the watchdog.

Fixed: a reused pid no longer blocks startup (the 2026-11-03 outage root cause); `reload.ps1` waits by seconds instead of poll count; interpreter paths with a drive letter are no longer treated as secrets by `broadcast.command`.

Rollback target is `v0.9.0` (`51da849`). Note that the 0.9.0 watchdog does not understand `deploy.lock`.
