# AGENTS.md — mimi-agent（飞书群助手模板）

给在本仓库工作的编码 agent 的速查说明。权威依据是 `README.md`、`agents/CONFIG.md`、
`CONTRIBUTING.md`、`docs/安全红线.md`；本文件与它们冲突时，以那些文件为准。

## 项目是什么

飞书（Lark）群助手开源模板，跑在用户自己的电脑上（脚本按 Windows 写）。群里被 @ 或
白名单私聊触发后，用本机 Cursor CLI 或任一 OpenAI 兼容模型回答；能读群历史、飞书文档、
日历、多维表格、附件和图片。写操作（建文档、文末追加、建/改/删日程、加表格记录）必须
同时过三道白名单（用户、资源、动作类型）和发起人本人确认：默认点卡片按钮，未开卡片回调
退回 6 位确认码，确认不可关闭。纯 Python 3.12 标准库实现，无强制第三方依赖。
一个机器人 = 一份 `agents/*.json` 配置，没有专用代码。

## 架构地图

- `agentbot.py` — 主入口：收事件、门卫过滤、拼上下文、调模型、回复。
- `feishu_link.py` — lark-cli 长连接与休眠重连；`outbound.py` — 主动发消息的统一出口。
- `channels/` — 渠道适配层：`feishu.py`（默认）、`wecom.py`（实验骨架，默认不连）、
  `memory.py`（仅供测试）。
- `providers/` — 模型接口：`cursor.py`（默认）、`openai_compat.py`、`anthropic.py`、
  `fake.py`（测试）；`presets.py` 存各家预设；`settings.py` 只读环境变量名，不读密钥值。
- `acp_client.py` — 可选常驻模式（`agent.mode=acp`，默认 oneshot，Cursor 只启动一次）。
- `tools.py` — 飞书只读工具与需确认的写入。
- `confirm_mode.py` — 写入确认；`guard.py` — 脱敏与话题红线；`utf8io.py` — 管道强制 UTF-8。
- `memory.py` — 按群长期记忆；`memory_growth.py` / `retrospect.py` / `skill_evolve.py` /
  `crew.py` — 默认关闭的增强功能（写入都要审批确认）。
- `skills.py` + `skills/*/SKILL.md` — 技能目录与触发词，默认关。
- `knowledge.py` / `kb_sync.py` — 分群知识库检索与待审同步，默认关。
- 定时任务（全部默认关）：`health_alert.py` 断线提醒、`digest.py` 晨报、
  `broadcast.py` 播报（不调模型）、`usage.py` 用量周报。
- `lifecycle.py` 单实例锁与优雅停机；`observe.py` / `calltrace.py` 本机脱敏日志；
  `doctor.py` 只读诊断；`feature_switch.py` 主人私聊开关功能；
  `setup_wizard.py` / `setup_agent.py` 配置生成。

## 关键命令

在仓库根目录运行（Windows PowerShell；Python 3.12）：

```text
# 离线测试：不需要第三方包、不连飞书；通过时最后一行打印通过条数
python tests/run_tests.py

# Lint（查 UTF-8、可编译、测试里的 Windows 形状路径声明），不重排代码
python checks/lint.py
python checks/test_batch.py
python checks/check_config.py agents/example.json

# 回答质量回归（假模型，不连飞书，不拿单实例锁）
python evals/run.py --config agents/example.json --provider fake --tag ci --baseline evals/baseline/ci.json --out evals/out

# 只读诊断（不发消息；没装 lark-cli 会列出缺什么）
python agentbot.py agents/example.json --doctor

# 演练：用事件 jsonl 回放，会调模型但不发飞书
python agentbot.py agents/<配置>.json --dry-run 演练.jsonl

# 正式启动（Windows；停止用 scripts\stop.ps1，平滑重启用 scripts\reload.ps1）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1 -Config agents\<配置>.json

# 可选依赖：只有看 PDF 需要（requirements.txt 仅为让 Dependabot 跟踪版本）
python -m pip install pypdf
```

首次安装走 `scripts\setup.ps1`（调用 `setup_wizard.py`，一次一问）。App Secret 只经
`lark-cli config init --name <profile> --app-secret-stdin` 由用户本人输入，任何代码、
配置、回复里都不出现。

## 配置与环境变量

配置：一个机器人一份 `agents/*.json`，逐项说明见 `agents/CONFIG.md`，schema 在
`agents/config.schema.json`。`REPLACE_` 开头的占位符必须全部替换才能启动；只有
`example.json` 允许提交。关键键：`profile`、`bot_open_id`、`chat_ids`、
`write.allowed_users`、`write.resources`、`model_provider`（cursor|openai_compat）、
`agent.api_key_env`。

