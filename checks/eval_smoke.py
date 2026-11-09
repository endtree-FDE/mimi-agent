#!/usr/bin/env python3
# 固定问答回归。假会话和假工具结果进真实的拒答、确认和只读路径。
# 不连飞书，不调模型，不发消息。沙箱配置只活在临时目录，不改仓库里的默认。
# 不 import agentbot：那个文件在导入时就读 argv 并建目录。
# 用法见 docs/回归测试.md 的「固定问答回归」。
import argparse, json, logging, os, re, shutil, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import utf8io  # noqa: E402,F401
import guard  # noqa: E402
import history_scan  # noqa: E402
from tools import READ_TOOLS, WRITE_TOOLS, ToolError, Tools  # noqa: E402

GOLDEN = os.path.join(ROOT, "evals", "fixtures", "golden")
# 这些参数一旦出现在假 lark 的命令里，就说明确认前执行了写入。只读命令用 +fetch / +search / +chat-messages-list。
WRITE_ARGV = ("+create", "+update", "+delete", "+append", "messages-send")
ID_RULES = (
    ("message_id", re.compile(r"om_[A-Za-z0-9]{10,}")),
    ("open_id", re.compile(r"ou_[A-Za-z0-9]{10,}")),
    ("union_id", re.compile(r"on_[A-Za-z0-9]{10,}")),
    ("chat_id", re.compile(r"oc_[A-Za-z0-9]{16,}")),
    ("app_id", re.compile(r"cli_[A-Za-z0-9]{8,}")),
)
CONFIRM_RX = re.compile(r"确认\s*\d{6}")


def untrusted_tools():
    """工具结果里要消掉标记的那份名单，和 agentbot._UNTRUSTED_TOOLS 保持同一行。"""
    path = os.path.join(ROOT, "agentbot.py")
    text = open(path, encoding="utf-8").read()
    found = re.search(r"_UNTRUSTED_TOOLS = \{([^}]+)\}", text)
    if not found:
        raise SystemExit("找不到 agentbot._UNTRUSTED_TOOLS，只读结果的消标记对不上")
    names = set()
    for part in found.group(1).split(","):
        name = part.strip().strip("\"'")
        if name:
            names.add(name)
    return names


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]


def clip(text, limit=500):
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def sandbox_cfg(policy):
    """临时配置。确认用确认码，避免受本机卡片回调环境变量影响。不写进仓库。"""
    return {
        "name": "golden",
        "profile": "eval_profile",
        "redact_file": "redact.txt",
        "kb_dir": "kb",
        "bot_names": ["小助手"],
        "texts": {"policy_refuse": "这个话题我不参与讨论。"},
        "tools": {
            "docs_read": {"enabled": True, "allow_tokens": []},
            "docs_create": {"enabled": True},
            "history": {"enabled": True, "days": 7, "max_pages": 2},
            "kb_read": {"enabled": True},
        },
        "write": {
            "enabled": True,
            "confirm_ttl_sec": 300,
            "allowed_users": {"user_admin": "小李"},
            "resources": {
                "folder_token": "fld_golden",
                "docs_append_tokens": [],
                "calendar_id": "cal_golden",
                "base_token": "bsc_golden",
                "table_id": "tbl_golden",
            },
        },
        "confirm": {"mode": "code"},
        "skills": {"enabled": False},
        "memory": {"enabled": False},
        "policy": policy if isinstance(policy, dict) else {"redlines": []},
    }


