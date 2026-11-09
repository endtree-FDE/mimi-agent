# 配置怎么填

一份配置 = 一个机器人。复制 `example.json`，改名为你的机器人，例如 `agents/xiaojing.json`。用记事本或 VS Code 打开，按下面逐项改。

先记三句：

1. 以 `REPLACE_` 开头的，都必须换成你自己的，不能留着启动。
2. 「小助手」「小李」只是例子，改成你的机器人名字和同事的称呼。
3. **不要**在这个文件里写应用密钥（App Secret）。密钥只在你自己电脑上、运行初始化命令时输入一次，见 `docs/新建智能体.md`。

默认走这台电脑上的 Cursor：模型名字写在 `agent.model`，默认是 `grok-4.7-high-fast`，额度算已经执行过 `cursor-agent login` 的那个账号。要换成自己的模型账号，把 `model_provider` 写成 `openai_compat`，或改用 `model.provider`（`openai_compatible` 或 `anthropic`）。密钥放在环境变量里。配置里不写账号，也不要写别人的账号。见 [docs/换模型.md](../docs/换模型.md) 和 [docs/模型接口.md](../docs/模型接口.md)。

下面按文件里的顺序说明每一项。

## 基本

| 键 | 填什么 |
|---|---|
| `name` | 这个机器人的短名字，只用英文和数字，例如 `xiaojing`。用来写日志。 |
| `base_dir` | 填放着 `agentbot.py` 的那个文件夹的完整路径，斜杠写成 `/`。看门狗只读这个代码文件夹里的 `state\heartbeat`。程序把心跳写在 `base_dir` 下面。两个地方不一致，看门狗会每 5 分钟重启一次。不要填成别的文件夹，也不要填别人的用户目录。 |
| `kb_dir` | 知识库文件夹，默认 `kb`。把资料 md 或 txt 放在那里。 |
| `profile` | 你在自己电脑上配置 lark-cli 时起的名字。运行 `lark-cli config show` 能看到。不是应用密钥。 |
| `bot_open_id` | 机器人自己的编号。在群成员列表的 bots 里，抄 `member_id`。没填时，正式启动会被拒绝。演练模式可以暂时空着，但正式用之前必须填。 |
| `bot_names` | 机器人在群里显示的名字，可写多个。有人 @ 这个名字时，程序会把 @ 去掉再理解问题。 |
| `chat_ids` | 允许回答的群的编号，一个群一项。不在这里的群，即使被 @ 也不说话。编号只能含字母、数字、下划线和短横线。写了这项（非空数组）就只用它。想改成自动认群，要把它改成 `[]`，见下面「哪些群会回答」。 |
| `conflict_pidfiles` | 旧程序的 pid 文件路径。文件第一行仍是进程号。那个进程看起来还是 `agentbot.py` 时，新程序拒绝启动，避免同一个应用回复两次。编号若已被别的程序复用（pid 文件第二行写了 `created=` 且和现在的进程对不上），或者那个编号现在就是本目录自己的进程，都不拒绝，也不结束它，只在日志里留一行 `stale pidfile`。读不到命令行时宁可拒绝。`scripts\start.ps1` 同样如此，打出 REFUSED 并且不启动。没有旧程序就留空列表 `[]`；旧目录已经彻底不用了，把它的 pid 文件删掉更干净。 |
| `reply_in_thread` | `true` 表示回复在话题里，不打散群聊。一般保持 `true`。 |
| `max_concurrency` | 同时最多答几题。默认 `2`。 |
| `max_queue` | 排队最多几题，多出来的会回复「提问有点多」。默认 `4`。 |
| `shutdown_wait_sec` | 收到停止信号后，最多再等几秒让正在答的题写完。默认 `15`。不写这项也是 15 秒。写成 `0` 表示不等，马上退出；没答完的题留在 `state.db`，下次启动补答。负数或写错会按 15 秒。 |
| `link_jump_sec` | 电脑休眠后，长连接超过这么多秒就重连。不写是 `20`。写成 `0` 表示不因为休眠去重连；进程退出后下次启动仍会重新连接。写错按 20 秒。这项不发消息。 |
| `channel` | 不写就是飞书，旧配置不用加这一项。写成 `wecom` 之前要看 [docs/渠道-企业微信.md](../docs/渠道-企业微信.md)。企业微信还是实验骨架，还要把 `channels.experimental` 设为 true 才会加载，而且加载后也不会连接。密钥不要写在这里。 |

## 停机补答 catchup

进程被杀掉，或用 `scripts\stop.ps1` 优雅停止时，正在答的那条不会丢。它在 `state.db` 里记着「收到了、还没答完」，下次启动会再答一次。同一条连着补答仍失败，就放弃，避免一条坏消息反复把进程拖死。`state\inflight.json` 只记消息编号和阶段，不记问题原文。停机和锁的升级说明见 [docs/升级停机与单实例.md](../docs/升级停机与单实例.md)。`scripts\stop.ps1` 怎么写下 `state\shutdown.request`、看门狗为什么不会因此保持停止，见 [docs/运维升级回滚与停机意图.md](../docs/运维升级回滚与停机意图.md)。

停机期间 @ 了机器人、本地又没有答过的消息，启动时用群消息列表回扫。起点是上次心跳再往前 `overlap_sec` 秒（默认 300），并且不会早于现在减去 `max_age_sec`（默认 12 小时）。回复开头会写「（延迟回复）」。已经答过的、已经撤回的，都不会再答。没有上次心跳（第一次启动）不回扫。一次最多 `max_messages` 条（默认 20）。

| 键 | 含义 |
|---|---|
| `enabled` | 默认 `true`。改成 `false` 就不再回扫停机期间的 @。正在处理却没答完的那条仍然会补。 |
| `overlap_sec` | 从上次心跳再往前重叠多少秒。默认 `300`。 |
| `max_messages` | 一次启动最多补多少条。默认 `20`。 |
| `max_age_sec` | 只补最近这么多秒里的消息。不写是 `43200`（12 小时）。写成 `0` 表示不再另加这条时限，仍按心跳和条数回扫。负数或写错按 12 小时。 |

演练（`--dry-run`）默认不回扫。要试这一段，设环境变量 `AGENTBOT_CATCHUP=1`，并先写好 `state/heartbeat`。

## 话题里接着问 thread_followup

群里默认仍要 @ 机器人才回答。写了下面这项并且 `enabled` 为 `true` 时，它**已经答过**的那条话题里，可以不 @ 接着问。没写这项的旧配置保持原样：必须 @。私聊本来就不用 @，不受这项影响。接着问仍然受 `rate_limit` 限制。

| 键 | 含义 |
|---|---|
| `enabled` | 默认当没写时是 `false`。例子里打开了。 |
| `who` | 谁可以不 @。`initiator_or_whitelist`（默认）：这条话题里第一个被接住的人，或写入白名单里的人。`initiator` 只限开头那个人。`whitelist` 只限白名单。`anyone` 是这个话题里的其他人也可以，仍不主动开口。 |

机器人自己的消息不会当成追问。别人的话题、它还没答过的话题，仍然要 @。同一条话题若同时带了 `root_id` 和另一个 `thread_id`，以 `root_id` 为准，避免拆成两段会话。

## 哪些群会回答

`chat_ids` 和 `chats` 一起决定群里回不回。私聊不看这两项，仍由后面的「谁可以私聊」决定。

| 情况 | 群里被 @ 时 |
|---|---|
| `chat_ids` 里有群 | 只回答这些群。`chats.auto_join` 写成 `true` 也不生效。这是默认，和以前一样。 |
| `chat_ids` 是 `[]` 或没写，并且 `auto_join` 是 `false` | 哪个群都不回答。 |
| `chat_ids` 是 `[]`，并且 `auto_join` 是 `true` | 按 `admit` 认群。认下来的群会记进 `state.db`，每个群的长期记忆仍单独放。 |

`chats` 这一段：

| 键 | 默认 | 填什么 |
|---|---|---|
| `auto_join` | `false` | `true` 才启用自动认群。必须同时把 `chat_ids` 留空。 |
| `admit` | `confirm` | 安全门槛。只在 `auto_join` 生效时有用。看不懂就留 `confirm`。 |
| `inviter_open_ids` | `[]` | 只给 `admit` 为 `whitelist` 用。这些人的编号也可以把机器人拉进群。空着就只用 `write.allowed_users`。 |

`admit` 三个值：

- `confirm`（默认，推荐）：被拉进群、或启动时发现已经在某个群里，都先记成待认，**不回答，也不调用模型**。`write.allowed_users` 里的人在那个群 @ 机器人，发送 `/认群`，它才开始回答。发送 `/忘群` 就停。陌生人 @ 它，它保持沉默。
- `whitelist`：拉机器人进群的人在 `write.allowed_users` 或 `inviter_open_ids` 里，这个群直接可答。其他人拉进去的，仍要 `/认群`。启动时列出来的旧群不知道是谁拉的，也要 `/认群`。
- `open`：机器人当前所在的群，被 @ 就回答。谁能把它拉进群，谁就能消耗模型额度。一般不要用。

三种都一样：**不会在进群时主动发消息**，也不会发「大家好」。只有有人 @ 它，它才可能说话。`/认群` 和 `/忘群` 也是回复那条 @，不另找群来广播。

没订上进群事件也还能用。订了更及时：

- 事件 `im.chat.member.bot.added_v1`、`im.chat.member.bot.deleted_v1`（长连接）
- 权限 `im:chat.members:bot_access`，以及启动时列群用的 `im:chat:read`

启动时会跑 `lark-cli im +chat-list`（也就是列出 `im/v1/chats`）。列表失败只记一行日志，不清掉已经认过的群。

认下来的群，如果开了长期记忆，会马上建 `memory/groups/群编号/`。没认之前不建。以前用 `chat_ids` 跑过、已经记进 `state.db` 的群，改成自动认群之后仍算已认，不用再发 `/认群`；不想回答就在那个群发 `/忘群`。启动时如果发现机器人已经不在那个群里，会把它标成离开。

## 多久能问一次

`rate_limit.min_gap_per_user`：同一个人至少隔多少秒才能再问。默认 `20`。

`rate_limit.max_per_hour`：所有人加起来，一小时最多答多少次。默认 `30`。超过就回复「提问有点多」。

`agent.max_input_chars`：交给模型的问题最长多少字。默认 `8000`。更长的会截断，并在问题末尾注明。`0` 表示不截断。这是为了避免一条超长消息把额度打光。短问题不受影响。

## 状态命令 commands

