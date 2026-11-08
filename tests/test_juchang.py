# juchang 三门测试：决策门禁（工具 + 写提案包裹）、证据回放核对、Matrix 回执核验。
# 脚本零依赖（node 内置），测试里真跑 node：实例机 v24、CI runner 都预装。
# 上游 route-gate 测试（16 条）也在本文件里跑一遍，证明机械移植的行为等价性。
import datetime, hashlib, json, logging, os, shutil, subprocess, sys, tempfile, time

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401
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


def write_cfg(gate=None):
    w = {"enabled": True, "confirm_ttl_sec": 300,
         "allowed_users": {"user_jc": "测试管理员"},
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
        check("dual 审批提示双人复核边界", "双人复核" in out and "单人确认流" in out, out)
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
    check("示例里写提案门禁默认关且带等级声明", dg.get("enabled") is False and dg.get("tools", {}).get("docs_create") == "L2", dg)


test_upstream_port()
test_default_off()
test_decision_gate_routes()
test_evidence_replay()
test_receipt_verify()
test_gate_wrapper()
test_statics()

print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
