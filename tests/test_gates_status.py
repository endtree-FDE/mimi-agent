# 门禁状态行测试：/状态 里那行门禁（gates_status.status_line）+ agentbot dry-run 集成。
# 计数只读审计文件；断言不打印编号、群号和路径（/状态 的既有纪律）。
import datetime, json, os, shutil, subprocess, sys, tempfile, time

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401
from gates_status import status_line

EXAMPLE = json.load(open(os.path.join(FW, "agents", "example.json"), encoding="utf-8-sig"))

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(str(detail)[-1200:])


CFG_ALL = {"tools": {"evidencegate_check": {"enabled": True}, "decision_gate_check": {"enabled": True}},
           "write": {"decision_gate": {"enabled": True, "tools": {"docs_create": "L2", "base_create": "L2"}}}}
CFG_OFF = {}
CFG_EG_ONLY = {"tools": {"evidencegate_check": {"enabled": True}}}


def make_base(events):
    """造审计 base：按 events 造 audit/202611.jsonl，age 是距今天数。"""
    base = tempfile.mkdtemp(prefix="jc_status_")
    os.makedirs(os.path.join(base, "audit"), exist_ok=True)
    today = datetime.date.today()
    lines = []
    for ev in events:
        d = today - datetime.timedelta(days=ev.get("age", 0))
        row = {"kind": ev["kind"], "ts": d.isoformat() + "T10:00:00"}
        if ev.get("tool"):
            row["tool"] = ev["tool"]
        if ev.get("gate"):
            row["gate"] = ev["gate"]
        lines.append(json.dumps(row, ensure_ascii=False))
    with open(os.path.join(base, "audit", "202611.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return base


def test_status_line():
    check("三门全关返回空（/状态 不加行）", status_line(CFG_OFF, tempfile.mkdtemp()) == "")
    out = status_line(CFG_EG_ONLY, tempfile.mkdtemp())
    check("只开证据门：提证据门不提写提案门，并说明最近 7 天无记录",
          "证据门 开" in out and "写提案门" not in out and "最近 7 天没有" in out, out)
    base = make_base([
        {"kind": "write_proposed", "gate": {"level": "L2", "execution": "after_approval"}},
        {"kind": "write_blocked", "gate": {"level": "L2", "evidence": "partial", "evidence_source": "evidencegate:HUMAN_REVIEW"}},
        {"kind": "read", "tool": "evidencegate_check"},
        {"kind": "read", "tool": "evidencegate_check"},
        {"kind": "read", "tool": "decision_gate_check"},
        {"kind": "write_blocked", "gate": {"level": "L3", "evidence": "missing", "evidence_source": "default"}, "age": 10},
    ])
    out = status_line(CFG_ALL, base)
    check("全开时门禁行含三个开关与声明的写工具数",
          "证据门 开" in out and "决策门 开" in out and "写提案门 开（已声明 2 个写工具的等级）" in out, out)
    check("最近 7 天计数正确（7 天外的老阻断不计）",
          "放行提案 1 次" in out and "阻断 1 次" in out and "证据门查询 2 次" in out and "决策门查询 1 次" in out, out)
    check("最近一次阻断带等级、依据状态与来源", "最近一次阻断：等级 L2、依据不完整（来自证据门）" in out, out)
    check("状态行不打印编号、群号和本机路径",
          "oc_" not in out and "ou_" not in out and "Temp" not in out and "audit" not in out, out)
    shutil.rmtree(base, ignore_errors=True)
    empty = status_line(CFG_ALL, tempfile.mkdtemp())
    check("开着但审计目录不存在时不崩并说明无记录", "最近 7 天没有写提案和门禁查询记录" in empty, empty)


def _bot_config(work, gates_on):
    cfg = json.loads(json.dumps(EXAMPLE))
    cfg["base_dir"] = work
    cfg["bot_open_id"] = "ou_bot_placeholder"
    cfg["profile"] = "prof_test"
    cfg["chat_ids"] = ["oc_chat1"]
    cfg["rate_limit"] = {"min_gap_per_user": 0, "max_per_hour": 100}
    if gates_on:
        cfg.setdefault("tools", {})["evidencegate_check"] = {"enabled": True}
        cfg["tools"]["decision_gate_check"] = {"enabled": True}
        cfg.setdefault("write", {})["decision_gate"] = {"enabled": True, "tools": {"docs_create": "L2", "base_create": "L2"}}
    path = os.path.join(work, "bot.json")
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    open(os.path.join(work, "redact.txt"), "w", encoding="utf-8").write("杭州某某科技有限公司\n")
    return path


def _run_status(path, work, mid):
    events = os.path.join(work, "events.jsonl")
    bot = "小助手"
    mention = [{"id": "ou_bot_placeholder", "key": "@_user_1", "name": bot}]
    item = {"event": {"message_id": mid, "chat_id": "oc_chat1", "chat_type": "group", "message_type": "text",
                      "sender_id": "ou_sender1", "sender_type": "user", "content": "@%s /状态" % bot, "mentions": mention}}
    open(events, "w", encoding="utf-8").write(json.dumps(item, ensure_ascii=False) + "\n")
    env = dict(os.environ)
    env["AGENTBOT_FAKE_AGENT"] = "0"
    proc = subprocess.run([sys.executable, os.path.join(FW, "agentbot.py"), path, "--dry-run", events],
                          cwd=FW, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=90)
    out = (proc.stdout or "") + (proc.stderr or "")
    key = "[dry-run] reply %s: " % mid
    i = out.find(key)
    lines = []
    if i >= 0:
        for n, line in enumerate(out[i + len(key):].splitlines()):
            if n and len(line) > 30 and line[4] == "-" and " INFO " in line[:40]:
                break
            lines.append(line)
    return proc.returncode, "\n".join(lines), out


def test_agentbot_integration():
    # 开着：/状态 多一行门禁，带计数与最近一次阻断摘要
    work = tempfile.mkdtemp(prefix="jc_status_on_")
    try:
        base = make_base([
            {"kind": "write_proposed", "gate": {"level": "L2", "execution": "after_approval"}},
            {"kind": "write_blocked", "gate": {"level": "L2", "evidence": "partial", "evidence_source": "evidencegate:HUMAN_REVIEW"}},
            {"kind": "read", "tool": "evidencegate_check"},
        ])
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(base, work)
        path = _bot_config(work, True)
        code, reply, out = _run_status(path, work, "st1")
        check("开着时 /状态 多一行门禁（agentbot 集成）",
              code == 0 and "门禁：证据门 开" in reply and "放行提案 1 次" in reply and "阻断 1 次" in reply, reply + out[-800:])
        check("门禁行不含编号与群号", "ou_" not in reply and "oc_chat1" not in reply, reply)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # 对照：默认配置三门全关，/状态 与以前一样
    work = tempfile.mkdtemp(prefix="jc_status_off_")
    try:
        path = _bot_config(work, False)
        code, reply, out = _run_status(path, work, "st0")
        check("默认配置（三门全关）时 /状态 不出现门禁行", code == 0 and "门禁：" not in reply, reply + out[-600:])
    finally:
        shutil.rmtree(work, ignore_errors=True)


test_status_line()
test_agentbot_integration()

print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)