`commands.status` 不写或为 `true` 时，群里 @ 机器人发送 `/状态`、`/status`，或单独一个「状态」，会直接回复当前开关，不调用模型。回复里有模型接口、短期记忆条数、长期记忆和技能是否打开、写入是否要确认码。不打印文件夹、profile、群号、人的编号或密钥。

写成 `false` 时，这几个字仍交给模型，和以前一样。

「状态怎么样」「看一下状态」不是这条命令，仍会调用模型。

## 开关 features

每一项都是 `true` 或 `false`。

| 键 | 打开之后 |
|---|---|
| `memory` | 记住**当前话题**最近几轮对话（短期）。关掉后，下一句不再接着上一句。 |
| `p2p` | 允许私聊。关掉后，私聊一律不回。 |
| `tools` | 允许查飞书（群历史、文档、日历、表格）以及按确认码写入。 |
| `attachments` | 允许看对方发来的图片和文件。 |
| `vision` | 允许把图片交给模型看。要和 `attachments` 一起开。 |

## 两套「记忆」，不要混

`memory` 这一段里有两类开关：

- `enabled`：长期记忆（「记一下」、`/记忆`、`/忘记`）。**默认 `false`。** 想用之前先看 `docs/记忆与命令.md`，确认没问题再改成 `true`。升级旧机器人时，先不要开，见 `docs/升级已有智能体.md`。
- `max_turns`、`ttl_hours`：短期话题记忆，配合上面的 `features.memory`。默认记住 6 轮，超过 24 小时就忘掉。
- `max_turn_chars`：记进短期记忆的一条最多多少字，只保留开头。不写是 `2000`。`0` 表示整段都留下。写错或负数按 2000。这只影响之后新记下的内容，不改已经存在的记录。
- `context_budget_chars`：这几轮加起来最多多少字再交给模型。默认 `8000`。超了就丢掉最旧的整条，最新一条即使超长也留下。`0` 表示只按轮数，不按字数裁。短对话看不出差别。
- `trim_note`：丢掉旧对话时，要不要在提示词里写一句「省略了几条，本地还在」。不写或 `true` 就写这一句。`false` 恢复原来的静默丢掉。没超预算时不加这句话，短对话的提示词不变。这一句不另调模型。
- `dir`：长期记忆放在哪个文件夹，默认 `memory`。每个群一个子文件夹，互不混用。
- `profile_budget_chars`：注入给模型的群档案最多多少字，默认 `1500`。超了会截断。
- `recall`：档案被截断时，若这一题命中了没放进去的事实，把那几条补在问题前面。**没写或 `true` 时，只要长期记忆开着就会这样做。** `false` 恢复成只给截断后的档案。长期记忆关着时，这一项不改变提示词。
- `recall_budget_chars`：补进去的事实一共最多多少字，默认 `400`。`0` 或负数表示不补。
- `max_fact_chars`：一条「记一下」最多多少字，默认 `300`。
- `scope`：现在固定用 `topic`（按话题分开）。
- `per_user`：按人记一份档案。**先保持 `false`。** 个人记忆默认不开启。
- `growth`：从近期对话里提议新的长期记忆。**默认关。** 不写或 `enabled` 为 `false` 时，不调用模型，不发提案，`/忘记` 仍是立刻删除。打开之后的审批、命令和配置键见 [docs/记忆成长.md](../docs/记忆成长.md)。

- `retrospect`：一轮群聊做完后，写一句「做了什么、哪里出错、下次怎么做」，走记忆成长的审批。**默认关。** 不写或 `enabled` 为 `false` 时不提议。长期记忆也要开着；从私聊「设置」打开时会一起打开。审批人仍用 `memory.growth.approver_open_ids`。没人点头不写入。说明见 [docs/复盘写回.md](../docs/复盘写回.md)。

`agents/example.json` 里 `memory.growth.enabled` 和 `memory.retrospect.enabled` 仍是 `false`。旧配置没有这两段时，行为和以前一样。

## 技能 skills

技能是「这类事怎么做」的步骤，不是资料，也不是记忆。默认关着。怎么写一份新技能，看 [docs/技能.md](../docs/技能.md)。

| 键 | 默认 | 填什么 |
|---|---|---|
| `enabled` | `false` | `true` 才把技能目录放进提示词。关掉时，提示词和没有技能层时一样，触发词也不会预放正文。 |
| `dir` | `skills` | 技能文件夹，相对 `base_dir`。每个技能一个子文件夹，里面一份 `SKILL.md`。 |
| `only` | 不写或 `[]` | 选用哪些技能。不写、空列表或 `false` 时，目录里合法的技能全部可用，和以前一样。写成 `["meeting-minutes"]` 之后，目录、触发词预放和 `skill_read` 都只认这几个名字。没被点名的技能还在文件夹里，只是这一个机器人不用。名字写错时，`--check` 打一行 HINT，不因此失败。 |
| `index_budget_chars` | `800` | 目录最长多少字。每个技能只占一行「名字：描述」，超了就截断。 |
| `preload` | `true` | 问题命中某个技能的 `triggers` 时，把那份正文直接放进这一题。只在 `enabled` 为 `true` 时生效。改成 `false` 就只留目录，模型再用 `skill_read` 去读。 |
| `preload_budget_chars` | `3000` | 预放的正文最长多少字。超了就截断，并注明已经按字数预算截断。 |

还要开着 `features.tools`。没有命中触发词时，模型要用某个技能，会输出一行 `<<TOOL>>{"tool":"skill_read","name":"名字"}`，程序只读那份正文。工具关着的话，这一行不会执行。

预放的正文放在这一题会变的部分，紧挨在问题前面。技能目录和群档案仍在前面，不跟着这一题变。常驻模式下冻住的也只是群档案。一题最多预放 1 个；命中多个时取得分最高的，得分是命中关键词的字数相加。怎么写 `triggers` 见 [docs/技能.md](../docs/技能.md)。

- `evolve`：根据失败的调用和复盘，提议技能的下一版。**默认关。** 不写或 `enabled` 为 `false` 时不记信号，也不改 `SKILL.md`。打开后要主人私聊发「改进技能」。程序会跑 `evals/run.py`（假模型，默认带 `ci` 标记的整套题）。分数没有更高不替换。分数更高，还要用原来的确认方式点头。`cases` 不写就跑整套；写成用例编号就只跑那几条。回滚发「回滚技能 名字」，确认后回到上一版。不执行技能里的脚本。说明见 [docs/技能自动改进.md](../docs/技能自动改进.md)。

升级旧机器人时先保持 `enabled` 为 `false`。`agents/example.json` 里这项和 `evolve.enabled` 仍是 `false`，`only` 仍是 `[]`。不改这些项时，行为和以前一样：技能关着，提示词里没有目录，也不会改技能文件。

自带的技能：`progress-table`（查进度表，只读多维表格）、`meeting-minutes`（整理会议纪要，只组织文字）。另外六份是创作流程，同样要自己打开：`topic-ideation`（选题打分）、`short-video-script`（口播稿）、`storyboard`（分镜表）、`aigc-prompt-pack`（不绑定工具的提示词）、`creative-brief`（项目策划书）、`post-mortem`（复盘）。步骤和每份技能的短对话见 [docs/技能.md](../docs/技能.md)。

只要这六份、不要进度表和会议纪要时，在你自己的配置里写成：

```json
"skills": {
  "enabled": true,
  "only": [
    "topic-ideation",
    "short-video-script",
    "storyboard",
    "aigc-prompt-pack",
    "creative-brief",
    "post-mortem"
  ]
}
```

`only` 保持 `[]` 再把 `enabled` 改成 `true`，则文件夹里八个合法技能都会进目录。写入飞书仍走确认码，不因打开技能而放宽。

## 谁可以私聊

私聊要先把 `features.p2p` 设为 `true`。关掉之后，下面这些名单都不生效，私聊一律不回。

谁能得到回复，按这个顺序看：

1. `p2p.open_to_all` 为 `true`：谁私聊都回。这一项优先。和下面的群成员开关同时打开时，`--check` 会提示仍由 `open_to_all` 决定谁能私聊。
2. 这个人在 `p2p.allow_open_ids` 里，**或者**在 `write.allowed_users` 里。两份名单是「或」的关系，写在其中一份即可。
3. `p2p.allow_group_members` 为 `true`，并且这个人**当前**是机器人所服务的任意一个群的成员。

都不满足：不回复，也不调用模型。

`p2p.allow_open_ids`：允许私聊的人的编号列表。可以是空列表 `[]`。

`p2p.open_to_all`：默认 `false`。为 `true` 时谁都能私聊。不在 `allow_open_ids` 里、也不在写入白名单里、又不是所服务群当前成员的人，只能聊天，不能调用飞书工具或技能。模型工作区仍是知识库，一般不要对所有人开放。这项工具限制只作用于私聊。已认群里的成员 @ 机器人，仍可查群历史、读文档、查日历和表格；写入仍要写入白名单和 6 位确认码。

`p2p.allow_group_members`：默认 `false`。不写或为 `false` 时，不会去查群成员，私聊范围只看上面两条。为 `true` 时，第 3 条生效。凭群成员身份进来的人，和写在 `allow_open_ids` 里的人一样，可以使用已经开启的飞书工具和技能；写入仍要写入白名单和 6 位确认码。

所服务的群，和群里会不会回答是同一套。`chat_ids` 写了非空列表时，就是这几个群（这时自动认群不生效，私聊也不把别的群算进来）。`chat_ids` 为空且自动认群打开时，是已经认下的群。待认、已离开、已忘群都不算。几个群的成员放在一起看，在其中任何一个群里即可。

`p2p.member_cache_ttl_sec`：每个群的成员名单缓存多少秒。不写、写错或负数都是 `600`。写成 `0` 表示每次需要核对时都重新拉。启动后会在后台先拉一遍。缓存没过期时不再打接口。同一条私聊里，每个群最多刷新一次；同时来的几条私聊共用这一次，不会对同一个群打两次。

成员变化多久生效：进群、退群不会立刻生效。缓存没过期之前仍用上一份成功的名单，所以最迟大约 `member_cache_ttl_sec` 秒，到下一次刷新才看得到。开放平台里新开通的 `im:chat.members:read` 也是下一次拉取时生效，不用为了这个权限再改别的键。配置文件本身改完仍要重启机器人才读到新键。

