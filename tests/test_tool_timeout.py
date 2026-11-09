# 工具超时档位：默认关，打开后读/写/长三档，超时杀进程并给一句原因。
# 假编号只用扫描器已经放过的尾巴（placeholder、字母名），不引用实例生产配置。
import json, logging, os, re, shutil, subprocess, sys, tempfile, time

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401
import crew, observe, tool_timeout
import tools as tools_mod
from checks.check_config import check_data, load_schema
from tools import ToolError, ToolTimeout, Tools, run_capture

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(str(detail)[-1500:])


def alive(pid):
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------- 档位与确认时效分开 ----------
bare = {"write": {"confirm_ttl_sec": 999}, "confirm": {"ttl_sec": 888}}
check("没写 timeouts 时沿用调用点自己的秒数，不读确认时效",
      tool_timeout.enabled(bare) is False
      and tool_timeout.limit_for(bare, "docs_read", 60) == 60
      and tool_timeout.limit_for(bare, "docs_create", 60) == 60
      and tool_timeout.limit_for(bare, "attachment", 120) == 120
      and tool_timeout.reap_sec(bare) == 15)
off = {"tools": {"timeouts": {"enabled": False, "read_sec": 5, "write_sec": 10, "long_sec": 30}},
       "write": {"confirm_ttl_sec": 999}, "confirm": {"ttl_sec": 888}}
check("enabled 不是 true 时即使写了秒数也不生效",
      tool_timeout.limit_for(off, "history", 60) == 60 and tool_timeout.reap_sec(off) == 15)
check("字符串 false 不会把档位打开",
      tool_timeout.enabled({"tools": {"timeouts": {"enabled": "false"}}}) is False)
on = {"tools": {"timeouts": {"enabled": True}}, "write": {"confirm_ttl_sec": 999}, "confirm": {"ttl_sec": 888}}
got = tool_timeout.settings(on)
check("打开后用保守默认，仍然不是确认码或按钮的秒数",
      got["read_sec"] == 20 and got["write_sec"] == 45 and got["long_sec"] == 120
      and tool_timeout.limit_for(on, "docs_read", 60) == 20
      and tool_timeout.limit_for(on, "calendar_create", 60) == 45
      and tool_timeout.limit_for(on, "attachment", 120) == 120
      and tool_timeout.limit_for(on, "evidencegate_check", 60) == 120
      and tool_timeout.limit_for(on, "message_attachment", 60) == 120
      and tool_timeout.reap_sec(on) == 2
      and 999 not in (got["read_sec"], got["write_sec"], got["long_sec"])
      and 888 not in (got["read_sec"], got["write_sec"], got["long_sec"]))
bad = {"tools": {"timeouts": {"enabled": True, "read_sec": 0, "write_sec": 9999, "long_sec": "慢"}}}
bad_s = tool_timeout.settings(bad)
check("越界或写错退回默认，不把 0 当成一直等",
      bad_s["read_sec"] == 20 and bad_s["write_sec"] == 45 and bad_s["long_sec"] == 120)
check("档位划分：读短、写中、长任务更长",
      tool_timeout.tier_of("kb_read") == "read" and tool_timeout.tier_of("docs_append") == "write"
      and tool_timeout.tier_of("receipt_verify") == "long" and tool_timeout.tier_of("decision_gate_check") == "long")
packed = tool_timeout.pack("read")
check("原因码能从 detail 里取出来，回复是一句完整的话",
      packed["code"] == "tool_timeout_read" and observe.code_of(packed["detail"]) == "tool_timeout_read"
      and packed["user_msg"].endswith("。") and "\n" not in packed["user_msg"]
      and tool_timeout.is_user_message(packed["user_msg"]))

ex = json.load(open(os.path.join(FW, "agents", "example.json"), encoding="utf-8-sig"))
ex_err, _ex_hints = check_data(ex, "example.json", load_schema())
check("示例里档位默认关，并且通过配置检查",
      (ex.get("tools") or {}).get("timeouts", {}).get("enabled") is False and not ex_err, ex_err)