环境变量（配置里只写变量名，绝不写密钥值）：
- `agent.api_key_env` 指向的变量 — OpenAI 兼容模型的 API Key。预设见 `providers/presets.py`：
  `DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`、`ZAI_API_KEY`（智谱）、`MAAS_API_KEY`（盘古）。
- `ANTHROPIC_API_KEY` — provider 为 anthropic 时的默认变量名。
- `TAVILY_API_KEY` — 可选联网检索（见 `providers/settings.py`）。
- `knowledge.embeddings.api_key_env` — 可选 embedding 服务的自定义变量名。
- 测试注入（见 `tests/run_tests.py`、`evals/world.py`）：`AGENTBOT_TEST_CFG`、
  `AGENTBOT_FAKE_AGENT`、`AGENTBOT_FAKE_LARK`、`AGENTBOT_AGENT_CMD` 等。
- CI 统一设 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`；`utf8io.py` 在进程内兜底。

外部依赖：飞书开放平台应用（事件走 lark-cli 长连接，需 Node.js 与 `@larksuite/cli`）；
模型用本机 Cursor（`cursor-agent login`）或自备 API Key。运行时本地目录 `kb/`、
`memory/`、`logs/`、`state/`、`state.db`、`redact.txt` 全部不入库。

## 改动规范

- 只能开 Pull Request，不得直推 main。main 已开分支保护：必须走 PR，且 4 个 CI 检查
  （两个平台的 test、secret scan、Windows PowerShell 5.1）全部通过才能合并。
  CODEOWNERS 是 @endtree-FDE。安全相关改动要在 PR 描述里写明影响：谁能写、写到哪里、
  失败时用户看到什么。
- 提交前让 `python checks/lint.py` 和 `python tests/run_tests.py` 全部通过（改到评测
  逻辑时再跑 `python evals/run.py --self-check`）。
- 改了启动脚本、配置键或工具名，要把对应检查补进 `tests/run_tests.py`。
- 沿用所在文件已有风格：4 空格缩进、紧凑写法，不要整文件重排版。注释写「为什么」；
  用户可见文案用完整句子，放 `docs/` 或 README；不要在文档里写死测试条数。
- 提交说明写清改了什么、为什么；中英文皆可。
- 不要放宽安全默认：确认不可关；`memory.enabled`、`progress.enabled`、`agent.mode=acp`、
  播报/晨报/周报/技能等默认关，不要改成默认开，也不要擅自加 `policy.redlines` 屏蔽词。
- 不要提交：填好的 `agents/*.json`（`example.json` 除外）、`redact.txt`、`.env`、
  `memory/`、`logs/`、`audit/`、`state/`、`state.db`、`evals/out/`、`kb/` 真实资料。
  示例一律用「小助手」「小李」「某客户」，不写真实群号、open_id、客户名或个人路径。

## 陷阱与注意（真实观察）

- 没有 pyproject/setup.py；测试是手写 runner（`tests/run_tests.py`），不是 pytest，
  用 `check()` 逐条断言、末尾打印条数。
- 含中文的 `.ps1` 必须存成 UTF-8 带 BOM（CI 用 PowerShell 5.1 逐文件检查）；启动、
  停止、注册计划任务类脚本在 CI 里只解析不真跑。
- 测试里出现 Windows 形状绝对路径字面量（`C:/x`、`C:\x`）必须声明：文件顶部加
  `# win-path-fixture` 或行尾加 `# win-path`，否则 `checks/lint.py` 报错；且 ubuntu 上
  `C:/...` 不算绝对路径，同一断言两个系统语义不同，别拿它当通用「绝对路径」用例。
- CI 会用 `PYTHONUTF8=0` + 代码页 936 再跑一遍测试，防编码侥幸；不要依赖管道默认 UTF-8。
- 不要用管道喂中文给启动/演练命令；判断进程在不在别解析 tasklist 的中文输出。
- 工具名是带 s 的复数：`docs_search`、`docs_read`、`docs_create`、`docs_append`、
  `calendar_create` 等；升级旧机器人时尤其别沿用单数旧名。
- `agents/example.json` 有三重身份：CI 的 schema 校验样例、测试的默认配置模板
  （不设 `AGENTBOT_TEST_CFG` 时用它）、新人文档。改它必须保证 check_config 与全部测试仍过。
- 语音、表情、联系人/群名片类消息不调模型、不回显 file_key/open_id——改消息处理时
  保持这类行为，测试里有断言。
- 同一个应用只允许一个进程（`lifecycle.py` 单实例锁 + 看门狗），排障先看
  `logs/bot.log`；`--doctor`、`--dry-run`、fake provider 之外不要往真实群发测试消息。
- 脚本里调用 `lark-cli` 必须显式传 `--name <profile>` 且与配置一致：不写会覆盖本机
  默认 profile，影响同机其他机器人。