查成员以机器人身份调用 `lark-cli im +chat-members-list --as bot --page-all`（接口是 `im/v1/chats/{chat_id}/members`，`member_id_type=open_id`），每一页都取完。失败就拒绝，不用半份名单放人进来。接口报错、超时、缺少 `im:chat.members:read`、名单被截断或没翻完，都算失败。上次成功的名单最多再沿用两倍 TTL；超过之后，不在 `allow_open_ids` 和写入白名单里的人会被拒绝，并且不回复。失败时日志只有一行 `p2p member check failed`、群编号和错误码，不写访问令牌。接口不可用时，写在 `allow_open_ids` 或写入白名单里的人仍可私聊。

开关打开时，`--check` 会打印每个群的成员人数，以及这份名单是否完整；`--doctor` 会把 `im:chat.members:read` 算进所需权限。

建议先保持 `allow_group_members` 为 `false`。要开的话，先在飞书开放平台给这个应用加上 `im:chat.members:read` 并发布。

## 用哪一家模型 model_provider

放在配置最外层，和 `agent` 并列。**不写这一项时就是 `cursor`，和旧配置一样。**

| 值 | 意思 |
|---|---|
| `cursor` | 用这台电脑上的 Cursor。默认。 |
| `openai_compat` | 用你自己的 OpenAI 兼容账号。密钥不写在这里。见 [docs/模型接口.md](../docs/模型接口.md)。 |
| `deepseek`、`dashscope`、`zhipu`、`pangu` | 同上，并在 `base_url`、`model`、`api_key_env` 空着时填上该家的公开地址和变量名。已经写了的值优先。 |
| `fake` | 只给离线测试用。正常不要写。 |

## 模型 agent

| 键 | 填什么 |
|---|---|
| `mode` | `oneshot`（默认）：每题新开一个进程，和以前一样。旧配置里的 `ask`、`plan` 也还是每题一个进程，并把这个值传给 `--mode`。只有写成 `acp` 才改成常驻进程，见 [docs/常驻模式.md](../docs/常驻模式.md)。常驻只在 `model_provider` 为 `cursor` 时有用。常驻时程序固定加 `--mode ask`，模型不能改电脑上的文件。 |
| `preset` | 可选。`model_provider` 为 `openai_compat` 时写成 `deepseek`、`dashscope`、`zhipu` 或 `pangu`，用来补空着的地址和变量名。不写则不补。`cursor` 下忽略这一项。 |
| `model` | 模型名字。Cursor 默认 `grok-4.7-high-fast`。不写这一项时，Cursor 也用这个默认值。一次性模式下，如果这个模型暂时不能用，程序会自动去掉模型名字再试一次。`openai_compat` 或预设下，空着才用预设里的名字；写了就用写的。 |
| `base_url` | 只给 `openai_compat` 用。OpenAI 兼容地址，不要带密钥。例子见 [docs/模型接口.md](../docs/模型接口.md)。 |
| `api_key_env` | 只给 `openai_compat` 用。环境变量的**名字**，例如 `DEEPSEEK_API_KEY`。不要把密钥写在这里。 |
| `network_retries` | 失败后再试几次。默认 `2`。Cursor 的常驻模式不用这项。`openai_compat` 只在网络中断或 408/429/5xx 时重试，401 不重试。 |
| `max_runtime_sec` | 一道题最长多久（秒）。没写时仍是 `1800`（30 分钟），和旧配置一样。写成 `0` 表示不设硬时限，长答案可以一直做到有结果。到点就停（只在大于 0 时）。Cursor 一次性模式尽量把已经写出的部分发出去；常驻模式这一题改走一次性进程。`openai_compat` 也把已经写出的部分发出去。 |
| `stall_sec` | 多少秒完全没有新输出，就当成卡住。默认 `300`。这是发现卡死的办法，不靠上面的总时长。写成 `0` 或负数时仍按 `300`，避免把卡死检测关掉。Cursor 常驻模式下，卡住的这一题改走一次性进程。`openai_compat` 同样把已经写出的部分发出去。 |
| `progress_heartbeat_sec` | 作答过程中每隔多少秒记一条进度心跳。默认 `20`。这段时间完全没有新输出时，进度卡片会写成「已经 N 秒没有新输出」。模型仍在往外吐字时只记日志，不改卡片上的阶段。写成 `0` 则不打这条心跳。心跳本身不会把「最后一次输出」的时间刷新掉，所以卡死仍按 `stall_sec` 判断。 |
| `max_chars` | 回答最多保留多少字。默认 `3500`。模型写出的更长内容会在这里截断。 |
| `body_max_chars` | 工具结果放进提示词时最多多少字。默认 `20000`。`0` 表示不截。附件和文档还可以各自再设上限，见下面。 |
| `max_tool_rounds` | 只读工具最多连续几轮。不写是 `4`。小于 `1` 时按 `1`，查一次就回答。每一轮里可以按顺序执行多条只读调用，每条仍做原来的校验。每轮都会告诉模型还剩几轮。写操作不占「再读一轮」：同一轮里一旦提议写入就停，后面的调用不再执行，等确认码。轮数用尽时，如果模型只吐出工具行、没有正文，会说明这几步已经查完，并附上已读内容的摘要，摘要里不带消息编号。 |
| `crew` | 复杂问题交给主理人和只读专员。**默认关。** 不写或 `enabled` 为 `false` 时，回答路径和以前一样。打开后，长问题或同时要做几件事才会拆成查资料、读文档、起草。短句不拆。专员不能调用写入工具。总预算不写时是 16 轮、40 万 token、900 秒；每一步不写时是 6 轮、12 万 token、240 秒。写 0、负数或过大时分别回到默认或上限。说明见 [docs/主理人与专员.md](../docs/主理人与专员.md)。 |
| `tool_context_budget_chars` | 多轮工具结果重新发给模型时，加起来最多多少字。不写是 `120000`。超过时先把较早的结果压成短摘要，仍然超过就截断并注明，不会因此报错。`0` 表示不设预算。写错或负数按 120000。 |
| `reply_chunk_chars` | 一条飞书消息最多多少字。默认 `3500`。只有回答比这个长时才拆成多条，每条开头写（1/N）。`0` 表示不拆。不改 `max_chars` 时，回答本来就不超过 3500 字，仍然是一条。想发出更长的回答，先把 `max_chars` 调大。 |
| `acp_max_sessions` | 常驻时最多保留几个话题会话。默认 `8`。超出就丢掉最久没人问的那个。只在 `mode` 为 `acp` 时有用。 |
| `acp_idle_sec` | 一个话题多久没人问，就丢掉这个会话。默认 `1800`（30 分钟）。下一问重新开会话。 |
| `acp_allow_web` | 常驻时是否允许上网。默认 `true`。只放行上网搜索，以及打开 http/https 公网网页，并且只选「允许这一次」。本机、内网地址不放行。改成 `false` 则上网也拒绝。 |
| `acp_web_max_per_turn` | 一轮问答里最多放行几次上网。默认 `15`。超过就拒绝。只在 `acp_allow_web` 为 true 时有用。 |

写飞书仍然只走 `<<TOOL>>`、白名单和 6 位确认码。常驻进程里，改文件、删文件、移动、执行命令这些权限请求一律拒绝。上网搜索和打开公网网页按上面两项放行，不会选「以后都允许」。

额度想宽一点，又不改这里的默认值，看 [docs/宽松配置示例.md](../docs/宽松配置示例.md)。只读轮数、附件数、PDF 页数、文档字数、群历史行数、搜索和日历和表格的字数、一条短期记忆的字数、多轮工具结果的总预算，都可以调大。不抄那段时，上面的默认仍然有效。确认码和写入白名单不在那段里放宽。

`python agentbot.py agents/<名字>.json --check` 按 `model_provider` 检查：

- `cursor` 且 `mode` 为 `acp`：真的启动一次常驻进程，做 initialize 握手。成功是 `OK   acp`，失败是 `FAIL acp` 加原因。
- `openai_compat`：看环境变量在不在（只报变量名，不打印值），再发一个很短的流式请求。成功是 `OK   openai_compat`。

配置文件里没有账号、没有密码、没有密钥。`api_key_env` 只是变量名。Cursor 的额度算在运行 `cursor-agent login` 的那个人头上。`openai_compat` 的额度算在那个环境变量对应的账号上。

从示例生成一份新配置，并看计划任务命令（默认不写文件）：

```text
python setup_agent.py --name demo --provider deepseek --dry-run
```

`--write` 只在 `agents/<名字>.json` 还不存在时创建。不要用 `--api-key`。

只想先看 JSON 写得对不对、有没有把密钥写进文件，可以不连飞书：

```text
python checks/check_config.py agents/example.json
```

它按 `agents/config.schema.json` 检查已经写了的键。缺了的键不算错，不认识的新键先留着。类型不对、`api_key_env` 不像变量名、`base_url` 里夹了密钥，会打印「错误」并以失败退出。从示例复制出来的文件里如果还留着 `REPLACE_`，只打印「提示」，检查仍然通过。`example.json` 本身允许这些占位。

## 脱敏和红线

`redact_file`：客户名名单的文件名，默认 `redact.txt`，放在 `base_dir` 里。一行一个名字。复制 `redact.example.txt` 再填。名单为空时，只打码手机号、证件号、邮箱、密钥样子的字符串和电脑路径。

`policy.redlines`：话题红线。**默认是空列表，不拦截任何话题。** 框架里不写死「不许聊什么」。想加规则时，照下面的例子写（这只是例子，关键词请换成你自己要限制的）：

```json
"policy": {
  "redlines": [
    {
      "name": "薪资与报价",
      "keywords": ["薪资", "工资", "报价单"],
      "action": "refuse",
      "apply_to": ["input", "output", "memory", "progress"],
      "reply": "这个话题请直接找负责人沟通。"
    }
  ]
}
```

- `action` 为 `refuse`：入口直接拒答。`drop`：只在出口删掉命中的段落。
- `apply_to` 决定在哪生效：`input` 入口、`output` 出口、`memory` 不记、`progress` 进度卡片里不显示、`kb` 知识库同步时删段落。不写 `apply_to` 则每一处都生效。
- 旧键 `taboo_keywords` 还能认，新配置不要再用。

`help_pattern`：对方问「你能干什么」时，用这段规则判断，然后直接回复 `texts.help`，不去叫模型。看不懂就保持例子里的原文。

## 工具 tools

每一项的 `enabled` 为 `true` 才允许模型使用。没配好编号时，调用会告诉对方「还没配置」，不会乱写。

