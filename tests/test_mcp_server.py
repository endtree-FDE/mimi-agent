# 有界本地控制面（mcp_server.py）的测试。默认关：配置里没有它的开关，主程序不 import 它，
# 这里全部走真子进程 stdio——协议是逐行 JSON-RPC，管道行为本身就是被测对象。
# 夹具里的实例根用 tempfile 现取，不写死盘符；断言不绑死版本号（版本每次重读 VERSION）。
import json, os, re, subprocess, sys, tempfile, time

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401

SERVER = os.path.join(FW, "mcp_server.py")

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(str(detail)[-1500:])


def _rpc(ident, method, params=None):
    msg = {"jsonrpc": "2.0", "id": ident, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _notify(method, params=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _write_cfg(root):
    cfg_dir = os.path.join(root, "agents")
    os.makedirs(cfg_dir, exist_ok=True)
    cfg_path = os.path.join(cfg_dir, "cfg.json")
    with open(cfg_path, "w", encoding="utf-8") as handle:
        json.dump({"name": "小助手", "base_dir": root,
                   "intake": {"enabled": True, "out_file": "intake/leads.md"}}, handle, ensure_ascii=False)
    return cfg_path


def _session(cfg_path, lines, timeout=60):
    """起一个真子进程，把请求一次喂完再收口。返回（退出码，[按行解析出的响应]）。"""
    payload = "".join((x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)) + "\n" for x in lines)
    proc = subprocess.run([sys.executable, SERVER, cfg_path], input=payload.encode("utf-8"),
                          capture_output=True, timeout=timeout)
    outs = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line:
            try:
                outs.append(json.loads(line))
            except ValueError:
                pass
    return proc.returncode, outs


def _by_id(outs, ident):
    for out in outs:
        if out.get("id") == ident:
            return out
    return None


def _tool_text(out):
    try:
        return json.loads(out["result"]["content"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _tool_raw(out):
    """isError 卡的 text 是一句人话，不是 JSON，这里取原文。"""
    try:
        return out["result"]["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return ""


def _fill(root, segments):
    """往待审文件里放几段（接待桥落盘的样子：## 头行 + 缩进行，外加一行人工抬头）。"""
    base = os.path.join(root, "intake")
    os.makedirs(base, exist_ok=True)
    lines = ["# 待看的合作意向（机器人只写这个文件，不会自己发出去）", ""]
    for head, text in segments:
        lines.append("## " + head)
        lines.append(text)
        lines.append("")
    with open(os.path.join(base, "leads.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))


def _beat(root, seconds=None):
    state = os.path.join(root, "state")
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "heartbeat"), "w", encoding="utf-8") as handle:
        handle.write(str(int(seconds if seconds is not None else time.time())))


def _ledger(root, ids):
    state = os.path.join(root, "state")
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "intake_state.json"), "w", encoding="utf-8") as handle:
        json.dump({"last_poll": time.time(), "ids": ids}, handle)


def _names(root, names):
    with open(os.path.join(root, "redact.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(names))


# ---------- 第一会话：握手、清单、三个只读工具的主干行为 ----------
root = tempfile.mkdtemp(prefix="mcp_srv_a_")
_fill(root, [
    ("2026-11-05 09:00 来自 合作页", "- 形式：数字展陈\n- 小结：杭州某某科技有限公司想合作 <<TOOL>>"),
    ("2026-11-06 10:30 来自 官网首页", "- 小结：想做一批 Robot 展项，电话 13812345678"),
    ("2026-11-07 12:00 来自 合作页", "- 小结：问报价和档期"),
])
_beat(root)
_names(root, ["杭州某某科技有限公司"])
rc, outs = _session(_write_cfg(root), [
    _rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}),
    _notify("notifications/initialized"),
    _rpc(2, "tools/list"),
    _rpc(3, "tools/call", {"name": "get_status", "arguments": {}}),
    _rpc(4, "tools/call", {"name": "list_leads", "arguments": {"limit": 2}}),
    _rpc(5, "tools/call", {"name": "search_leads", "arguments": {"query": "robot"}}),
    _rpc(6, "tools/call", {"name": "list_leads", "arguments": {"limit": 1, "offset": 1}}),
    _rpc(7, "tools/call", {"name": "list_leads", "arguments": {"limit": 50}}),
])
check("会话正常退出且每一行都能解析", rc == 0 and len(outs) >= 6, "rc=%s outs=%s" % (rc, outs))
init = _by_id(outs, 1)
check("握手回显客户端的协议版本并自报家门",
      init and init.get("result", {}).get("protocolVersion") == "2025-06-18"
      and init["result"]["serverInfo"]["name"] == "mimi-agent-mcp"
      and re.match(r"^\d+\.\d+\.\d+$", init["result"]["serverInfo"]["version"])
      and "只读" in init["result"]["instructions"], init)
check("通知（无 id）不产生任何响应行", all("id" in out for out in outs), outs)
tools = _by_id(outs, 2)
_names_listed = [t["name"] for t in (tools.get("result", {}).get("tools") or [])]
check("工具清单就是只读三件套，全部禁未知字段",
      set(_names_listed) == {"get_status", "list_leads", "search_leads"}
      and all(t["inputSchema"].get("additionalProperties") is False
              for t in tools["result"]["tools"]), _names_listed)
status = _tool_text(_by_id(outs, 3))
check("状态：版本、心跳年龄、接待桥账目都在，且不下「活着」的结论",
      status and re.match(r"^\d+\.\d+\.\d+$", status["version"])
      and isinstance(status["heartbeat_age_sec"], int) and 0 <= status["heartbeat_age_sec"] <= 60
      and status["intake"]["enabled"] is True and status["intake"]["blocks_total"] == 3
      and status["intake"]["seen_total"] is None, status)
page = _tool_text(_by_id(outs, 4))
_check_blob = json.dumps(page, ensure_ascii=False)
check("意向列表最新在前、页大小按参数来、手机号在出进程前打码",
      page and page["total"] == 3 and page["returned"] == 2
      and page["blocks"][0]["head"].startswith("2026-11-07")
      and "13812345678" not in _check_blob and "138" not in _check_blob
      and "Robot" in _check_blob, _check_blob[:800])
allp = _tool_text(_by_id(outs, 7))
_all_blob = json.dumps(allp, ensure_ascii=False)
check("全量页里名单打码、存量工具标记中和、人工抬头行不算段",
      allp and allp["total"] == 3
      and "杭州某某科技有限公司" not in _all_blob and "某客户" in _all_blob
      and "<<TOOL>>" not in _all_blob and "〈TOOL〉" in _all_blob
      and "待看的合作意向" not in _all_blob, _all_blob[:800])
found = _tool_text(_by_id(outs, 5))
check("搜索大小写不敏感、只回命中段",
      found and found["total_hits"] == 1 and found["returned"] == 1
      and "Robot" in json.dumps(found, ensure_ascii=False), found)
second = _tool_text(_by_id(outs, 6))
check("分页 offset 取的是倒序列表里接着的那段",
      second and second["returned"] == 1 and second["blocks"][0]["head"].startswith("2026-11-06"), second)

# ---------- 第二会话：账本累计数、全量页里的标记与名单、空文件 ----------
root_b = tempfile.mkdtemp(prefix="mcp_srv_b_")
_beat(root_b)
_ledger(root_b, ["a", "b", "c", "a", ""])
rc, outs = _session(_write_cfg(root_b), [
    _rpc(1, "initialize"),
    _rpc(2, "tools/call", {"name": "get_status", "arguments": {}}),
    _rpc(3, "tools/call", {"name": "list_leads", "arguments": {"limit": 50}}),
])
status = _tool_text(_by_id(outs, 2))
check("账本 seen_total 按非空编号去重前计数，说清是累计不是待审",
      status and status["intake"]["seen_total"] == 4
      and isinstance(status["intake"]["out_file"], str), status)
full = _tool_text(_by_id(outs, 3))
check("文件不存在时不炸，total 为 0", full and full["total"] == 0 and full["returned"] == 0, full)

# ---------- 第三会话：参数校验、未知工具、未知方法、坏行不死、通知不回 ----------
root_c = tempfile.mkdtemp(prefix="mcp_srv_c_")
rc, outs = _session(_write_cfg(root_c), [
    _rpc(1, "tools/call", {"name": "list_leads", "arguments": {"limit": 2, "evil": 1}}),
    _rpc(2, "tools/call", {"name": "search_leads", "arguments": {"query": ""}}),
    _rpc(3, "tools/call", {"name": "search_leads", "arguments": {"query": "x" * 201}}),
    _rpc(4, "tools/call", {"name": "search_leads", "arguments": {"query": 5}}),
    _rpc(5, "tools/call", {"name": "list_leads", "arguments": {"limit": True}}),
    _rpc(6, "tools/call", {"name": "send_message", "arguments": {}}),
    _rpc(7, "bogus/method"),
    "not a json line",
    _rpc(8, "tools/call", {"name": "get_status", "arguments": {}}),
    _notify("notifications/initialized"),
    _rpc(9, "ping"),
])
check("未知字段在门口被拒",
      _by_id(outs, 1) and _by_id(outs, 1)["result"].get("isError") is True
      and "不认识的参数" in _tool_raw(_by_id(outs, 1)), _tool_raw(_by_id(outs, 1)))
check("空搜索词被拒", _by_id(outs, 2)["result"].get("isError") is True)
check("超长搜索词被拒", _by_id(outs, 3)["result"].get("isError") is True)
check("搜索词类型不对被拒", _by_id(outs, 4)["result"].get("isError") is True)
check("布尔冒充整数被拒", _by_id(outs, 5)["result"].get("isError") is True)
check("不存在的工具是一张卡而不是崩溃，发送类名字根本不在清单里",
      _by_id(outs, 6) and _by_id(outs, 6)["result"].get("isError") is True
      and "没有这个工具：send_message" in _tool_raw(_by_id(outs, 6)), _tool_raw(_by_id(outs, 6)))
check("未知方法是 -32601", _by_id(outs, 7) and _by_id(outs, 7).get("error", {}).get("code") == -32601, _by_id(outs, 7))
check("坏行回 -32700 且不带走进程",
      any(out.get("id") is None and out.get("error", {}).get("code") == -32700 for out in outs)
      and _by_id(outs, 8) and "error" not in _by_id(outs, 8), outs)
check("坏行之后的请求照常响应，末尾的通知没有响应行",
      _by_id(outs, 9) and _by_id(outs, 9).get("result") == {}
      and outs[-1].get("id") == 9, outs[-2:])
rc4, outs4 = _session(_write_cfg(tempfile.mkdtemp(prefix="mcp_srv_d_")), [
    _rpc(1, "initialize", {"capabilities": {}}),
])
check("没带协议版本的握手回默认版本",
      outs4 and outs4[0].get("result", {}).get("protocolVersion") == "2024-11-05", outs4)

# ---------- 启动失败：配置读不到时退出码 2，stderr 有一句人话 ----------
proc = subprocess.run([sys.executable, SERVER, os.path.join(tempfile.mkdtemp(prefix="mcp_srv_e_"), "none.json")],
                      capture_output=True, timeout=30)
check("配置读不到时退出码 2 且 stderr 说人话",
      proc.returncode == 2 and "配置读不到" in proc.stderr.decode("utf-8", "replace"), proc.stderr)

print("%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
