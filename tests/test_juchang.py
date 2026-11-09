# juchang 三门测试：决策门禁（工具 + 写提案包裹）、证据回放核对、Matrix 回执核验。
# 脚本零依赖（node 内置），测试里真跑 node：实例机 v24、CI runner 都预装。
# 上游 route-gate 测试（16 条）也在本文件里跑一遍，证明机械移植的行为等价性。
import datetime, hashlib, json, logging, os, shutil, subprocess, sys, tempfile, time

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401
import confirm_mode  # noqa: F401
from tools import Tools, ToolError, READ_TOOLS

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(str(detail)[-1500:])


CTX = {"user": "user_jc", "chat_id": "oc_jc", "chat_type": "group", "message_id": "om_jc_0001"}

GOOD_DOC = json.dumps({
    "document_title": "测试住宿单", "test_number": "T-1", "issue_date": "2026-01-10",
    "buyer": "甲公司", "seller": "乙酒店", "city": "杭州", "expense_type": "住宿",
    "check_in_date": "2026-01-10", "check_out_date": "2026-01-12", "quantity_nights": 2,
    "amount_excluding_tax_yuan": 100, "tax_rate": "6%", "tax_amount_yuan": 6,
    "total_amount_yuan": 106, "purpose_text": "出差",
    "synthetic_labels": ["合成测试票据", "仅供OCR评测", "非真实发票"], "uncertainties": [],
}, ensure_ascii=False)
# 金额算术错 → HUMAN_REVIEW（partial 证据）
BAD_DOC = GOOD_DOC.replace('"total_amount_yuan": 106', '"total_amount_yuan": 999')


def new_tools(tools_cfg, write_cfg=None):
    base = tempfile.mkdtemp(prefix="jc_base_")
    # 三个门禁脚本按实例布局放进 base（工具只认 base 内路径）。
    shutil.copytree(os.path.join(FW, "skills"), os.path.join(base, "skills"))
    cfg = {"profile": "placeholder", "bot_open_id": "ou_bot_placeholder", "bot_names": ["小助手"],
           "tools": tools_cfg}
    if write_cfg is not None:
        cfg["write"] = write_cfg
    return base, Tools(cfg, base, lambda: ["lark-cli"], logging.getLogger("jc"), dry=True)


def write_cfg(gate=None, users=None):
    w = {"enabled": True, "confirm_ttl_sec": 300,
         "allowed_users": dict(users or {"user_jc": "测试管理员"}),
         "resources": {"folder_token": "fld_demo", "calendar_id": "cal_demo"}}
    if gate is not None:
        w["decision_gate"] = gate
    return w


def audit_events(base):
    out = []
    folder = os.path.join(base, "audit")
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if name.endswith(".jsonl"):
            for line in open(os.path.join(folder, name), encoding="utf-8"):
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


# ---------- ① 上游测试移植：route-gate 行为等价 ----------