| 键 | 作用 |
|---|---|
| `history` | 读本群最近几天的消息，包含话题里的回复。关键词不区分大小写。图片、文件、富文本、合并转发会留占位（如 `[图片]`）。`days` 默认 7，`max_pages` 默认 2。`page_size` 不写是 `50`，停机补答拉消息也用这个数；小于 1 或写错时按 50。`max_lines` 不写是 `150`，超过时注明还剩几行；写成 `0` 表示不截断，写错或负数按 150。私聊里不提供。 |
| `docs_search` | 搜索已分享给机器人的飞书文档。`max_chars` 不写是 `4000`。`0` 表示不截断。写错或负数按 4000。 |
| `docs_read` | 读一份文档。`allow_tokens` 为空表示：分享给机器人的都能读。想限制就填文档编号。`max_chars` 是最多读多少字，没写时默认 `20000`。超过上限时保留开头、中段和结尾，并注明全文长度，方便分段概括，这时才标「节选」。没超过上限时不标「节选」。聊天附件的 `file_`、`img_` 编号会被拒绝，并说明这不是云文档。 |
| `calendar_read` | 读日历。`calendar_id` 可空，空则用下面 `write.resources.calendar_id`。`max_chars` 不写是 `4000`。`0` 表示不截断。写错或负数按 4000。 |
| `base_read` | 读多维表格。`base_token`、`table_id` 换成你的表。`search_fields` 是可搜索的列名，没有就留 `[]`。`max_chars` 不写是 `5000`。`0` 表示不截断。写错或负数按 5000。 |
| `attachment` | 下载图片和文件。`max_mb` 是单文件上限，默认 20。`max_chars` 是提取出的正文最多多少字，没写时跟 `agent.body_max_chars`（默认 `20000`）。能读：纯文本（txt、md、csv、json、log 等）、常见代码文件、PDF、`.docx`、`.pptx`、图片（png、jpg、gif、webp、bmp，要开 `features.vision`）。`.docx` 和 `.pptx` 只用标准库。PDF 需要 `pypdf`，按页抽文字；没装会说明请安装或另存成文本。某一页没有文字时，会抽出前 `pdf_scan_pages`（不写时是 10；配置里写了 3 就仍是 3）页里内嵌的 JPG、PNG 或 BMP 交给模型看，张数不超过 `pdf_max_images`（不写时是 3）。发给模型的说明写的是这个实际张数，不另写死一个数字。抽不出就请对方把那一页导出成图片。不渲染整页，也不需要 Poppler。`.xlsx` 在装了 `openpyxl` 时读取，没装会说明读不了，并建议另存 CSV。旧格式 `.doc`、`.ppt`、`.xls` 会请对方另存为对应的新格式。zip 会先列目录，再读取其中支持的文件；默认最多列出 `zip_max_files`（30）项、读取 `zip_max_read`（8）个，解压总体积不超过 `zip_max_mb`（40）。路径里带 `..`、绝对路径、压缩比异常或内层 zip 都会跳过。音频和视频只说明类型，不听不看。下载后的文件会尽量改成消息里的原文件名，而不是 `file_key`。这些上限没写进配置时用括号里的默认值。 |
| `message_attachment` | 读取当前会话里历史消息的附件。可以传一个 `message_id`，也可以传 `message_ids` 列表。列表里的每一条都单独核对会话和时间，结果分开标注；某一条对不上不影响其他条，也不会下载那一条。下载前和下载后都会核对消息编号和会话。模型只能用本群历史里给出的消息编号。没写这项时，跟着 `attachment.enabled`。写了 `enabled` 就以写的为准。`max_per_answer` 不写是 `4`，限制的是读进这一次回答的文件数。同一轮里的多条只读调用按写出的顺序逐个执行。 |
| `kb_read` | 按相对路径读取知识库里的 md 或 txt。不写这项时可以读。写成 `{"enabled": false}` 就关掉。`max_chars` 默认 `8000`。跳不出知识库目录。 |
| `evidencegate_check` | EvidenceGate 门禁：校验文档 AI（OCR）输出，返回三路由（ACCEPT_CANDIDATE / HUMAN_REVIEW / MODEL_OUTPUT_INVALID）与字段证据。默认关，`enabled: true` 才可用。可选 `schema` 换门禁契约 JSON 的实例内相对路径，`node` 换 Node 可执行文件。只读，不改业务。见 skills/evidencegate-ocr/SKILL.md。 |
| `decision_gate_check` | juchang 决策门禁查询：按「证据状态×动作等级×可逆性」算出写动作的路由（automatic / after_approval / manual_only / blocked）与理由。默认关。只读，分数只排先后不给许可。脚本固定在 skills/juchang-decision-gate/scripts/。 |
| `evidence_replay_check` | 证据回放核对：校验回放归档的三模式标签、哈希与缺口登记，输出 pass / fail。默认关。只读，通过只证明归档与登记一致。见 skills/juchang-evidence-replay/SKILL.md。 |
| `receipt_verify` | Matrix 回执核验：离线校验 caller 提供的 accepted@2 导出，结果只证明内部一致，不证明来源真实。默认关，且只对 Matrix 生态的导出有用。 |
| `web` | 只影响常驻模式里「打开网页」。`allow_fake_ip_ranges` 默认 `["198.18.0.0/15"]`。Clash 这类假 IP 代理会把公网域名解析到这个段。用域名访问、并且两次解析都落在这段里时放行。网址里直接写 `198.18.x` 仍然拒绝。`127/8`、`10/8`、`172.16/12`、`192.168/16`、`169.254/16`、`100.64/10`、`::1` 一律拒绝，写进这个列表也不放行。跳转每一跳都按同一规则检查。没写 `web` 时也是这个默认。写成 `[]` 或 `false` 就连假 IP 段也不放行。 |
| `docs_create` | 在专用文件夹新建文档。要确认码。 |
| `docs_append` | 在白名单文档末尾追加。要确认码。 |
| `calendar_create` | 在团队日历建一个日程，不邀请任何人。要确认码。 |
| `calendar_create_batch` | 一次提议多个日程，一个确认码确认全部。说明里会列出每一条。`write.max_batch` 默认 10。没写这项时，跟着 `calendar_create` 的开关。 |
| `calendar_update` | 修改已有日程（标题、时间、说明）。命令里固定不通知参会人，也不能改参会人。要确认码。没写这项时，跟着 `calendar_create`。 |
| `calendar_delete` | 删除已有日程。同样不通知参会人。要确认码。没写这项时，跟着 `calendar_create`。写了 `enabled: false` 就关掉，不会跟着建日程一起开。 |
| `base_create` | 在表格里加一条记录。要确认码。 |

`agents/example.json` 里 `evidencegate_check`、`decision_gate_check`、`evidence_replay_check`、`receipt_verify` 四项都是 `"enabled": false`。它们是主程序的只读配套，本地控制面的清单里没有它们。

飞书接口报错时，会先看 stdout，没有 JSON 再看 stderr。文档不存在、编号不是云文档、没有权限、权限未开通，会分别说明，而不是都说成「接口暂时不可用」。

回复或引用一条文字、富文本、卡片时，原文会交给模型。帖子里的图片会一起下载。合并转发只展开一层，内层转发不再继续请求；平台不让看时，会说明看不到明细。已经答过的话题里，如果只是接着发文字、并且父消息就是话题根，不会为了追问再去取一次根消息。第一次回复一条文件（文件本身就是话题根）仍会下载。

`notify_all` 只在对方原话里写了 @全员、@所有人、通知全员、通知所有人、提醒全员、告知全员或艾特全员时才会在**确认成功后的回复**开头 @全员。它不是日程邀请。模型自己把开关打开、对方没说，也不会 @。

工具名字是 `docs_search`、`docs_read`、`docs_create`、`docs_append`（docs 带 s）。旧名字 `doc_search`、`doc_read`、`doc_create`、`doc_append` 仍会按新名字读取。`write.resources` 里的 `doc_folder_token`、`doc_append_tokens` 同样，对应现在的 `folder_token`、`docs_append_tokens`。两边都写了就用新名字。`python agentbot.py 配置.json --check` 会打出 `HINT` 提醒改掉，这行不算失败。

## 写入 write

三道锁都要过，才会真正改飞书。详见 `docs/安全红线.md`。

| 键 | 填什么 |
|---|---|
| `enabled` | `true` 才允许提议写入。升级时可以先改成 `false`，等只读稳定了再开。 |
| `confirm_ttl_sec` | 确认码有效秒数，默认 `300`（5 分钟）。确认码写在 `state/state.db`，进程重启后、过期之前仍然有效。过期或用过就从待确认里删掉。过期的会在本机 `state/confirm_expired.jsonl` 记成 `expired`，见下面「确认超时与待确认队列」。 |
| `escalate` | 确认超时后要不要私聊提醒。不写或 `enabled` 不是 `true` 时不发消息。细节见下面一节。 |
| `allowed_users` | 谁可以发起写入、谁可以改群记忆。左边是这个人的编号，右边是称呼，例如 `"REPLACE_USER_OPEN_ID": "小李"`。右边的称呼只用于回复和审计，改成真人的称呼。 |
| `resources.folder_token` | 专用文档文件夹的编号。新建文档只进这个文件夹。 |
| `resources.docs_append_tokens` | 允许在末尾追加的文档编号列表。空列表表示还不能追加。 |
| `resources.calendar_id` | 专用日历的编号。 |
| `resources.base_token` / `table_id` | 允许新增记录的那张表。读和写可以用同一张，也可以分开。 |
| `base_time_field` | 加记录时，如果没有这一列，就自动填上当前时间。不需要就改成 `""`。 |
| `base_select_fields` | 飞书里的单选列。程序会把纯文字包成列表再写入，否则飞书会报格式错误。例子里是「状态」。你的表没有单选列就改成 `[]`。 |
| `max_batch` | 一次批量建日程最多几条。默认 `10`。 |
| `decision_gate` | 写提案决策门禁（juchang-decision-gate），默认关。`enabled: true` 并在 `tools` 里声明哪些写工具过门禁、各是什么等级（如 `"docs_create": "L2"`，只能是 L1/L2/L3；写错时该写动作被拒绝，宁可挡住也不猜）。propose 阶段自动过门：`blocked` 拒绝提案并说明依据，`manual_only` 拒绝代做（提示人工操作），其余放行进既有确认流——门禁只能加严不能放宽，`automatic` 仍需发起人确认。证据状态优先取本会话近期 `evidencegate_check` 的路由，没有或过期用 `evidence_default`（默认 `sufficient`，`evidence_window_sec` 默认 900）；来源连同等级、路由、审批模式一起写进审计。没在 `tools` 里点名的写工具不过门禁；不想过门就删掉整个 `decision_gate` 段，行为回到从前。路由给出 `approval: dual`（critical 影响的动作常见）时启用双人复核：发起人回复「确认 码」只记下不执行，需另一位写入白名单管理员在同一会话内回复「复核 码」才真正执行；发起人自己复核不算，复核人不在白名单被拒并留痕，取消不挡（发起人随时可「取消 码」）。复核码与确认码共用同一套时效与一次性约束，审计链依次落 `write_confirmed`（dual first / dual second）与 `write_done`。试运行只挂 `docs_create` 与 `base_create` 为字符串 `L2`，见下一节。第二位默认是白名单里任意另一位；要按星期和时段指定，用下面的 `review_roster`。 |
| `review_roster` | 双人复核值班表，默认关。不写，或 `enabled` 不是 `true`，第二位仍是任意另一位 `write.allowed_users` 管理员，和现在一样。`enabled: true` 之后只能收窄：复核人必须是当前时段值班、并且也在写入白名单里的另一位管理员。值班表不能把白名单外的人放进来，不能代替发起人确认，也不会把日常的 `"L2"` 抬成 dual。怎么填、怎么回滚见下面「复核值班表」。 |

