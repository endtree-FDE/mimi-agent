---
name: matrix-receipt-verifier
description: Matrix 回执核验：离线校验 caller 提供的 accepted@2 导出——canonical 投影哈希、发送者 / 任务关联、因果顺序、冲突与零写入策略。结果只证明内部一致，不证明来源真实。
---

# Matrix 回执核验

对包含 `JUCHANG_AGENT_STUDIO_WORKER_RUN` 与 `JUCHANG_AGENT_STUDIO_RECEIPT_ACCEPTED` 标记的 Matrix 事件导出做离线一致性核验。它不能证明导出真实来自 Matrix，也不能证明底层业务事实为真——通过只意味着「caller 提供的导出内部自洽」。

## 用法（mimi 内）

用 `receipt_verify` 只读工具（默认关，配置 `tools.receipt_verify.enabled=true` 后启用），参数给导出 JSON 的实例内相对路径；或直接跑脚本：

```bash
node skills/matrix-receipt-verifier/scripts/verify-matrix-receipts.mjs --input <export.json>
```

退出码：0 = 通过（verdict passed）；1 = 核验失败（stdout 给稳定原因码）；2 = 用法或输入文件错误。

## 两个档位（写在导出的 expected.projectionProfile 里）

- `app-compatible`：校验 accepted@2 传输与投影契约（schema、界长、安全文本、投影哈希、发送者一致、关联字段、因果顺序、角色覆盖、冲突绑定）。
- `runtime-zero-write`：在上一档之上，再要求五个影响区按序声明且四项安全计数全为 0（productionWrites / publicPublishes / realRefunds / externalMessages）。

## 结果怎么读

- `receiptDigest` 把 leader 的接受绑定到 worker 的完成标记；`projectionDigest` 由递归键排序的 canonical JSON 重算，必须与 accepted@2 声明一致。
- `sourceAuthenticity` 恒为 `not_verified`：导出与期望范围都是 caller 给的，谁都能自造一份自洽数据。
- `domainSkillClaim.present: true` 仍只是 leader 单方声明，除非对照被引用回执独立核验；`status` 可能是 blocked / failed / not_called——内部一致的链也可以描述一次不成功的业务动作。
- 所有接受与完成标记必须绑定同一 project / task / session / thread / command / run / role / worker / workerTask / 来源回执摘要，且与 Matrix 服务器时间相差不超过 60 秒、接受不早于完成。

## 必守边界

- 只用本机、窄过滤过的事件导出；不要请求或打印 Matrix 访问令牌、密码、Cookie、房间历史或无关消息。
- 不连接 Matrix：核验器故意保持离线，只用 Node 标准库。
- 把 Runtime 编排证据与 domainSkillReceipt 分开：合法的 Runtime trace 不能顶替业务 Skill 回执。
- 坏标记、意外字段、发送者不符、时间漂移、摘要不符、绑定冲突、角色缺失——任一出现立即停。

完整字段契约见 references/contract.md。