# ---------- 真进程：超时会杀掉，并且很快返回 ----------
pid_dir = tempfile.mkdtemp(prefix="agentbot_to_")
pid_path = os.path.join(pid_dir, "pid.txt")
sleeper = "import os, time; open(%r, 'w').write(str(os.getpid())); time.sleep(30)" % pid_path
t0 = time.monotonic()
killed = False
try:
    run_capture([sys.executable, "-c", sleeper], timeout=1, reap=1)
except subprocess.TimeoutExpired:
    killed = True
elapsed = time.monotonic() - t0
pid = 0
try:
    pid = int(open(pid_path, encoding="utf-8").read().strip())
except (OSError, ValueError):
    pid = 0
# 留一点点时间让系统收掉已杀死的进程。
time.sleep(0.2)
check("超时会杀掉子进程并且很快返回，不会干等完整的睡眠",
      killed and elapsed < 6 and pid > 0 and not alive(pid), "elapsed=%.2f pid=%s" % (elapsed, pid))
shutil.rmtree(pid_dir, ignore_errors=True)

# ---------- lark：开着只试一次；关着仍重试，且不升级成档位原因码 ----------
def new_tools(timeouts=None, live=False):
    base = tempfile.mkdtemp(prefix="agentbot_tt_")
    os.makedirs(os.path.join(base, "state"), exist_ok=True)
    with open(os.path.join(base, "redact.txt"), "w", encoding="utf-8") as handle:
        handle.write("杭州某某科技有限公司\n")
    cfg = {
        "name": "t", "profile": "placeholder", "redact_file": "redact.txt",
        "bot_names": ["小助手"], "bot_open_id": "ou_placeholder",
        "tools": {
            "docs_read": {"enabled": True},
            "docs_create": {"enabled": True},
            "attachment": {"enabled": True},
            "evidencegate_check": {"enabled": True},
        },
        "write": {
            "enabled": True, "confirm_ttl_sec": 300,
            "allowed_users": {"user_admin": "管理员"},
            "resources": {"folder_token": "fldTEST", "docs_append_tokens": ["doxTEST"],
                          "calendar_id": "calTEST", "base_token": "basTEST", "table_id": "tblTEST"},
        },
        "confirm": {"ttl_sec": 600, "mode": "code"},
        "skills": {"enabled": False}, "memory": {"enabled": False},
    }
    if timeouts is not None:
        cfg["tools"]["timeouts"] = timeouts
    log = logging.getLogger("tool-timeout-test")
    log.handlers.clear()
    log.setLevel(logging.INFO)
    box = []

    class Grab(logging.Handler):
        def emit(self, record):
            box.append(record.getMessage())

    log.addHandler(Grab())
    obj = Tools(cfg, base, lambda: ["lark-cli"], log, dry=not live)
    return obj, box, base, cfg


orig_capture = tools_mod.run_capture
orig_sleep = tools_mod.time.sleep
planted = "app_secret=" + "abc"
reader_base = long_base = writer_base = None


def restore():
    tools_mod.run_capture = orig_capture
    tools_mod.time.sleep = orig_sleep