这些编号都不是密钥，但它们指向你的真实文档和表。不要把填好的配置发到公开的地方。

### 决策门禁 L2（幕幕与 Mimi 同一段）

这道门插在「已经通过写入白名单、还没发确认码」的位置。它只加严：阻断或拒绝代做时提案发不出去；放行时仍要发起人本人用确认码或卡片点头。确认不能关。默认关着。`agents/example.json` 里整段 `enabled` 是 `false`，仓库默认不打开。

这一轮只挂两个写工具，等级都写成字符串 `L2`（公开修改）。追加文档、建日程、改日程、删日程、批量建日程、群记忆提案都不写进 `tools`，它们继续只过原来的白名单和确认。不要把某一项写成对象去改 `impact`。字符串 `L2` 由程序推导成可直接撤销、单一对象、可能发生、中影响；审批模式是负责人批准（`named`），执行路由是批准后执行（`after_approval`），发起人本人确认一次即可。把 `impact` 覆盖成 `critical` 会让审批模式变成双人复核（`dual`）：发起人回复「确认 码」只记下不执行，另一位写入白名单管理员在同一会话回复「复核 码」才执行。这位默认是白名单里任意另一位；`write.review_roster` 打开后还必须是当前值班的人，见下面「复核值班表」。值班表不把字符串 `L2` 抬成 dual。双人复核已经实现；这一轮试运行保持字符串 `L2`，不走到那条路。

打开时改实例自己的配置（填好的 json 不进仓库），在已有的 `write` 里加上：

```json
"decision_gate": {
  "enabled": true,
  "tools": {
    "docs_create": "L2",
    "base_create": "L2"
  },
  "evidence_window_sec": 900,
  "evidence_default": "sufficient"
}
```

`tools.decision_gate_check.enabled` 设为 `true` 时，模型可以只读查询一条路由，查询本身不写飞书。写提案过门不依赖这个开关，程序直接调用 `skills/juchang-decision-gate/scripts/run-decision-gate.mjs`。想让证据状态来自票据门禁时，把 `tools.evidencegate_check.enabled` 也设为 `true`。三个开关可以分开开。

证据状态记在本进程内存里，按会话记最近一次 `evidencegate_check`，不落盘。`evidence_window_sec` 不写是 `900`（秒）。窗口内：`ACCEPT_CANDIDATE` 当作依据完整，`HUMAN_REVIEW` 当作依据不完整，`MODEL_OUTPUT_INVALID` 当作缺少依据。依据不完整、冲突或缺少时，L2 提案被阻断，对方看到「决策门禁阻断」和证据来源。没有记录、记录已过期，或票据门禁没开时，用 `evidence_default`（不写是 `sufficient`，普通新建文档和加记录仍进入确认）。审计里的 `evidence_source` 是 `evidencegate:ACCEPT_CANDIDATE`、`evidencegate:HUMAN_REVIEW`、`evidencegate:MODEL_OUTPUT_INVALID` 或 `default`。写成 `0` 或负数时，本进程里已有的记录不过期。重启后内存记录清空，下一次写入回到默认，直到这一会话又跑过票据门禁。

和确认码、白名单的关系：

- 人不在 `write.allowed_users` 里时，在进门禁之前就拒绝。审计是 `write_denied`，对方看到「你不在写入白名单里」。门禁不加人，也不把谁移出白名单。
- 放行后的确认码、卡片、有效期、发起人本人、原来的会话，仍按 [docs/确认方式.md](../docs/确认方式.md) 和 [docs/安全红线.md](../docs/安全红线.md)。门禁不发码、不消耗码、不代替点头。
- `tools` 里没点名的写动作不过这道门，确认码照旧要。
- `tools` 必须是对象。写成列表时程序当成没声明任何工具，门禁等于没挂上，写入仍只靠白名单和确认码。
- 等级只接受 `L1`、`L2`、`L3`。写成别的，该动作被拒绝（fail closed），对方看到等级不合法。这一轮两项都写 `L2`。依据完整时 `L3` 会拒绝代做，提示管理员自己在飞书里操作。

回滚：从实例配置里删掉 `write.decision_gate` 整段，然后按现有办法平滑重启（`scripts\reload.ps1`）。删段之后，新建文档和加记录回到只有白名单和确认码，审计里的 `write_proposed` 不再带 `gate`。只读查询要一并关掉时，把 `tools.decision_gate_check.enabled` 改回 `false`。不要为了回滚去改程序默认值。

试跑：本机要有 `node`，实例目录里要有上面那个脚本。脚本缺失或跑失败时，挂了门的 `docs_create` 和 `base_create` 提案发不出去，对方看到「决策门禁脚本…」；没挂上的写工具不受影响。改完要重启进程才读到新段。不要往正式群发测试消息。看 `audit/` 里当月的 jsonl：依据完整时期望 `write_proposed` 的 `gate.level` 为 `L2`、`gate.execution` 为 `after_approval`、`gate.approval` 为 `named`，确认码或卡片仍要发起人本人点头。依据不完整时期望 `write_blocked`，且 `gate.evidence` 为 `partial`。回滚并重启后再提议一次新建文档，确认 `write_proposed` 没有 `gate`。

### 复核值班表

`write.review_roster` 只在门禁已经要求双人复核时起作用。它回答「第二位是谁」，不回答「要不要双人」。日常写工具写成 `"L2"` 时，影响仍是 medium，审批仍是负责人批准，一个人确认就执行。打开值班表不会把这条抬成 dual。确认也不能靠它关掉。

不写这一段，或 `enabled` 不是 `true`，行为和现在一样：另一位写入白名单管理员都可以复核。

打开之后，复核人要同时满足三件：不是发起人、在 `write.allowed_users` 里、并且落在当前时段的某个班次上。三件缺一件都不执行。只写在值班表、不在白名单里的人，跟白名单外的人一样被拒绝。这一时段的班次上如果没有人同时在白名单里，就当没有可复核的人，宁可挡住，不会退回「白名单里随便哪一位」。班次写错、对不上时段、`utc_offset_hours` 不是 -12 到 14 的整数，也是没有人能复核。

时间按复核那一刻算，不按发起那一刻。不写 `utc_offset_hours` 时，用运行机器人的那台电脑的本地时间。写了就是相对 UTC 的小时数（东八区写 `8`），不是在本地时间上再加 8。`weekdays` 用 1 到 7，1 是周一，7 是周日。`start` 含在班次里，`end` 不含。`end` 可以写成 `24:00`，表示当天结束。`end` 早于 `start` 表示跨过午夜：周五 `18:00` 到 `09:00` 覆盖周五晚上和周六早晨。早晨算前一天的班次，所以「只写了周一」的跨夜班盖不住周一早晨；要盖住周一早晨，把周日写进那个班次。

回复里只出现白名单里的称呼，不出现人的编号。一位可以排多个班次，一个班次可以有多位。`open_ids` 换成 `allowed_users` 里已经有的编号。示例里的 `ou_placeholderreviewa` 只是占位，不能拿去上线。

回滚：把 `enabled` 改成 `false`，或删掉整个 `review_roster`，然后重启。双人复核本身还在（只要门禁仍给出 dual），第二位恢复成任意另一位白名单管理员。不想要双人复核，按 [双人复核离线演练.md](../docs/双人复核离线演练.md) 把那个写工具的影响改回去，不要用值班表去关确认。

```json
"review_roster": {
  "enabled": false,
  "utc_offset_hours": 8,
  "slots": [
    {
      "weekdays": [1, 2, 3, 4, 5],
      "start": "09:00",
      "end": "18:00",
      "open_ids": ["ou_placeholderreviewa"]
    },
    {
      "weekdays": [1, 2, 3, 4, 5],
      "start": "18:00",
      "end": "09:00",
      "open_ids": ["ou_placeholderreviewb"]
    }
  ]
}
```

### 确认超时与待确认队列

时效不另设一套。确认码用上面的 `confirm_ttl_sec`（不写是 300 秒），按钮用 `confirm.ttl_sec`（不写是 600 秒）。到点还没确认：这次不执行，确认码作废，审计记一行 `write_expired`。同时往本机 `state/confirm_expired.jsonl` 追加一条，`status` 为 `expired`。这个文件在 `state/` 里，不入库。同一次超时只记一条，重启不会再刷一条，也不会再发一次提醒。

只读查看还没确认的提案，以及近期过期的记录（没有确认码、按钮记号、写入参数，也没有 open_id 明文）：

```text
python pending_queue.py <实例目录>
python agentbot.py <配置>.json --doctor
```

`--doctor` 多一行 `pending`，只报条数和工具名。读不到队列时这行是 `WARN`，不因此判失败，也不新建数据库。MCP 控制面多一个只读工具 `list_pending`（不起这个进程就没有）。三处都不能代为确认。

可选提醒写在 `write.escalate`。默认关。不写、`enabled` 不是 `true`、或 `notify` 为 `none` 时，超时只留本机日志和状态文件。

| `notify` | 发给谁 |
|---|---|
| `owner`（不写也是这个） | 主人私聊。名单和用量周报相同：先用 `report.owner_open_ids`，空着再用 `alerts.owner_open_ids`。不要求断线提醒已经打开。 |
| `initiator` | 私聊发起人本人。 |
| `both` | 上面两边。同一个人只发一条。 |
| `none` | 仍然不发。 |