def write_redact(base, names):
    lines = []
    for name in names or []:
        text = str(name).strip()
        if text and text not in lines:
            lines.append(text)
    with open(os.path.join(base, "redact.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + ("\n" if lines else ""))


def write_kb(base, items):
    root = os.path.join(base, "kb")
    os.makedirs(root, exist_ok=True)
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = os.path.basename(str(item.get("name") or "notes.txt"))
        if not name or name in (".", ".."):
            continue
        with open(os.path.join(root, name), "w", encoding="utf-8") as handle:
            handle.write(str(item.get("text") or ""))


def ctx_of(session):
    session = session or {}
    return {
        "user": str(session.get("sender") or "user_member"),
        "chat_id": str(session.get("chat_id") or "chat_golden"),
        "chat_type": str(session.get("chat_type") or "group"),
        "message_id": str(session.get("message_id") or ""),
        "scope": "",
        "question": str(session.get("text") or ""),
    }


def make_tools(base, cfg, stub, calls):
    log = logging.getLogger("eval-smoke")
    log.handlers.clear()
    log.addHandler(logging.NullHandler())
    log.propagate = False
    tools = Tools(cfg, base, lambda: ["lark-cli"], log, dry=True)

    def fake(argv):
        calls.append(list(argv))
        if isinstance(stub, dict):
            return stub
        return {"ok": True, "data": {}}

    tools.fake = fake
    return tools


def close_tools(tools):
    db = getattr(tools, "_db", None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass
        tools._db = None


def finish_read(name, text, names, untrusted):
    """和 agentbot._run_tool 一样：先脱敏，不可信工具再消标记。模型看到的是这一步之后的文字。"""
    text = guard.redact(text, names)
    if name in untrusted:
        text = guard.neutralize(text)
    return text


def policy_reply(cfg, text):
    rules = guard.policy_rules(cfg, "input")
    hit = guard.policy_hit(text, rules)
    if hit and hit.get("action", "refuse") == "refuse":
        reply = hit.get("reply") or (cfg.get("texts") or {}).get("policy_refuse") or "这个话题我不参与讨论。"
        return True, str(reply)
    return False, ""


def is_write_argv(argv):
    blob = " ".join(str(x) for x in argv)
    return any(mark in blob for mark in WRITE_ARGV)


def load_suite(path):
    data = json.load(open(path, encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise SystemExit("用例文件须是 JSON 对象")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SystemExit("用例文件里没有 cases")
    return cases


def golden_files():
    if not os.path.isdir(GOLDEN):
        raise SystemExit("找不到 " + GOLDEN)
    files = [os.path.join(GOLDEN, name) for name in sorted(os.listdir(GOLDEN)) if name.endswith(".json")]
    if not files:
        raise SystemExit("evals/fixtures/golden 里没有 JSON 用例")
    return files


def scan_text(text, path):
    """用例正文过 history_scan 的同一套白名单。真实编号和密钥在跑断言之前就失败。"""
    bad = []
    for kind, pat in history_scan.PATTERNS.items():
        for match in re.finditer(pat, text):
            if kind == "phone":
                phone = re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", match.group(0))
                if not phone:
                    continue
                value = phone.group(1)
            elif kind == "email":
                value = match.group(0)
            else:
                value = match.group(0)
            if history_scan.fixture(kind, value, path):
                continue
            bad.append("%s %s" % (kind, history_scan.mask(value)))
    for kind, rx in ID_RULES:
        for match in rx.finditer(text):
            body = match.group(0).split("_", 1)[-1]
            if re.search(r"[g-zG-Z]", body):
                continue
            if history_scan.fixture(kind, match.group(0), path):
                continue
            bad.append("%s 缺少 g–z %s" % (kind, history_scan.mask(match.group(0))))
    return bad


def check_ids_in_case(case):
    blob = json.dumps(case, ensure_ascii=False)
    bad = []
    for kind, rx in ID_RULES:
        for match in rx.finditer(blob):
            body = match.group(0).split("_", 1)[-1]
            if not re.search(r"[g-zG-Z]", body):
                bad.append("%s %s" % (kind, match.group(0)))
    return bad


def run_case(case, untrusted):
    kind = str(case.get("kind") or "")
    expect = case.get("expect") if isinstance(case.get("expect"), dict) else {}
    behavior = str(expect.get("behavior") or "")
    session = case.get("session") if isinstance(case.get("session"), dict) else {}
    question = str(session.get("text") or "")
    base = tempfile.mkdtemp(prefix="golden_")
    calls = []
    tools = None
    reply = ""
    refused = False
    error = ""
    try:
        cfg = sandbox_cfg(case.get("policy"))
        write_redact(base, case.get("redact"))
        write_kb(base, case.get("kb"))
        if kind == "policy":
            refused, reply = policy_reply(cfg, question)
        elif kind in ("write", "read"):
            stub = case.get("tool_stub") if isinstance(case.get("tool_stub"), dict) else None
            tools = make_tools(base, cfg, stub, calls)
            call = case.get("tool_call") if isinstance(case.get("tool_call"), dict) else {}
            name = str(call.get("name") or "")
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            actor = ctx_of(session)
            try:
                if kind == "write":
                    if name not in WRITE_TOOLS:
                        error = "未知写入工具 " + name
                    else:
                        reply = tools.propose_write(name, args, actor)
                else:
                    if name not in READ_TOOLS:
                        error = "未知只读工具 " + name
                    else:
                        reply = finish_read(name, tools.run_read(name, args, actor), tools.names, untrusted)
            except ToolError as exc:
                refused = True
                reply = guard.redact(exc.user_msg, tools.names)
        else:
            error = "kind 只能是 policy、write 或 read"
        pending = len(tools.pending) if tools is not None else 0
        names = tools.names if tools is not None else guard.load_names(os.path.join(base, "redact.txt"))
        reply = guard.redact(reply, names) if kind == "write" else reply
    finally:
        if tools is not None:
            close_tools(tools)
        shutil.rmtree(base, ignore_errors=True)
    return grade(case, behavior, reply, refused, calls, pending, error)


def grade(case, behavior, reply, refused, calls, pending, error):
    expect = case.get("expect") if isinstance(case.get("expect"), dict) else {}
    failed = []
    if error:
        failed.append(("用例", error))

    def need(ok, name, detail=""):
        if not ok:
            failed.append((name, detail))

    id_bad = check_ids_in_case(case)
    need(not id_bad, "编号带 g–z", "；".join(id_bad))
    if behavior == "refuse":
        need(refused, "拒答", reply or "没有拒绝")
    elif behavior == "not_refused":
        need(not refused and not reply, "不拒答", reply)
    elif behavior == "needs_confirm":
        need(not refused, "不是拒绝", reply)
        need(bool(CONFIRM_RX.search(reply or "")), "确认码", reply)
        if "pending" not in expect:
            need(pending == 1, "pending=1", str(pending))
    elif behavior == "readonly_ok":
        need(not refused and not error, "只读成功", reply)
        if "pending" not in expect:
            need(pending == 0, "pending=0", str(pending))
    else:
        need(False, "behavior", "须是 refuse / not_refused / needs_confirm / readonly_ok")
    for bit in as_list(expect.get("reply_contains")):
        need(bit in (reply or ""), "reply_contains " + bit, clip(reply))
    for bit in as_list(expect.get("reply_absent")):
        need(bit not in (reply or ""), "reply_absent " + bit, clip(reply))
    if "lark_calls" in expect:
        try:
            want = int(expect.get("lark_calls"))
        except (TypeError, ValueError):
            want = -1
        need(len(calls) == want, "lark_calls=%s" % expect.get("lark_calls"), str(len(calls)))
    if "pending" in expect:
        try:
            want_p = int(expect.get("pending"))
        except (TypeError, ValueError):
            want_p = -1
        need(pending == want_p, "pending=%s" % expect.get("pending"), str(pending))
    wrote = [argv for argv in calls if is_write_argv(argv)]
    need(not wrote, "确认前不写入", " ".join(wrote[0][:6]) if wrote else "")
    return failed, reply


def main(argv):
    parser = argparse.ArgumentParser(description="固定问答回归。不连飞书，不调模型。")
    parser.add_argument("--id", action="append", default=[], help="只跑这一条。可以重复。")
    parser.add_argument("--suite", default="", help="用例 JSON。默认跑 evals/fixtures/golden 里的全部 JSON。")
    args = parser.parse_args(argv)
    files = [os.path.abspath(args.suite)] if args.suite else golden_files()
    for path in files:
        if not os.path.isfile(path):
            print("找不到用例 " + path)
            return 2
        raw = open(path, encoding="utf-8-sig").read()
        leaked = scan_text(raw, os.path.relpath(path, ROOT).replace("\\", "/"))
        if leaked:
            print("失败 白名单 " + path)
            for line in leaked:
                print("  - " + line)
            return 1
    untrusted = untrusted_tools()
    want = set(args.id or [])
    rows = []
    seen = set()
    for path in files:
        for case in load_suite(path):
            cid = str(case.get("id") or "")
            if want and cid not in want:
                continue
            if not cid or cid in seen:
                rows.append((cid or "(无 id)", False, [("id", "缺少或重复")]))
                continue
            seen.add(cid)
            failed, _reply = run_case(case, untrusted)
            rows.append((cid, not failed, failed))
    if want and len(rows) != len(want):
        missing = sorted(want - seen)
        if missing:
            print("没有这些用例：" + "、".join(missing))
            return 2
    if not rows:
        print("没有选中的用例")
        return 2
    passed = 0
    for cid, ok, failed in rows:
        if ok:
            passed += 1
            print("通过 " + cid)
            continue
        print("失败 " + cid)
        for name, detail in failed:
            print("  - " + name)
            if detail:
                print("    " + clip(detail).replace("\n", "\n    "))
    print("%d/%d passed" % (passed, len(rows)))
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