try:
    seen = []

    def boom(cmd, cwd=None, timeout=60, reap=15):
        seen.append((timeout, reap, list(cmd)))
        raise subprocess.TimeoutExpired(cmd, timeout)

    tools_mod.run_capture = boom
    tools_mod.time.sleep = lambda _s: None
    reader, reader_log, reader_base, _cfg = new_tools({"enabled": True, "read_sec": 20, "write_sec": 45, "long_sec": 120}, live=True)
    raised = None
    try:
        reader.lark("docs_read", ["docs", "+fetch", "--doc", "doxTEST", planted])
    except ToolTimeout as exc:
        raised = exc
    except Exception as exc:
        raised = exc
    log_blob = "\n".join(reader_log)
    check("打开后读超时只试一次，收尸时间变短，回复带读的原因码",
          len(seen) == 1 and seen[0][0] == 20 and seen[0][1] == 2
          and isinstance(raised, ToolTimeout) and raised.code == "tool_timeout_read"
          and raised.user_msg == tool_timeout.USER["read"]
          and "tool_timeout_read" in log_blob and planted not in log_blob and "doxTEST" not in log_blob,
          log_blob + "\n" + str(raised))
    audit = ""
    audit_dir = os.path.join(reader_base, "audit")
    if os.path.isdir(audit_dir):
        for name in os.listdir(audit_dir):
            audit += open(os.path.join(audit_dir, name), encoding="utf-8").read()
    ctx = {"user": "user_admin", "chat_id": "chat_timeout", "chat_type": "group", "message_id": "msg_timeout1"}
    read_exc = None
    try:
        reader.run_read("docs_read", {"doc": "doxTEST"}, ctx)
    except ToolTimeout as exc:
        read_exc = exc
    audit = ""
    if os.path.isdir(audit_dir):
        for name in os.listdir(audit_dir):
            audit += open(os.path.join(audit_dir, name), encoding="utf-8").read()
    check("读超时记入审计的是原因码，没有命令行里的假密钥",
          isinstance(read_exc, ToolTimeout) and "tool_timeout_read" in audit and planted not in audit
          and "write_expired" not in audit, audit[-800:])

    seen.clear()
    long_tools, _long_log, long_base, _c = new_tools({"enabled": True, "long_sec": 30}, live=True)
    tmp_root = os.path.join(long_base, "down")
    os.makedirs(tmp_root, exist_ok=True)
    att_exc = None
    try:
        long_tools.fetch_attachments("om_placeholder", ctx, tmp_root)
    except ToolTimeout as exc:
        att_exc = exc
    left = []
    if os.path.isdir(tmp_root):
        left = os.listdir(tmp_root)
    check("附件超时用长档位，临时目录会被清掉",
          isinstance(att_exc, ToolTimeout) and att_exc.code == "tool_timeout_long"
          and seen and seen[-1][0] == 30 and not left, "left=%s timeout=%s" % (left, seen[-1] if seen else None))

    # 关着：仍把超时当成网络错误重试三次，不抛档位异常。
    seen.clear()
    plain, plain_log, _b, _c = new_tools(None, live=True)
    plain_exc = None
    try:
        plain.lark("docs_read", ["docs", "+fetch", "--doc", "doxTEST"])
    except ToolError as exc:
        plain_exc = exc
    check("关闭时超时仍重试，不使用档位原因码",
          len(seen) == 3 and all(item[0] == 60 and item[1] == 15 for item in seen)
          and isinstance(plain_exc, ToolError) and not isinstance(plain_exc, ToolTimeout)
          and "tool_timeout_read" not in "\n".join(plain_log),
          "n=%d %s" % (len(seen), plain_exc))
finally:
    restore()
    if reader_base:
        shutil.rmtree(reader_base, ignore_errors=True)
    if long_base:
        shutil.rmtree(long_base, ignore_errors=True)

# ---------- 写入超时不碰另一条还没到期的确认 ----------
try:
    seen = []

    def boom(cmd, cwd=None, timeout=60, reap=15):
        seen.append((timeout, reap))
        raise subprocess.TimeoutExpired(cmd, timeout)

    tools_mod.run_capture = boom
    tools_mod.time.sleep = lambda _s: None
    writer, _wlog, writer_base, writer_cfg = new_tools({"enabled": True}, live=True)
    ctx = {"user": "user_admin", "chat_id": "chat_timeout", "chat_type": "group",
           "message_id": "msg_timeout1", "scope": "", "question": "建一份文档"}
    writer.propose_write("docs_create", {"title": "周报", "markdown": "内容"}, ctx)
    writer.propose_write("docs_create", {"title": "另一份", "markdown": "还没确认"}, ctx)
    codes = list(writer.pending)
    check("两条确认都还在", len(codes) == 2, str(codes))
    if len(codes) == 2:
        first, second = codes[0], codes[1]
        expires = writer.pending[second].get("expires")
        text = writer.confirm(first, ctx)
        still = writer.pending.get(second)
        audit = ""
        audit_dir = os.path.join(writer_base, "audit")
        for name in os.listdir(audit_dir):
            audit += open(os.path.join(audit_dir, name), encoding="utf-8").read()
        kinds = [json.loads(line).get("kind") for line in audit.splitlines() if line.strip()]
        check("写入超时只停这一次，另一条确认的到期时间不变",
              text == tool_timeout.USER["write"] and still and still.get("expires") == expires
              and "write_failed" in kinds and "write_expired" not in kinds
              and seen and seen[0][0] == 45
              and writer_cfg["write"]["confirm_ttl_sec"] == 300
              and writer_cfg["confirm"]["ttl_sec"] == 600,
              text + "\n" + audit[-800:])