没有可用的私聊对象时，不改发到群里，日志里留一句，状态文件记 `no_route`。群号（`oc_` 开头）和 `REPLACE_` 占位符不会被当成接收人。演练（dry-run）也不发。确认码、双人复核、白名单都不因这项打开而变化。

## 确认 confirm

怎么点头。不写这一段时，默认点卡片上的按钮。飞书还没开通卡片回调时，自动改回确认码，旧配置不用改。确认不能关掉。细节见 [docs/确认方式.md](../docs/确认方式.md)。

| 键 | 填什么 |
|---|---|
| `mode` | `button`（点按钮，默认）、`code`（6 位确认码）、`button_or_code`（两种都行）、`button_and_code`（两样都要）。写成关掉也会按 `button`。 |
| `high_risk_mode` | 批量建日程、改功能开关、重启这一类用哪种。不写时和 `mode` 相同。 |
| `ttl_sec` | 按钮有效秒数。不写是 `600`（10 分钟）。 |
| `code_ttl_sec` | 确认码有效秒数。不写时用上面的 `write.confirm_ttl_sec`。 |
| `code_digits` | 确认码位数，4 到 8。不写是 `6`。 |
| `card_callback` | `auto`（不写也是这个）、`on`、`off`。`auto` 会在启动前看飞书有没有开通卡片回调；没开通就不起这个接收进程，确认改用确认码，并且只私聊提醒主人一次。`on` 总是去启动，没订阅则退出后不再重启。`off` 不启动，确认用确认码。旧配置不用加这项。 |

## 进度卡片 progress

`enabled` 默认 `false`：不发表情、不发「处理中」卡片，直接等答案。升级时先保持关闭，只读跑稳了再改成 `true`。

打开后需要权限：表情 `im:message.reactions:write_only`，更新消息 `im:message:update`，卡片 `cardkit:card:write`。`delete_status_after_reply` 为 true 时还要撤回权限 `im:message:recall`。缺了也不会崩，只是没有进度提示，或者撤回失败时改成「已完成」。

| 键 | 含义 |
|---|---|
| `mode` | `card` 是一张卡片（思考过程默认收起）。`text` 是一条文字，答完后这条文字会被换成答案。 |
| `reaction` | 收到问题时贴的表情，默认 `OnIt`。 |
| `done_reaction` | 答完换成的表情，默认 `DONE`。 |
| `status_message` | 要不要发进度消息。 |
| `delete_status_after_reply` | 默认 `false`。为 `true` 时，答案另发一条消息之后，撤回那条「处理中」状态消息（只撤机器人自己发的那条）。撤回失败就改成「✅ 已完成」。`false` 时仍是改成「✅ 已完成」。`text` 模式如果已经把状态消息换成答案，不会撤回。 |
| `thinking_panel` | 卡片里要不要「思考过程」。会先去掉路径和客户名。 |
| `thinking_chars` | 思考过程最多保留多少字。 |
| `card_interval_sec` / `card_max_updates` | 卡片多久刷新一次、最多刷新多少次。 |
| `min_gap_sec` | 两次刷新至少隔几秒。 |
| `fast_interval_sec` / `fast_phase_sec` / `slow_interval_sec` / `max_edits` | 文字模式用：前两分钟刷新密一些，之后变疏。文字消息大约只能改 20 次，所以 `max_edits` 留了余量。 |

## 固定回复 texts

对方看到的几句现成话。可以改成你的机器人的口气。

| 键 | 什么时候用 |
|---|---|
| `busy` | 这一小时问得太多，或排队满了。 |
| `wait` | 同一个人两条消息隔得太近（`rate_limit.min_gap_per_user`）。没写时用「请稍等一下，我处理完上一条就回复你。」 |
| `empty` | @ 了但没有写问题。 |
| `fail` | 模型没有给出回答。 |
| `help` | 对方问「你能干什么」。 |
| `partial_note` | 时间到了，但已经写出一部分，贴在答案后面。 |
| `stall` | 时间到了，一点文字都没有。 |
| `policy_refuse` | 命中红线、又没给那条规则单独写回复时用。 |
| `chat_pending` | 自动认群还没认这个群时，白名单成员 @ 了它（不是 `/认群`）。不调用模型。 |
| `chat_admitted` | 白名单成员发了 `/认群`。 |
| `chat_revoked` | 白名单成员发了 `/忘群`。 |

## 人设 system_prompt

模型每次都会先读这段。写成你希望它怎么说话、什么不能做。例子是一个通用助手。请改成你的机器人的名字和边界。不要写客户真名，不要写密钥，不要写电脑路径。

例子里有两句不要写反：

- **联网搜索和打开网页是模型自带的能力**，不在飞书工具表里。问比赛、新闻、日期、截止时间、政策时，先搜索，回答里给 1 到 3 个链接。不要写成「什么都只能走下面的工具」，否则它会拒绝上网。
- **飞书的读和写才只能走列出的工具。** 日程可以建、改、删，但不能邀请人。只有对方原话明确要求 @全员 或通知所有人时，才允许在确认后的日程回复开头 @全员。

## 本机日志 observability

这几份日志都只在运行的那台电脑上，不要提交，也不要外传。它们记的不是同一件事。

`observability.journal` 不写或为 `true` 时，每道交给模型的题在 `logs/journal.jsonl` 追加一行。里面只有时间、群聊或私聊、是否成功、字数、耗时、用过的工具名。没有问题原文、没有工具参数、没有回复正文、没有路径和编号。写成 `false` 就不再追加。原来的 `metric` 行仍在 `logs/bot.log` 里。升级旧配置时不用改；不想记这一行就写成 `"observability": {"journal": false}`。

`logs/calls.jsonl` 是调用链。`observability.calls` 不写，或 `enabled` 不为 `false` 时，每道交给模型的题追加一条：收到的消息、用过的技能和工具、每步耗时和 token、结果。写入前先脱敏，客户名变成「某客户」，密钥、手机号、路径和编号不留原文。`retain_days` 不写是 30，更早的行在下次写入时丢掉。写成 `false` 或 `"enabled": false` 就不记。主人在私聊里发「最近调用」或「这条怎么答的」可以看。用量周报只加一段合计，没有记录时周报正文和以前一样。说明见 [docs/调用记录.md](../docs/调用记录.md)。

`logs/events.jsonl` 是诊断日志，没有单独的开关。每道题记一条回答，每个工具记一条：消息编号、工具名、是否成功、飞书错误码、耗时。问题原文不写进去。看起来像手机号、邮箱或密钥的字符串会打码。大约 2MB 轮转，保留 5 份 `.1`。`--doctor` 不写这个文件，也不写心跳。

`python agentbot.py agents/<名字>.json --doctor` 只做只读诊断：登录、权限、事件订阅、网络、依赖、进程是在跑还是已停、最近一次成功应答的时间、最近一条失败（一句，不打堆栈），以及通过、警告、失败项名单。时间从 `logs/events.jsonl` 和 `logs/journal.jsonl` 读，原因不够时才看 `logs/bot.log` 的最后一条 ERROR。不发消息，不启动收消息的进程，也不写这些文件。Windows 上部署之后可以用 `powershell.exe -File scripts\verify_windows.ps1` 再看一遍本机进程和最近的 `logs\events.jsonl`。这个脚本只在 Windows 上读本机进程。

## 断线提醒 alerts

默认关。不写这一段，或 `enabled` 不是 `true`，就不会发私聊，也不会写 `logs/alerts.log`。长连接断了而进程还在时，心跳文件仍会更新，看门狗不会因此重启。打开后，进程每隔大约 15 秒看一次连接；连续不健康达到阈值才通知主人，恢复后再发一条。发送走当前渠道的主动发送。飞书是 `im +messages-send`，不依赖事件长连接，也不启动收消息进程。看门狗只在进程不在或心跳超过 3 分钟、并且这项开着时，于重启前再通知一次。

| 键 | 默认 | 填什么 |
|---|---|---|
| `enabled` | `false` | `true` 才通知。 |
| `owner_open_ids` | `[]` | 主人的 open_id，可以多位。空着只写本机日志。`REPLACE_` 开头的会丢掉。 |
| `unhealthy_after_sec` | `180` | 连续不健康多少秒才发第一条。`0`、负数或写错仍按 180。不要写得比 180 大，否则进程死掉时看门狗会先重启，死亡告警可能来不及发。 |
| `repeat_sec` | `1800` | 仍未恢复时，最少隔多少秒再提醒。`0`、负数或写错仍按 1800。 |
| `restart_window_sec` | `21600` | `--doctor` 里 `restart` 那一行的统计窗口（秒）。没写是 6 小时，最多 7 天。只影响诊断怎么说，不改重启行为。 |
| `restart_warn_after` | `3` | 窗口内 consumer 退出够几次才 `WARN`。写 `0` 表示这条不提醒。够阈值只是 `WARN`，不判失败，也不发消息。 |
| `local_log` | `true` | 写 `logs/alerts.log`。里面没有 open_id。 |
| `windows_toast` | `false` | `true` 且飞书没发给每一位主人时，Windows 上再弹一次本地通知。 |

权限仍是回复消息已经需要的 `im:message:send_as_bot`。不用打开 `features.p2p`。主人要在可用范围里；如果提示不在会话里，先让主人给机器人发一条私聊。细节见 [docs/断线提醒与晨报.md](../docs/断线提醒与晨报.md)。

## 早晨摘要 digest

默认关。只有 `enabled` 为 `true` 才发。到点后每个群、每个本地日最多一条，重启也不会再发。正文不调用模型，不点名所有人。`chat_ids` 还得落在服务范围内：顶层 `chat_ids` 非空时只用那份；留空时用已经认下的群。播报是另一项，见下一节。播报不读这里的日历和任务表。默认也关。

| 键 | 默认 | 填什么 |
|---|---|---|
| `enabled` | `false` | `true` 才到点发送。 |
| `time` | `08:30` | `HH:MM`。写错就不发。 |
| `timezone` | `Asia/Shanghai` | 认不出来的时区不发。Windows 上没有时区数据时，上海、重庆、哈尔滨仍按东八区。 |
| `chat_ids` | `[]` | 要接收的群。空着不发。`REPLACE_` 开头的会丢掉。 |
| `window_min` | `30` | 到点之后多少分钟内还可以补发。`0` 表示只在那一分钟。负数按 30。 |
| `include_calendar` | `true` | 读今天的团队日历。编号用 `tools.calendar_read.calendar_id`，没有再用 `write.resources.calendar_id`。 |
| `include_tasks` | `true` | 读任务表里还没完成的行。编号用 `tools.base_read` 的 `base_token` 和 `table_id`。 |
| `status_field` | `状态` | 用这一列判断完成了没有。必须整格相同，不会把「未完成」当成「完成」。 |
| `title_field` | 空 | 空着就从「任务 / 标题 / 名称 / 事项」里找。 |
| `done_values` | 见例子 | 算作做完的状态。不写这个键时用例子里的那一份。 |