def test_upstream_port():
    r = subprocess.run(["node", "--test", os.path.join("skills", "juchang-decision-gate", "scripts", "route-gate.test.mjs")],
                       cwd=FW, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    check("上游 route-gate 16 条测试在移植版上全绿（机械移植行为等价）",
          r.returncode == 0 and "pass 16" in out and "fail 0" in out, out)


# ---------- ② 三个工具默认关 ----------

def test_default_off():
    base, t = new_tools({"history": {"enabled": True, "days": 7}})
    try:
        for name in ("decision_gate_check", "evidence_replay_check", "receipt_verify"):
            try:
                t.run_read(name, {}, dict(CTX))
                check("默认关时 %s 不可用" % name, False)
            except ToolError as e:
                check("默认关时 %s 不可用" % name, "未知工具" in str(e) or "还没在配置里启用" in str(e), e)
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------- ③ decision_gate_check：三路由与安全 ----------

DG_L2 = {"actionLevel": "L2", "evidenceState": "sufficient", "likelihood": "possible",
         "impact": "medium", "reversibility": "reversible", "complexity": "simple"}


def test_decision_gate_routes():
    base, t = new_tools({"decision_gate_check": {"enabled": True}})
    try:
        out = t.run_read("decision_gate_check", {"input": dict(DG_L2)}, dict(CTX))
        check("L2 公开修改路由 after_approval 且话术是需确认", "after_approval" in out and "需确认" in out, out)
        check("摘要带维度与审批模式", "动作等级 L2 公开修改" in out and "负责人批准" in out, out)
        check("摘要声明分数不给权限", "分数不给权限" in out, out)
        out = t.run_read("decision_gate_check", {"input": dict(DG_L2, evidenceState="conflict", supportingEvidence=20)}, dict(CTX))
        check("证据冲突无条件阻断（强观测也不放行）", "blocked" in out and "阻断" in out, out)
        out = t.run_read("decision_gate_check", {"input": dict(DG_L2, actionLevel="L3")}, dict(CTX))
        check("L3 路由 manual_only 只允许人工", "manual_only" in out and "只允许人工" in out, out)
        out = t.run_read("decision_gate_check", {"input": dict(DG_L2, actionLevel="L0")}, dict(CTX))
        check("L0 路由 automatic 且仍提醒确认不能关", "automatic" in out and "确认不能关" in out, out)
        try:
            t.run_read("decision_gate_check", {"input": dict(DG_L2, actionLevel="L9")}, dict(CTX))
            check("非法枚举 fail closed 报输入不合法", False)
        except ToolError as e:
            check("非法枚举 fail closed 报输入不合法", "决策门禁输入不合法" in str(e), e)
        try:
            t.run_read("decision_gate_check", {}, dict(CTX))
            check("空参数报错", False)
        except ToolError as e:
            check("空参数报错", "input" in str(e) and "path" in str(e), e)
        try:
            t.run_read("decision_gate_check", {"path": "../agents/example.json"}, dict(CTX))
            check("路径逃逸被拒绝", False)
        except ToolError as e:
            check("路径逃逸被拒绝", "不存在或不在实例目录内" in str(e), e)
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------- ④ evidence_replay_check：pass / fail ----------

def replay_doc(readonly=True, schema="verified-replay@1", disclosure="本归档由权威账本导出冻结，沙盘推演内容不进入本档，缺口项已如实登记。"):
    return {"readonly": readonly, "schema": schema, "disclosure": disclosure,
            "rawExportSha256": "a" * 64, "skillInvocations": [{"status": "not_called"}],
            "qualityReview": {"state": "needs_revision"}}


def test_evidence_replay():
    base, t = new_tools({"evidence_replay_check": {"enabled": True}})
    try:
        p = os.path.join(base, "replay-ok.json")
        json.dump(replay_doc(), open(p, "w", encoding="utf-8"), ensure_ascii=False)
        out = t.run_read("evidence_replay_check", {"path": "replay-ok.json"}, dict(CTX))
        check("如实归档核对 pass 且缺口登记保留", "pass" in out and "自洽" in out, out)
        p2 = os.path.join(base, "replay-sim.json")
        json.dump(replay_doc(schema="juchang-crisis-protocol-simulation@1"), open(p2, "w", encoding="utf-8"), ensure_ascii=False)
        out = t.run_read("evidence_replay_check", {"path": "replay-sim.json"}, dict(CTX))
        check("协议模拟报告冒充归档核对 fail", "fail" in out and "未过" in out, out)
        p3 = os.path.join(base, "replay-readonly.json")
        json.dump(replay_doc(readonly=False), open(p3, "w", encoding="utf-8"), ensure_ascii=False)
        out = t.run_read("evidence_replay_check", {"path": "replay-readonly.json"}, dict(CTX))
        check("readonly=false 的档核对 fail", "fail" in out and "未过" in out, out)
        check("摘要声明通过不证明业务事实", "不证明业务事实" in out, out)
        try:
            t.run_read("evidence_replay_check", {"path": "../agents/example.json"}, dict(CTX))
            check("回放路径逃逸被拒绝", False)
        except ToolError as e:
            check("回放路径逃逸被拒绝", "不存在或不在实例目录内" in str(e), e)
        try:
            t.run_read("evidence_replay_check", {}, dict(CTX))
            check("回放空参数报错", False)
        except ToolError as e:
            check("回放空参数报错", "path" in str(e), e)
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------- ⑤ receipt_verify：passed / failed ----------

def receipt_export():
    leader = "@leader:example.test"
    worker = "@worker-m:example.test"
    at_w = "2026-11-08T10:00:00Z"
    at_a = "2026-11-08T10:00:10Z"
    ts_w = int(datetime.datetime(2026, 11, 8, 10, 0, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    ts_a = ts_w + 10000
    receipt_digest = "b" * 64
    scope = {"projectId": "demo-project", "taskId": "demo-task-01", "sessionId": "studio-example-session-0001",
             "threadId": "demo-thread-01", "commandId": "11111111-1111-4111-8111-111111111111",
             "runId": "22222222-2222-4222-8222-222222222222", "workerId": "worker-m",
             "role": "material_intake", "workerTaskId": "demo-worker-task-01"}
    projection = {
        "schema": "yixun-agent-studio-receipt-projection@1", "conclusion": "HUMAN_REVIEW",
        "analysisSummary": "材料核对完成，冲突已登记，未执行任何写入",
        "facts": [{"field": "ticket_count", "value": "3", "evidenceRefs": ["run-1"]}],
        "conflicts": [], "unknownFields": [], "nextAction": "",
        "impacts": [{"area": a, "description": "零写入声明", "evidenceRefs": []}
                    for a in ("event", "ticketing", "customer_service", "notification", "knowledge_base")],
        "safetyCounters": {"productionWrites": 0, "publicPublishes": 0, "realRefunds": 0, "externalMessages": 0},
        "domainSkillReceipt": None, "runtimeSkillTraceValidated": False,
    }
    canon = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    proj_digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    worker_marker = dict(scope, schema="yixun-agent-studio-worker-run@1", status="completed", tool="",
                         receiptDigest=receipt_digest, at=at_w)
    accepted = dict(scope, schema="yixun-agent-studio-receipt-accepted@2", receiptDigest=receipt_digest,
                    at=at_a, projectionDigest=proj_digest, projection=projection)
    export = {
        "expected": {"projectId": scope["projectId"], "taskId": scope["taskId"], "sessionId": scope["sessionId"],
                     "threadId": scope["threadId"], "commandId": scope["commandId"], "runId": scope["runId"],
                     "leaderSender": leader, "roles": ["material_intake"],
                     "workerSenders": {"material_intake": worker}, "projectionProfile": "runtime-zero-write"},
        "events": [
            {"sender": worker, "origin_server_ts": ts_w,
             "content": {"body": "JUCHANG_AGENT_STUDIO_WORKER_RUN: " + json.dumps(worker_marker, separators=(",", ":"))}},
            {"sender": leader, "origin_server_ts": ts_a,
             "content": {"body": "JUCHANG_AGENT_STUDIO_RECEIPT_ACCEPTED: " + json.dumps(accepted, separators=(",", ":"))}},
        ],
    }
    return export


def test_receipt_verify():
    base, t = new_tools({"receipt_verify": {"enabled": True}})
    try:
        p = os.path.join(base, "receipt-ok.json")
        json.dump(receipt_export(), open(p, "w", encoding="utf-8"), ensure_ascii=False)
        out = t.run_read("receipt_verify", {"path": "receipt-ok.json"}, dict(CTX))
        check("合法 accepted@2 导出核验 passed", "passed" in out and "内部一致" in out, out)
        check("结果声明来源未核验与零写入策略", "not_verified" in out and "passed" in out, out)
        bad = receipt_export()
        bad["events"][1]["content"]["body"] = bad["events"][1]["content"]["body"].replace(
            '"conclusion":"HUMAN_REVIEW"', '"conclusion":"APPROVED"')
        p2 = os.path.join(base, "receipt-bad.json")
        json.dump(bad, open(p2, "w", encoding="utf-8"), ensure_ascii=False)
        out = t.run_read("receipt_verify", {"path": "receipt-bad.json"}, dict(CTX))
        check("篡改投影后核验 failed 并给稳定原因码", "failed" in out and "accepted_projection_digest_mismatch" in out, out)
        try:
            t.run_read("receipt_verify", {"path": "../agents/example.json"}, dict(CTX))
            check("回执导出路径逃逸被拒绝", False)
        except ToolError as e:
            check("回执导出路径逃逸被拒绝", "不存在或不在实例目录内" in str(e), e)
        # 入口判定回归：从含 ~ 与非 ASCII 的路径（CI runner 的 8.3 短路径形状）跑也要出结果
        odd = os.path.join(base, "RUNNE~1-核验")
        os.makedirs(odd, exist_ok=True)
        script_odd = os.path.join(odd, "verify-matrix-receipts.mjs")
        shutil.copy(os.path.join(FW, "skills", "matrix-receipt-verifier", "scripts", "verify-matrix-receipts.mjs"), script_odd)
        r = subprocess.run(["node", script_odd, "--input", os.path.join(base, "receipt-ok.json")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        check("含 ~ 的路径下入口判定仍执行（8.3 短路径回归）",
              r.returncode == 0 and '"passed"' in (r.stdout or ""), (r.stdout or "") + (r.stderr or ""))
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------- ⑥ 决策门禁包裹写提案流 ----------

def test_gate_wrapper():
    # 默认关：不写 decision_gate 时提案照旧
    base, t = new_tools({"docs_create": {"enabled": True}}, write_cfg())
    try:
        out = t.propose_write("docs_create", {"title": "纪要", "markdown": "内容"}, dict(CTX))
        check("未启用门禁时提案照旧发出", "将要执行" in out and "确认" in out, out)
        evs = audit_events(base)
        check("未启用门禁时审计不带 gate 字段", all("gate" not in e for e in evs if e.get("kind") == "write_proposed"), evs)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 启用 + L2 + 默认证据 → after_approval，提案照发，审计带路由依据
    base, t = new_tools({"docs_create": {"enabled": True}},
                        write_cfg({"enabled": True, "tools": {"docs_create": "L2"}}))
    try:
        out = t.propose_write("docs_create", {"title": "纪要", "markdown": "内容"}, dict(CTX))
        check("L2 足够证据放行进确认流", "将要执行" in out and "确认" in out, out)
        gate = [e.get("gate") for e in audit_events(base) if e.get("kind") == "write_proposed"]
        check("审计含路由依据（等级/证据/路由/来源）",
              gate and gate[0].get("level") == "L2" and gate[0].get("execution") == "after_approval"
              and gate[0].get("evidence") == "sufficient" and gate[0].get("evidence_source") == "default", gate)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 双门联动：evidencegate HUMAN_REVIEW → partial → 写提案被阻断
    base, t = new_tools({"docs_create": {"enabled": True}, "evidencegate_check": {"enabled": True}},
                        write_cfg({"enabled": True, "tools": {"docs_create": "L2"}}))
    try:
        t.run_read("evidencegate_check", {"candidate": BAD_DOC}, dict(CTX))
        check("门禁一返回 HUMAN_REVIEW 并登记进注册表",
              t._eg_last.get("oc_jc", {}).get("state") == "partial", t._eg_last)
        try:
            t.propose_write("docs_create", {"title": "报销", "markdown": "内容"}, dict(CTX))
            check("partial 证据阻断 L2 写提案", False)
        except ToolError as e:
            check("partial 证据阻断 L2 写提案", "决策门禁阻断" in str(e) and "先补齐或解决依据" in str(e), e)
        blocked = [e for e in audit_events(base) if e.get("kind") == "write_blocked"]
        check("阻断审计带 gate 依据（evidence=partial 且来源是 evidencegate）",
              blocked and blocked[0].get("gate", {}).get("evidence") == "partial"
              and "evidencegate:HUMAN_REVIEW" in str(blocked[0].get("gate", {}).get("evidence_source")), blocked)
        # 换成合格候选后同一会话可再提案（sufficient → after_approval）
        t.run_read("evidencegate_check", {"candidate": GOOD_DOC}, dict(CTX))
        out = t.propose_write("docs_create", {"title": "报销", "markdown": "内容"}, dict(CTX))
        check("证据转合格后同一会话恢复提案", "将要执行" in out, out)
        gate = [e.get("gate") for e in audit_events(base) if e.get("kind") == "write_proposed"]
        check("恢复后审计来源是 evidencegate:ACCEPT_CANDIDATE",
              gate and "evidencegate:ACCEPT_CANDIDATE" in str(gate[0].get("evidence_source")), gate)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 证据过期回默认
    base, t = new_tools({"docs_create": {"enabled": True}},
                        write_cfg({"enabled": True, "tools": {"docs_create": "L2"},
                                   "evidence_window_sec": 1, "evidence_default": "sufficient"}))
    try:
        t._eg_last["oc_jc"] = {"status": "HUMAN_REVIEW", "state": "partial", "ts": time.time() - 10}
        out = t.propose_write("docs_create", {"title": "纪要", "markdown": "内容"}, dict(CTX))
        check("证据记录过期后回默认 sufficient 照常提案", "将要执行" in out, out)
        gate = [e.get("gate") for e in audit_events(base) if e.get("kind") == "write_proposed"]
        check("过期后审计来源记 default", gate and gate[0].get("evidence_source") == "default", gate)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # L3 → manual_only，拒绝代执行
    base, t = new_tools({"calendar_delete": {"enabled": True}},
                        write_cfg({"enabled": True, "tools": {"calendar_delete": "L3"}}))
    try:
        try:
            t.propose_write("calendar_delete", {"event_id": "ev_1", "summary": "旧日程"}, dict(CTX))
            check("L3 只允许人工执行，机器人拒绝代做", False)
        except ToolError as e:
            check("L3 只允许人工执行，机器人拒绝代做", "只允许人工执行" in str(e) and "机器人不代做" in str(e), e)
        blocked = [e for e in audit_events(base) if e.get("kind") == "write_blocked"]
        check("manual_only 也落 write_blocked 审计", blocked and blocked[0].get("gate", {}).get("execution") == "manual_only", blocked)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 等级写错 → fail closed
    base, t = new_tools({"docs_create": {"enabled": True}},
                        write_cfg({"enabled": True, "tools": {"docs_create": "L9"}}))
    try:
        try:
            t.propose_write("docs_create", {"title": "纪要", "markdown": "内容"}, dict(CTX))
            check("配置等级不合法时 fail closed", False)
        except ToolError as e:
            check("配置等级不合法时 fail closed", "等级不合法" in str(e), e)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 未点名的写工具不过门禁
    base, t = new_tools({"docs_create": {"enabled": True}, "calendar_create": {"enabled": True}},
                        write_cfg({"enabled": True, "tools": {"calendar_create": "L2"}}))
    try:
        out = t.propose_write("docs_create", {"title": "纪要", "markdown": "内容"}, dict(CTX))
        check("未点名的写工具不过门禁", "将要执行" in out, out)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # dual 审批的诚实降级提示
    base, t = new_tools({"docs_create": {"enabled": True}},
                        write_cfg({"enabled": True, "tools": {"docs_create": {"level": "L2", "impact": "critical"}}}))
    try:
        out = t.propose_write("docs_create", {"title": "重要变更", "markdown": "内容"}, dict(CTX))
        check("dual 审批提示两步确认与另一位管理员", "双人复核" in out and "另一位管理员" in out and "复核" in out, out)
        gate = [e.get("gate") for e in audit_events(base) if e.get("kind") == "write_proposed"]
        check("dual 路由进审计 approval=dual", gate and gate[0].get("approval") == "dual", gate)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # tools 配成非字典（写错形状）时不拦，提案照旧
    base, t = new_tools({"docs_create": {"enabled": True}},
                        write_cfg({"enabled": True, "tools": ["docs_create"]}))
    try:
        out = t.propose_write("docs_create", {"title": "纪要", "markdown": "内容"}, dict(CTX))
        check("tools 配成列表时不误伤提案（形状错当没声明）", "将要执行" in out, out)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 群记忆提案同样进门禁
    base, t = new_tools({}, write_cfg({"enabled": True, "tools": {"memory_propose": "L2"}}))
    try:
        t.memory_enabled = True
        t._eg_last["oc_jc"] = {"status": "MODEL_OUTPUT_INVALID", "state": "missing", "ts": time.time()}
        try:
            t.propose_memory({"text": "主题：测试记忆"}, dict(CTX))
            check("missing 证据阻断群记忆提案", False)
        except ToolError as e:
            check("missing 证据阻断群记忆提案", "决策门禁阻断" in str(e), e)
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------- ⑦ 静态形状：READ_TOOLS / TOOL_DOC / 示例配置 ----------

def test_statics():
    import tools as _tools
    check("READ_TOOLS 收录三个新工具",
          all(n in READ_TOOLS for n in ("decision_gate_check", "evidence_replay_check", "receipt_verify")))
    for n in ("decision_gate_check", "evidence_replay_check", "receipt_verify"):
        check("工具说明里有 %s 且标注默认关" % n, n in _tools.TOOL_DOC and "默认关" in _tools.TOOL_DOC.split(n)[1][:600])
    EXAMPLE = json.load(open(os.path.join(FW, "agents", "example.json"), encoding="utf-8-sig"))
    et = EXAMPLE.get("tools") or {}
    check("示例里三个工具默认关", all((et.get(n) or {}).get("enabled") is False
          for n in ("decision_gate_check", "evidence_replay_check", "receipt_verify")), et)
    dg = (EXAMPLE.get("write") or {}).get("decision_gate") or {}
    check("示例里写提案门禁默认关，试运行只声明 docs_create 与 base_create 为 L2",
          dg.get("enabled") is False
          and dg.get("tools") == {"docs_create": "L2", "base_create": "L2"}
          and dg.get("evidence_window_sec") == 900
          and dg.get("evidence_default") == "sufficient", dg)


# ---------- ⑧ 零写入冻结导出器 + 端到端复检（生产配置） ----------

def make_ledger_base():
    """造一个账本 base：群记忆 meta.json + 审计 jsonl（含 write_blocked）。"""
    base = tempfile.mkdtemp(prefix="jc_ledger_")
    gd = os.path.join(base, "memory", "groups", "oc_demo")
    os.makedirs(gd, exist_ok=True)
    os.makedirs(os.path.join(base, "audit"), exist_ok=True)
    json.dump({"facts": [{"text": "demo 事实"}]}, open(os.path.join(gd, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False)
    today = datetime.date.today().isoformat()
    lines = [
        json.dumps({"kind": "read", "tool": "evidencegate_check", "user": "ou_x", "chat": "oc_demo", "ok": True,
                    "args": "{}", "ts": "%sT10:00:00" % today}, ensure_ascii=False),
        json.dumps({"kind": "write_blocked", "tool": "docs_create", "user": "ou_x", "chat": "oc_demo", "ok": False,
                    "gate": {"level": "L2", "evidence": "partial", "evidence_source": "evidencegate:HUMAN_REVIEW", "execution": "blocked"},
                    "detail": "阻断", "ts": "%sT10:01:00" % today}, ensure_ascii=False),
    ]
    with open(os.path.join(base, "audit", "202611.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return base


def test_dual_review():
    """门禁 dual：第一位（发起人）确认只记下，第二位白名单管理员「复核 码」才执行；边界与审计。"""
    users = {"user_jc": "发起管理员", "user_jc2": "复核管理员"}
    dg = {"enabled": True, "tools": {"docs_create": {"level": "L2", "impact": "critical"}}}

    def fresh():
        base, t = new_tools({"docs_create": {"enabled": True}}, write_cfg(dg, users=users))
        box = []

        def fake(argv):
            box.append(list(argv))
            return {"ok": True, "data": {"url": "https://example.com/docx/NEW"}}

        t.fake = fake
        return base, t, box

    base, t, box = fresh()
    ctx2 = dict(CTX, user="user_jc2", message_id="om_jc2_0001")
    try:
        out = t.propose_write("docs_create", {"title": "重要变更", "markdown": "内容"}, dict(CTX))
        code, rec = next(iter(t.pending.items()))
        check("dual 提案带 dual 标记且文案写清两步", rec.get("dual") is True and "双人复核" in out and "另一位管理员" in out, rec)
        early = t.review(code, dict(ctx2))
        check("第一位没确认前复核被挡", "还没到复核步骤" in early and not box, early)
        first = t.confirm(code, dict(CTX))
        check("第一位确认只记下不执行", "第一位确认已记下" in first and "复核" in first and not box, first)
        self_r = t.review(code, dict(CTX))
        check("发起人自己复核不算", "另一位管理员" in self_r and not box, self_r)
        second = t.review(code, dict(ctx2))
        check("第二位白名单管理员复核后真执行", second.startswith("已完成") and len(box) == 1, second)
        evs = [(e.get("kind"), e.get("detail"), e.get("user")) for e in audit_events(base)]
        h = lambda u: hashlib.sha256(u.encode("utf-8")).hexdigest()[:8]  # 审计不留人编号，只留哈希
        check("审计链 dual first → dual second → write_done",
              ("write_confirmed", "dual first", h("user_jc")) in evs
              and ("write_confirmed", "dual second", h("user_jc2")) in evs
              and any(k == "write_done" and u == h("user_jc2") for k, _d, u in evs), evs)
        replay = t.review(code, dict(ctx2))
        check("复核后码失效不重放", "无效或已过期" in replay and len(box) == 1, replay)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base, t, box = fresh()
    try:
        t.propose_write("docs_create", {"title": "重要变更", "markdown": "内容"}, dict(CTX))
        code = next(iter(t.pending))
        check("取消不挡（发起人可直接取消）", t.confirm(code, dict(CTX), cancel=True) == "已取消。")
        check("取消后无写入", not [e for e in audit_events(base) if e.get("kind") == "write_done"])
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base, t, box = fresh()
    try:
        t.propose_write("docs_create", {"title": "重要变更", "markdown": "内容"}, dict(CTX))
        code = next(iter(t.pending))
        t.confirm(code, dict(CTX))
        outsider = t.review(code, dict(CTX, user="user_out", message_id="om_out_0001"))
        denied = [e for e in audit_events(base) if e.get("kind") == "write_denied"]
        check("复核人不在白名单被拒并留痕", "白名单" in outsider and denied
              and denied[0].get("user") == hashlib.sha256("user_out".encode("utf-8")).hexdigest()[:8], outsider)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base, t = new_tools({"docs_create": {"enabled": True}}, write_cfg())
    t.fake = lambda argv: {"ok": True, "data": {"url": "u"}}
    try:
        t.propose_write("docs_create", {"title": "普通变更", "markdown": "内容"}, dict(CTX))
        code = next(iter(t.pending))
        said = t.review(code, dict(CTX))
        check("非 dual 提案复核指路到确认码", "不需要复核" in said and "确认" in said, said)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    pat = confirm_mode.confirm_pattern({"confirm": {"code_digits": 6}})
    m = pat.match("复核 123456")
    check("复核命令进确认命令正则（直接命令、不调模型）",
          bool(m) and m.group(1) == "复核" and m.group(2) == "123456" and not pat.match("确认复核 123456"))


def run_freeze(base, since=None):
    cmd = ["node", os.path.join("skills", "juchang-evidence-replay", "scripts", "freeze-audit.mjs"), "--base", base]
    if since:
        cmd += ["--since", since]
    r = subprocess.run(cmd, cwd=FW, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    return r


def test_freeze_chain():
    base = make_ledger_base()
    try:
        today = datetime.date.today().isoformat()
        r = run_freeze(base, today)
        check("冻结导出器输出合法 JSON（exit 0）", r.returncode == 0, r.stdout + r.stderr)
        j = json.loads(r.stdout)
        check("冻结档案带可重算哈希链（sourceText→rawExportSha256）",
              hashlib.sha256(j["freeze"]["sourceText"].encode("utf-8")).hexdigest() == j["rawExportSha256"], r.stdout[:400])
        check("冻结档案三模式标签正确", j.get("readonly") is True and "mimi-audit-replay@1" in j.get("schema", ""), r.stdout[:200])
        check("缺口如实登记：窗口有 write_blocked → needs_revision",
              j.get("qualityReview", {}).get("state") == "needs_revision", r.stdout[:300])
        check("未触发的门 not_called 原值保留",
              any(x.get("skill") == "receipt_verify" and x.get("status") == "not_called" for x in j.get("skillInvocations", [])), r.stdout[:300])
        # 冻结→核对器闭环
        rp = os.path.join(base, "replay.json")
        with open(rp, "w", encoding="utf-8", newline="\n") as f:
            f.write(r.stdout)
        rr = subprocess.run(["node", os.path.join("skills", "juchang-evidence-replay", "scripts", "check.mjs"), rp],
                            cwd=FW, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        check("冻结档案过核对器 pass", rr.returncode == 0 and '"pass"' in (rr.stdout or ""), rr.stdout + rr.stderr)
        # 篡改哈希链任一段 → 可核验性失效（sourceText 与 raw 不再匹配）
        tampered = json.loads(r.stdout)
        tampered["freeze"]["sourceText"] = tampered["freeze"]["sourceText"] + "\n"
        check("篡改 sourceText 后重算≠存证（可核验性反面成立）",
              hashlib.sha256(tampered["freeze"]["sourceText"].encode("utf-8")).hexdigest() != tampered["rawExportSha256"])
        # 零写入：freeze 前后账本文件集合不变
        before = set(os.path.relpath(os.path.join(root, f), base) for root, _, files in os.walk(base) for f in files)
        run_freeze(base, today)
        after = set(os.path.relpath(os.path.join(root, f), base) for root, _, files in os.walk(base) for f in files)
        check("冻结导出器零写入（不产生/改动任何账本文件）", after == before, (before ^ after))
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _prod_config():
    """生产等价的配置蓝本：决策门禁 L2 试运行（docs_create / base_create）、两个门工具已启用。
    agents/mimi.json 是本机 gitignored 实例配置、不在 CI checkout 里，所以：
    本地有真配置时用它（并核对形状），CI 无真文件时用这份内联蓝本，e2e 永远不依赖那个文件。"""
    cfg = {"profile": "placeholder", "bot_open_id": "ou_placeholder", "bot_names": ["小助手"],
           "tools": {"evidencegate_check": {"enabled": True}, "decision_gate_check": {"enabled": True},
                     "docs_create": {"enabled": True}},
           "write": {"enabled": True, "confirm_ttl_sec": 300,
                     "allowed_users": {"user_jc": "测试"},
                     "resources": {"folder_token": "fld_demo"},
                     "decision_gate": {"enabled": True, "tools": {"docs_create": "L2", "base_create": "L2"},
                                       "evidence_window_sec": 900, "evidence_default": "sufficient"}}}
    real = os.path.join(FW, "agents", "mimi.json")
    if os.path.isfile(real):
        prod = json.load(open(real, encoding="utf-8-sig"))
        pdg = (prod.get("write") or {}).get("decision_gate") or {}
        check("本机生产 mimi.json 的决策门禁配置与文档一致",
              pdg.get("enabled") is True
              and str((pdg.get("tools") or {}).get("docs_create")) in ("L2", "{'level': 'L2'}"),
              "decision_gate=" + str(pdg.get("enabled")))
        check("本机生产 mimi.json 已启用两个门工具",
              (prod.get("tools") or {}).get("evidencegate_check", {}).get("enabled") is True
              and (prod.get("tools") or {}).get("decision_gate_check", {}).get("enabled") is True,
              "decision_gate_check=" + str((prod.get("tools") or {}).get("decision_gate_check")))
    return cfg


def test_e2e_production_gate():
    """生产配置形态下端到端验证双门+审计+冻结+核验闭环（可核验、可复现，不依赖本机实例文件）。"""
    cfg = _prod_config()
    base = tempfile.mkdtemp(prefix="jc_e2e_")
    shutil.copytree(os.path.join(FW, "skills"), os.path.join(base, "skills"))
    try:
        t = Tools(cfg, base, lambda: ["lark-cli"], logging.getLogger("e2e"), dry=True)
        t.run_read("evidencegate_check", {"candidate": BAD_DOC}, dict(CTX))
        check("门禁一 HUMAN_REVIEW 已登记进会话注册表", t._eg_last.get("oc_jc", {}).get("state") == "partial", t._eg_last)
        try:
            t.propose_write("docs_create", {"title": "报销", "markdown": "内容"}, dict(CTX))
            check("partial 证据阻断写提案", False)
        except ToolError as e:
            check("partial 证据阻断写提案", "决策门禁阻断" in str(e), e)
        blocked = [e for e in audit_events(base) if e.get("kind") == "write_blocked"]
        check("阻断审计落盘且带 gate 依据",
              blocked and blocked[0].get("gate", {}).get("evidence") == "partial"
              and "evidencegate:HUMAN_REVIEW" in str(blocked[0].get("gate", {}).get("evidence_source")), blocked)
        # 冻结真实审计链 → 核对器
        r = run_freeze(base, datetime.date.today().isoformat())
        check("冻结导出器输出合法 JSON", r.returncode == 0, r.stdout + r.stderr)
        rp = os.path.join(base, "replay.json")
        with open(rp, "w", encoding="utf-8", newline="\n") as f:
            f.write(r.stdout)
        rr = subprocess.run(["node", os.path.join("skills", "juchang-evidence-replay", "scripts", "check.mjs"), rp],
                            cwd=FW, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        check("生产审计链冻结后经核对器 pass", rr.returncode == 0 and '"pass"' in (rr.stdout or ""), rr.stdout + rr.stderr)
    finally:
        shutil.rmtree(base, ignore_errors=True)


test_upstream_port()
test_default_off()
test_decision_gate_routes()
test_evidence_replay()
test_receipt_verify()
test_gate_wrapper()
test_dual_review()
test_statics()
test_freeze_chain()
test_e2e_production_gate()

print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