finally:
    restore()
    if writer_base:
        shutil.rmtree(writer_base, ignore_errors=True)

# ---------- 主理人遇到超时就停，不再汇总 ----------
calls = {"n": 0}


def complete(_prompt):
    calls["n"] += 1
    return '<<TOOL>>{"tool":"kb_read","args":{"path":"notes.md"}}'


def run_tool(name, args, ctx):
    return tool_timeout.USER["read"], True


crew_cfg = {"agent": {"crew": {"enabled": True, "total_rounds": 4, "step_rounds": 2, "total_sec": 30, "step_sec": 10}}}
crew_text = crew.run(crew_cfg, "查一下资料并且读一下文档", {}, complete, run_tool, names=[])
check("超时那一句直接交还给用户，不再继续叫模型",
      crew_text == tool_timeout.USER["read"] and calls["n"] == 1, crew_text)

# ---------- 回复路径：读超时不再交给模型编一句 ----------
reply_base = tempfile.mkdtemp(prefix="agentbot_tt_bot_")
try:
    src = json.load(open(os.path.join(FW, "agents", "example.json"), encoding="utf-8-sig"))
    src["base_dir"] = reply_base
    src["profile"] = "placeholder"
    src["bot_open_id"] = "ou_placeholder"
    src["dry_run_live_reads"] = True
    src["tools"]["timeouts"] = {"enabled": True, "read_sec": 20, "write_sec": 45, "long_sec": 120}
    src["skills"]["enabled"] = False
    src["memory"]["enabled"] = False
    src["progress"] = {"enabled": False}
    path = os.path.join(reply_base, "c.json")
    json.dump(src, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    sys.argv = ["agentbot.py", path, "--dry-run"]
    import agentbot

    def boom(cmd, cwd=None, timeout=60, reap=15):
        raise subprocess.TimeoutExpired(cmd, timeout)

    tools_mod.run_capture = boom
    ctx = {"user": "user_admin", "chat_id": "chat_timeout", "chat_type": "group",
           "message_id": "msg_timeout1", "limited": False}
    text, done = agentbot._run_tool("docs_read", {"doc": "doxTEST"}, ctx, None)
    check("处理这一题时超时就用那一句收尾，并记下原因码",
          done and text == tool_timeout.USER["read"] and ctx.get("_tool_timeout") == "tool_timeout_read",
          text)
finally:
    restore()
    shutil.rmtree(reply_base, ignore_errors=True)

import search_backend
search_base = off_base = None
search_tools, _slog, search_base, search_cfg = new_tools({"enabled": True, "read_sec": 20})
search_cfg["search"] = {"enabled": True, "backend": "searxng", "base_url": "https://example.com", "timeout_sec": 60}
capped = search_tools._search_cfg()
check("网页搜索的等待不超过读档，原来的配置数字还在",
      capped is not search_cfg and capped["search"]["timeout_sec"] == 20
      and search_cfg["search"]["timeout_sec"] == 60)
def _search_timed_out(cfg, args, names=()):
    raise search_backend.SearchTimeout()

orig_run = search_backend.run
search_backend.run = _search_timed_out
try:
    try:
        search_tools._web_search({"query": "天气"}, {"user": "user_admin", "chat_id": "chat_timeout"})
        check("网页搜索超时走读档原因码", False)
    except ToolTimeout as exc:
        check("网页搜索超时走读档原因码", exc.code == "tool_timeout_read" and exc.user_msg == tool_timeout.USER["read"])
    off_tools, _o, off_base, _oc = new_tools(None)
    try:
        off_tools._web_search({"query": "天气"}, {"user": "user_admin", "chat_id": "chat_timeout"})
        check("档位关闭时搜索超时仍是原来的失败句", False)
    except ToolError as exc:
        check("档位关闭时搜索超时仍是原来的失败句",
              not isinstance(exc, ToolTimeout) and exc.user_msg == "搜索请求失败", exc.user_msg)
finally:
    search_backend.run = orig_run
    if search_base:
        shutil.rmtree(search_base, ignore_errors=True)
    if off_base:
        shutil.rmtree(off_base, ignore_errors=True)

print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if results and all(ok for _, ok in results) else 1)