日历或任务表是空的、或仍是 `REPLACE_` 时，当成没配置，不会去读。两段都没有就不发。读失败不会把接口原文发进群。

群里需要机器人已经在里面。权限：`im:message:send_as_bot`。日历编号是真的才需要 `calendar:calendar.event:read`；任务表编号是真的才需要 `base:record:read`。改完要发布版本。演练、自检和 `--doctor` 不发摘要。

## 播报 broadcast

默认关。这是另一条主动发到群里的消息，和早晨摘要分开。不写这一段，或 `enabled` 不是 `true`，就不发，`/状态` 也不多这一行。不调用模型，不读日历，不读任务表。私聊里的「设置」卡片不包含这一项，要在自己的配置文件里打开。

到了 `time`（不写是 `09:00`，时区不写是 `Asia/Shanghai`）之后的 `window_min` 分钟内（不写是 30），给 `chat_ids` 里、并且已经在服务范围内的每个群发一条。服务范围仍是：顶层 `chat_ids` 非空时只用它；留空时用已经认下的群。只写在顶层、不写进 `broadcast.chat_ids`，不会发。只写进 `broadcast.chat_ids`、不在服务范围里，也不会发。

每个群、每个本地日最多一条，记在 `state/broadcast_state.json`。这和 `state/digest_state.json` 不是同一份。打开播报不会去读日历或任务表，也不会占用早晨摘要的名额。重启落在同一窗口里不会再发。发送明确失败会放掉名额；超时或看不懂结果就保持占坑。配置了的段全部没读到时不占坑，大约 5 分钟后再试。有一段成功就发出去，失败的那段写成「暂时没有读到」，同一天不补第二条。

不写 `source` 时，`text`、`urls`、`body_file`、`command` 里填了的都会进同一条，顺序就是这四样。`urls` 单独成「站点」一段。文件和命令的正文原样放进去，所以待审名单写在文件或命令输出里。`source` 写成 `file`、`command`、`static`、`http` 之一时，只用那一项。

| 键 | 默认 | 填什么 |
|---|---|---|
| `enabled` | `false` | `true` 才到点发送。 |
| `time` | `09:00` | `HH:MM`。写错就不发。 |
| `timezone` | `Asia/Shanghai` | 认不出来的时区不发。 |
| `chat_ids` | `[]` | 要接收的群。空着不发。`REPLACE_` 开头的会丢掉。不要把真实群号写进仓库。 |
| `window_min` | `30` | 到点之后多少分钟内还可以补发。`0` 表示只在那一分钟。负数按 30。 |
| `title` | `播报` | 标题，最长 40 字。 |
| `source` | 空 | 空着就用下面填了的每一项。写了就只留一项。 |
| `body_file` | 空 | 相对机器人目录的文本文件，例如 `broadcast/pending.txt`。绝对路径和 `..` 不读。样子在 `broadcast/brief.example.txt`。`broadcast/brief.txt` 和 `broadcast/pending.txt` 不要提交。 |
| `command` | `[]` | 程序和参数组成的数组，只取标准输出。不经过 shell。`cmd`、`powershell`、`bash` 以及 `.bat`、`.cmd`、`.ps1` 不会启动。超时不写是 8 秒，小于 1 或大于 20 都按 8。标准错误丢掉。子进程环境里不放密钥变量。 |
| `text` | 空 | 固定几行，和别的段一起发。 |
| `urls` | `[]` | 最多 5 个公网地址，作为「站点」一段。只发状态码、`ok` 或 `fail`，以及大约 180 字摘录。不跟随跳转，不带查询参数。本机、局域网、链路本地和夹带密钥的地址直接跳过，不会去连。 |
| `timeout_sec` | `8` | 命令和网页各自的超时。 |

群里需要机器人已经在里面。权限仍是 `im:message:send_as_bot`，不因为这项再要日历或表格权限。演练、自检和 `--doctor` 不发。

转塘艺讯这类群不要开早晨摘要。顶层 `chat_ids` 里已经有这个群之后，在你自己的 json（不要提交）里让 `digest.enabled` 保持 `false`，只开播报。站点健康放 `urls`，待审名单放 `body_file`。群号用你自己的，不要写进仓库。

```json
"digest": { "enabled": false },
"broadcast": {
  "enabled": true,
  "time": "09:00",
  "timezone": "Asia/Shanghai",
  "window_min": 30,
  "chat_ids": ["REPLACE_CHAT_ID"],
  "title": "艺讯播报",
  "urls": ["https://example.com/"],
  "body_file": "broadcast/pending.txt"
}
```

`broadcast/pending.txt` 里写待审那几行，例如「待审」和每条一行。仓库里没有资讯抓取。README 里的 mumu 是另一份配置，不是这段代码。`digest` 只拼日历和未完成任务。这一版的播报只发送上面准备好的正文。AI 资讯以后再做。

## 接待桥 intake

默认关。不写这一段，或 `enabled` 不是 `true`，就不会去拉任何东西，也不会写任何文件。它是这一段里唯一「收」的定时项：到点从公网 HTTPS 端点读一批合作意向，去重之后追加写进本机的待审文件，然后就没有然后了。不调用模型，不读日历，不发消息。发不发、发给谁，由人看完那个文件决定。

```json
"intake": {
  "enabled": false,
  "url": "https://example.com/leads.json",
  "token_env": "MIMI_INTAKE_TOKEN",
  "interval_min": 30,
  "timeout_sec": 8,
  "timezone": "Asia/Shanghai",
  "out_file": "intake/leads.md"
}
```

- `url`：对端地址。只认公网 http(s)，判定和播报探站点用同一把尺：内网、元数据地址、带账号密码的、地址里夹客户名或密钥的，都算「没配」，`--check` 会直说不去拉。这台机器只有出去的长连接，没有能对公网开放的入口，所以是「我们定时去取」，不是「官网往里推」。
- `token_env`：存放密钥的环境变量名。配置里只写变量名，值不进配置文件，也不写进日志和待审文件。变量名写了但变量是空的，这一轮不去拉（报 `no_token`）；变量里有换行、制表或 NUL 的，当请求头注入直接拒掉，一个字节都不发。
- `interval_min`：最短多少分钟拉一次，越界退回 30，最低 15。没到点不去拉，也不算失败。
- `timeout_sec`：一次网络等待的上限，1 到 20 秒，越界退回 8。
- `timezone`：待审文件里那个时间按哪个时区写，认不出来就不拉。不自己造 UTC 偏移。
- `out_file`：待审文件，相对机器人目录。绝对路径、盘符、`..` 一律退回默认的 `intake/leads.md`。退回不是静默的：`--check` 会把你原样写的那个路径点出来，并说这一版按默认落。这个文件已进 `.gitignore`，里面是陌生访客写的话，别提交。样子在 `intake/leads.example.md`。

来的一条记录认这几组字段名：`need`/`form`/`type`/`形式`/`需求类型`、`when`/`time`/`deadline`/`时间`/`档期`、`note`/`summary`/`text`/`简述`/`需求`、`page`/`path`/`source`/`来源`、`id`/`key`/`编号`。认不到就当没有那一项；三项全空的丢掉；正文里夹着客户名或手机号的整条丢掉，不等写文件时才打码。对端返坏 JSON、纯 HTML、超过 4096 字节的，整批丢掉不猜；一次最多处理 20 条。

去重靠 `state/intake_state.json` 里的编号账本：有编号用编号，没编号用内容哈希。对端重复推同一条不会写第二遍。账本先写临时文件再换过去，进程被中断也不会留半个。

还有一条不用动手的路，见下面「待看提醒 intake.notify」；不想开它就照旧：看完 `intake/leads.md`，把挑出来的几行抄成 `broadcast/pending.txt`，交给播报的 `body_file`。接待桥自己一个写入工具都不碰，白名单和 6 位确认码那套规矩没有被绕开一步，见 [docs/确认方式.md](../docs/确认方式.md)；播报怎么进群、发几次，见 [docs/断线提醒与晨报.md](../docs/断线提醒与晨报.md)。`/状态` 里会多一行「合作意向接待：开，只收不发」，没打开时这一行不加。

## 待看提醒 intake.notify

默认关，而且比接待桥多一层：本体 `intake.enabled` 和 `intake.notify.enabled` 都要为 `true` 才跑。只开提醒没有意义，那边一条意向都收不到。它补的是「到飞书里的人」这一跳：待审文件里攒了新东西时，私聊主人一条「有 N 条待看」，附上这一批的前几条和一个 6 位码。人不回话，就一个群都不进。

```json
"notify": {
  "enabled": false,
  "owner_open_ids": [],
  "chat_ids": [],
  "min_items": 1,
  "max_per_day": 2,
  "min_gap_min": 60,
  "max_items": 5,
  "confirm_ttl_sec": 86400,
  "timezone": "Asia/Shanghai"
}
```

- `owner_open_ids`：提醒发给谁。不写就退回主人的编号（和断线提醒、用量周报同一个来源）。
- `chat_ids`：确认后发去哪几个群。只有既在这里、又属于本实例服务范围的群才会发；一个都不满足时直说「那个群不在本实例的服务范围内，没发」，确认码照样作废，不留着下次用。那几条意向不算处理过，仍在待审文件里，改好配置后下一轮提醒会带一个新码。
- `min_items`：攒够几条才提醒，1 到 50。
- `max_per_day`：同一个本地日最多提醒几条，1 到 10，多的攒着。用完当天就闭嘴，到 `timezone` 那个时区换日才放开（不按 UTC 换日）——这两条各有一格测试钉着。
- `min_gap_min`：两条提醒之间至少隔多少分钟，5 到 1440，不写是 60。只管「上一条已经发出去」之后；刚装上、还没提醒过时当场就发，不先等这一截。
- `max_items`：一条提醒里最多带几条的摘要，1 到 20，不写是 5。带不下的仍在待审文件里，等下一轮。
- `confirm_ttl_sec`：确认码多久失效，不写是 24 小时。位数跟着 `confirm.code_digits`，不另开一个数。
- `timezone`：「同一个本地日」按哪个时区算，认不出来就整条不提醒，`--check` 会直说。

确认的纪律和别处一模一样：`发意向 123456` 或 `不发意向 123456` 只能由主人本人在私聊里发。别人拿同一个码、主人在群里回、码已过期，都不作数，回一句说明原因，码不消耗。码被本人用掉的情况有四种：发成功了、回了「不发意向」、那批群都不在本实例服务范围、发送接口一条都没认上——后两种一个字节都没进群，所以只废这一个码，那几条意向仍留在待审文件里，下一轮换一个新码再提醒；只有前两种才把这批记成已处理。发之前正文再过一次脱敏和工具标记清洗，并且留出余量，不会撞发送接口那 3500 字的硬上限。发送接口一条都没认上时回话照实说「一条都没发出去」。

去重靠 `state/intake_notify.json`：已经提醒过的条有编号账本，文件被重写过也不会把发过的算成新的；码没过期没用掉的那些，也不会重复提醒。`--check` 和 `/状态` 里会多一行「合作意向提醒：开，只私聊提醒主人，本人回确认码之前不发群」，配错时逐条说明为什么不会提醒。提醒这条路是会失败的——线上健康告警走的是同一个发送接口，自己的日志里就常出现「一个主人都没送到」，所以这里也不假装成功：一次都没发出去时不记当天提醒次数、不发码，`state/intake_notify.json` 里记下连击数，`logs/bot.log` 留一行「intake_notify 提醒没发出去（连续第 N 次）」，`/状态` 那行末尾多出「最近有 N 次提醒没发出去（意向还留在待看里）」；发成功一次后这句自己消失。

## 用量周报 report

默认关。不写这一段，或 `enabled` 不是 `true`，就不会私聊，也不会占每周一次的名额。这是私聊，不是群消息。群里主动发的，是各自打开之后的早晨摘要和播报，默认都关。播报不读日历和任务表。

打开后，到了 `weekday` 和 `time`（不写是周一 `09:00`，时区不写是 `Asia/Shanghai`），把上一整周的合计私聊给主人。`window_min` 不写是 180，这三小时里重启也不会再发一份。`report.owner_open_ids` 有可用编号时用它；空着就用 `alerts.owner_open_ids`，不要求 `alerts` 已经打开。两边都空、或都是 `REPLACE_` 开头，就不发。某一位发不出去时，不会马上丢掉这一周的名额再连着试：网络失败大约 5 分钟后再试；飞书 41050（没有私聊权限）记成不再重试，日志只留一次。其它主人不受影响。

统计在本机 `logs/usage.jsonl`。周报里没有问题原文、人名、open_id 或群编号，只有 `群 1` 这种标签。演练（`--dry-run` 或测试替身）和停机后的补答会做标记，不进合计。主人在私聊里发 `/report` 可以马上再看一份，这不占每周的名额；在群里发只回一句「已私聊」，明细不进群。

不发送、只导出：`python agentbot.py agents/<名字>.json --report [--week 2026-W42] [--out 文件.md|文件.csv]`。`enabled` 为 false 时这条命令仍可用。细节见 [docs/用量周报.md](../docs/用量周报.md)。

| 键 | 默认 | 填什么 |
|---|---|---|
| `enabled` | `false` | `true` 才到点私聊。 |
| `owner_open_ids` | `[]` | 接收人。空着就用 `alerts.owner_open_ids`。 |
| `weekday` | `mon` | `mon` 到 `sun`，或 `周一` 到 `周日`，或 `0` 到 `6`（`0` 是周一）。认不出来就不发。 |
| `time` | `09:00` | `HH:MM`。写错就不发。 |
| `timezone` | `Asia/Shanghai` | 认不出来的时区不发。 |
| `window_min` | `180` | 到点之后多少分钟内还可以补发。`0` 表示只在那一分钟。负数按 180。 |

## 知识库目录 kb_index

模型每次回答前，如果知识库里有 `.md` 或 `.txt`，提示词里会多一份目录：只有相对路径和第一行标题，没有正文。正文要模型输出 `kb_read` 才会读。

| 键 | 默认 | 填什么 |
|---|---|---|
| `enabled` | 不写就是 `true` | `false` 时不把目录放进提示词。空文件夹本来就不会多出目录。 |
| `budget_chars` | `1000` | 目录最长多少字。超了就截断并注明。 |

`tools.kb_read` 不写时也可以读。写成 `{"enabled": false}` 就关掉。`max_chars` 默认 `8000`，只限制读进提示词的正文。

升级旧配置：不用改。没写 `kb_index` 和 `kb_read` 时，空知识库的提示词和以前一样；放了文件之后才会多出目录，并可以按路径读取。读出来的客户名会打码。`../`、绝对路径和跳出目录的链接读不到。未列入私聊名单的人看不到目录，也不能读。

## 分群知识库检索 knowledge

默认关。不写 `knowledge`，或 `enabled` 为 `false` 时，不建索引、不检索，提示词里也不会出现 `kb_search`。`/状态` 不多一行。已经在用的 `kb/` 目录、`kb_read` 和 `kb_sync` 都不变。

打开之后，每个群、每次私聊各有一份本地索引，存在本机 `state/kb/<会话>/`，不要提交。检索只能查当前这一份。甲群的文件和链接不会进乙群。

| 键 | 默认 | 填什么 |
|---|---|---|
| `enabled` | `false` | `true` 才收录、才响应 `/kb`。 |
| `auto_retrieve` | `false` | `true` 时，普通问题会先附上最多几条片段。命令不会。 |
| `local` | `true` | 收录本机器人 `kb/` 里的文件。这是机器人自己的资料，每个打开检索的会话都会收一份。设为 `false` 就只收下面几项。 |
| `group_files` | `false` | `true` 才收本群里发过的文件。私聊没有这一项。 |
| `group_links` | `false` | `true` 才收本群消息里的飞书云文档、知识库、多维表格链接。别的网址跳过，不会去访问。 |
| `docs` | `[]` | 云文档链接或 token。`REPLACE_` 开头的会丢掉。 |
| `wiki` | `[]` | 知识库链接或节点 token。 |
| `bases` | `[]` | 多维表格。可以写 `{"base_token":"…","table_id":"…","title":"任务表"}`，或 `base_token/table_id`。链接里要能看出 `table=`。 |
| `refresh_min` | `0` | `0` 不定时。写了分钟数就按这个间隔补收录，小于 5 按 5，避免打太勤。一个周期只更新一个会话。 |
| `chunk_chars` | `480` | 每段大约多少字。 |
| `chunk_overlap` | `80` | 相邻段重叠多少字。 |
| `top_k` | `5` | 一次最多回几段。 |
| `max_chars` | `4000` | 检索结果最多多少字，并且不会超过 `agent.tool_context_budget_chars`。 |
| `embeddings.enabled` | `false` | `true` 才请求向量。失败就只用关键词，不中断回答。 |
| `embeddings.base_url` | 空 | OpenAI 兼容地址，例如 `https://api.example.com/v1`。不要在地址里写密钥。本机可以用 `http://127.0.0.1:端口/v1`。 |
| `embeddings.api_key_env` | 空 | 环境变量的名字，不是密钥本身。 |
| `embeddings.model` | 空 | 向量模型名。空着就不会去请求。 |
| `embeddings.timeout_sec` | `20` | 请求最多等几秒。 |

群里的命令（要先打开 `enabled`，否则这几个字仍交给模型）：

| 命令 | 谁可以 | 做什么 |
|---|---|---|
| `/kb`、`/kb status`、`/kb 状态` | 能叫到机器人的人 | 看本会话收录了几份、上次什么时候更新。不调用模型。 |
| `/kb refresh`、`/kb 刷新` | 只有 `write.allowed_users` | 按上面的来源更新这一份索引。不调用模型。 |

模型侧的工具是 `kb_search`，参数 `{"query":"关键词"}`。它不能指定别的群。

飞书权限都是只读，只有打开并且用到对应来源时，`--doctor` 才会多要求这些：

| 来源 | 权限 |
|---|---|
| 只收本地 `kb/` | 不需要新的飞书权限 |
| 群文件 | `im:message:readonly`、`im:message.group_msg`、`im:resource` |
| 云文档 | `docx:document:readonly` |
| 知识库 | `wiki:node:read`（或 `wiki:wiki:readonly`、`wiki:node:retrieve`） |
| 多维表格 | `base:record:read` |

文档没分享给应用时，这一份会记失败，已经收过的内容先留着。图片没有单独的文字识别，不进索引。PDF、Word、PPT、Excel、CSV、Markdown、文本和 zip 用原来的读取和上限。细节见 [docs/知识库.md](../docs/知识库.md)。

`tools.docs_read.allow_tokens` 如果写了非空名单，知识库也只收名单里的云文档和知识库，不会因为开了检索就读得更宽。

## 知识库同步 kb_sync

`docs_tokens`：要从飞书拉进知识库的文档编号列表。空列表表示不拉。同步只进待审区，你确认后才替换正式知识库。见 `docs/新建智能体.md` 最后一节。拉取时和主程序一样优先用 `lark-cli.exe`，参数是列表。只剩 `.cmd` 时，参数里如果出现 `&`、`|` 这类字符就拒绝执行，不交给 cmd.exe。

## 演练开关

`dry_run_live_reads`：演练时要不要真的去读飞书。默认 `false`，演练只在屏幕上打印命令，不发消息。不要为了省事改成 `true`，除非你知道自己在演练、并且只读。

写操作在演练里默认也不真的执行。只有你本人在环境变量里打开 `AGENTBOT_DRY_LIVE_WRITES=1` 时才会真的写。验收时才这么做，并且用单独的测试表。

## 项目级 mcp.json 示例

本地控制面不写进 `agents/*.json`。Cursor 在仓库根放 `.cursor/mcp.json`（项目级，只对这个仓库生效）。`command` 的 `python` 是占位，换成你本机跑这个仓库的 Python 3.12；PATH 对不上时改成该解释器的绝对路径。`args` 是 `["mcp_server.py", "agents/<name>.json"]`，`cwd` 是仓库根。示例里没有 `env`，也不写密钥。填好本机路径的文件留在自己电脑上。启动参数、三个只读工具和只读边界见 [docs/本地控制面.md](../docs/本地控制面.md)。

```json
{
  "mcpServers": {
    "mimi-agent": {
      "command": "python",
      "args": ["mcp_server.py", "agents/<name>.json"],
      "cwd": "."
    }
  }
}
```

上面「工具 tools」里的 `decision_gate_check` 等四项只读配套在 `agents/example.json` 里保持关闭。`write.decision_gate` 也保持关闭。控制面不暴露写入。

> AI生成
