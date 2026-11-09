# 有界本地控制面：stdio MCP server。默认关：agentbot.py 不认识这个文件，配置里也没有它的开关，
# 由 MCP 客户端（TeleAgent、Claude Desktop 之类）按 mcpServers 配置用子进程拉起，stdin/stdout 逐行 JSON-RPC。
# 为什么是 stdio：这台机器没有能对公网开放的端口（docs/多入口对照与方案.md 结论一），stdio 是
# 父子进程管道，不监听端口、不经网络；本进程只读实例目录里的文件，主程序一个字节不用改。
# 边界抄 OpenMausBot 的 v1 MCP server（github.com/milind-soni/OpenMausBot，docs/mcp-server.md）：
# 只做只读的事；不暴露审批、发送、配置修改、删除，密钥永不进输出——那些留在主人的对话里。
# list_pending 读的是写入确认队列（pending_queue.py），仍然不能代为确认。
# 出这个进程的每个字节都当成出站正文看待：待审文件是访客写的内容，输出前统一过 guard.redact + neutralize。
import json, os, re, sys, time
import utf8io  # noqa: F401  管道强制 UTF-8，import 即生效
import guard, intake, pending_queue

SERVER_NAME = "mimi-agent-mcp"
_PROTOCOL_DEFAULT = "2024-11-05"   # 客户端没带版本时兜底；带了就原样回它的
_MAX_FILE = 1_000_000              # 待审文件读上限。每段几百字节、一次最多二十条，正常远小于这个数
_MAX_LEADS_HITS = 100              # 搜索单次最多返回的段数，与 OpenMausBot 的 search_messages 同款封顶
_MAX_LINE = 1_000_000              # 单行协议消息上限，超了按坏行处理，进程不死


def _product_version():
    """与 feature_switch.product_version 同口径（读代码根的 VERSION，格式不对就空着）。
    不 import 它：那会拉起一大串模块，而这个进程只该认识 guard 和 intake。"""
    try:
        text = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"), encoding="utf-8").read().strip()
    except OSError:
        return ""
    return text if re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", text) else ""


def _die(message):
    sys.stderr.write("[%s] %s\n" % (SERVER_NAME, message))
    sys.exit(2)


def load_instance(cfg_path):
    """读实例配置，算出与 agentbot.py 同款的实例根（base_dir 优先，否则配置文件所在目录）。
    目录口径必须和主程序一致，否则读到的 state、待审文件就不是同一套。"""
    try:
        with open(cfg_path, encoding="utf-8-sig") as handle:
            cfg = json.load(handle)
    except OSError:
        _die("配置读不到：%s" % cfg_path)
    except ValueError as exc:
        _die("配置不是合法 JSON：%s" % exc)
    if not isinstance(cfg, dict):
        _die("配置最外层必须是 JSON 对象")
    base = os.path.abspath(cfg.get("base_dir") or os.path.dirname(os.path.abspath(cfg_path)))
    names = guard.load_names(os.path.join(base, cfg.get("redact_file", "redact.txt")))
    raw = cfg.get("intake") if isinstance(cfg.get("intake"), dict) else {}
    # 借 intake 的私有函数是故意的：待审文件认不认得出，必须和 intake 自己落盘时用同一把尺。
    rel = intake._out_file(raw.get("out_file"))
    return {"base": base, "names": names, "version": _product_version(),
            "intake_enabled": bool(raw.get("enabled")),
            "out_rel": rel, "out_path": guard.safe_path(base, rel)}


class _ToolFail(Exception):
    """工具层失败：变成一张 isError 卡交给客户端，进程不死。"""


def _read_blocks(inst):
    """按「## 」头把待审文件拆成段落。文件开头那行人工抬头和段外空行不算段。
    超过读上限就报错，不截半段——半段会漏时间头，读的人容易当成完整的看。"""
    if inst["out_path"] is None:
        raise _ToolFail("待审文件路径认不出来（绝对路径、盘符或 ..），拒绝读")
    path = inst["out_path"]
    if not os.path.isfile(path):
        return []
    if os.path.getsize(path) > _MAX_FILE:
        raise _ToolFail("待审文件超过 1MB，先人工处理再查")
    blocks, current = [], None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            text = line.rstrip("\n")
            if text.startswith("## "):
                if current is not None:
                    blocks.append(current)
                current = {"head": text[3:].strip(), "lines": []}
            elif current is not None and text.strip():
                current["lines"].append(text.strip())
    if current is not None:
        blocks.append(current)
    for block in blocks:
        block["text"] = "\n".join(block.pop("lines"))
    return blocks


def _wash(text, names):
    """出进程前的最后一道。写盘时已经过一遍，这里再过是防两件事：
    redact.txt 后来加了名字，以及有人手工往文件里贴过没打码的原文。"""
    return guard.neutralize(guard.redact(text or "", names))


def _seen_total(inst):
    """去重账本里的累计条数。这是「拉到过多少」，不是「待审还剩多少」——
    发没发由人决定，文件里没有那笔账，这里不编一个数出来。"""
    try:
        with open(intake._state_path(inst["base"]), encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return None
    return len([x for x in (state.get("ids") or []) if x])


def _tool_status(args, inst):
    now = int(time.time())
    age = None
    try:
        age = now - int((open(os.path.join(inst["base"], "state", "heartbeat"), encoding="utf-8").read() or "").strip())
    except (OSError, ValueError):
        pass
    blocks = _read_blocks(inst)
    return {"version": inst["version"],
            "heartbeat_age_sec": age,
            "intake": {"enabled": inst["intake_enabled"], "out_file": inst["out_rel"],
                       "blocks_total": len(blocks), "seen_total": _seen_total(inst)}}


def _tool_list_leads(args, inst):
    blocks = _read_blocks(inst)
    blocks.reverse()  # 最新在前，和聊天记录的读法一致
    offset = args.get("offset", 0)
    limit = args.get("limit", 20)
    page = blocks[offset:offset + limit]
    return {"total": len(blocks), "offset": offset, "returned": len(page),
            "blocks": [{"head": b["head"], "text": _wash(b["text"], inst["names"])} for b in page]}


def _tool_list_pending(args, inst):
    """待确认写入。view 已经丢掉确认码和编号；摘要再洗一遍，和待审意向同一道出口。"""
    snap = pending_queue.view(inst["base"], names=inst["names"])
    limit = args.get("limit", 20)

    def wash(item):
        out = dict(item)
        out["summary"] = _wash(out.get("summary") or "", inst["names"])
        return out

    pending = [wash(item) for item in snap["pending"][:limit]]
    expired = [wash(item) for item in snap["expired"][:limit]]
    return {"readable": snap["readable"],
            "pending_total": len(snap["pending"]), "expired_total": len(snap["expired"]),
            "pending": pending, "expired": expired}


def _tool_search_leads(args, inst):
    query = args["query"].lower()
    hits = [b for b in _read_blocks(inst) if query in b["head"].lower() or query in b["text"].lower()]
    hits.reverse()
    page = hits[:_MAX_LEADS_HITS]
    return {"total_hits": len(hits), "returned": len(page),
            "blocks": [{"head": b["head"], "text": _wash(b["text"], inst["names"])} for b in page]}


def _validate(args, schema):
    """schema 只用到这一小把：object / integer / string / 数值范围 / 字符串长度 / required / 禁未知字段。
    客户端理应自己校验过，这里再校是防一手：坏参数在门口停下，不进工具。"""
    if not isinstance(args, dict):
        return ["参数必须是 JSON 对象"]
    props = schema.get("properties") or {}
    problems = []
    for key in args:
        if key not in props:
            problems.append("不认识的参数：%s" % key)
    for key, rule in props.items():
        if key not in args:
            if key in (schema.get("required") or []):
                problems.append("缺参数：%s" % key)
            continue
        value = args[key]
        want = rule.get("type")
        if want == "integer" and type(value) is not int:
            problems.append("%s 必须是整数" % key)
            continue
        if want == "string" and not isinstance(value, str):
            problems.append("%s 必须是字符串" % key)
            continue
        if isinstance(value, str):
            if "minLength" in rule and len(value) < rule["minLength"]:
                problems.append("%s 至少 %d 个字符" % (key, rule["minLength"]))
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                problems.append("%s 最多 %d 个字符" % (key, rule["maxLength"]))
        if type(value) is int:
            if "minimum" in rule and value < rule["minimum"]:
                problems.append("%s 不能小于 %d" % (key, rule["minimum"]))
            if "maximum" in rule and value > rule["maximum"]:
                problems.append("%s 不能大于 %d" % (key, rule["maximum"]))
    return problems


def _tool_error(message):
    return {"content": [{"type": "text", "text": message}], "isError": True}


TOOLS = [
    {"name": "get_status",
     "description": "只读：机器人版本、心跳年龄、接待桥开关与累计条数。不下结论、没有写入口；心跳年龄大只说明该去看日志，不说明别的。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _tool_status},
    {"name": "list_leads",
     "description": "只读：待审合作意向段落，最新的在前。发不发由人看完文件决定，这里只读不改；seen_total 是拉到过的累计数，不代表还剩几条没发。",
     "inputSchema": {"type": "object",
                     "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50},
                                    "offset": {"type": "integer", "minimum": 0, "maximum": 10000}},
                     "additionalProperties": False},
     "run": _tool_list_leads},
    {"name": "search_leads",
     "description": "只读：在待审合作意向里搜关键词（大小写不敏感），最多返回 100 段。",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200},
                                    "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                     "required": ["query"], "additionalProperties": False},
     "run": _tool_search_leads},
    {"name": "list_pending",
     "description": "只读：当前待确认的写入提案（最新的在前），以及近期超时记成 expired 的条目。不含确认码、按钮记号、open_id 明文和写入参数；不能审批，也不能代为确认。",
     "inputSchema": {"type": "object",
                     "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
                     "additionalProperties": False},
     "run": _tool_list_pending},
]
_TOOLS = {tool["name"]: tool for tool in TOOLS}
_TOOLS_DESC = [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]} for t in TOOLS]


def call_tool(params, inst):
    if not isinstance(params, dict):
        return _tool_error("工具调用参数必须是 JSON 对象")
    tool = _TOOLS.get(params.get("name"))
    if tool is None:
        return _tool_error("没有这个工具：%s" % params.get("name"))
    args = params.get("arguments")
    if args is None:
        args = {}
    problems = _validate(args, tool["inputSchema"])
    if problems:
        return _tool_error("；".join(problems))
    try:
        payload = tool["run"](args, inst)
    except _ToolFail as exc:
        return _tool_error(str(exc))
    except Exception as exc:  # 工具内部的任何意外都变成一张卡，循环不死——坏一行不带走整个控制面
        return _tool_error("内部错误：%s" % str(exc)[:200])
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "isError": False}


def _rpc_ok(ident, result):
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def _rpc_err(ident, code, message):
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


def handle(msg, inst):
    if not isinstance(msg, dict):
        return _rpc_err(None, -32600, "请求必须是 JSON 对象")
    method = msg.get("method")
    ident = msg.get("id")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if not isinstance(method, str):
        return None if ident is None else _rpc_err(ident, -32600, "method 必须是字符串")
    if method == "initialize":
        if ident is None:
            return None
        version = params.get("protocolVersion")
        if not isinstance(version, str) or not version:
            version = _PROTOCOL_DEFAULT
        return _rpc_ok(ident, {"protocolVersion": version,
                               "capabilities": {"tools": {"listChanged": False}},
                               "serverInfo": {"name": SERVER_NAME, "version": _product_version() or "0"},
                               "instructions": "只读控制面：查机器人状态、看待审合作意向、看待确认的写入。"
                                               "不提供发送、审批、改配置、删除，也没有任何密钥。"})
    if method == "ping":
        return None if ident is None else _rpc_ok(ident, {})
    if method == "tools/list":
        return None if ident is None else _rpc_ok(ident, {"tools": _TOOLS_DESC})
    if method == "tools/call":
        return None if ident is None else _rpc_ok(ident, call_tool(params, inst))
    if ident is None:
        return None  # notifications/initialized 之类的通知：不回，也不会有人等
    return _rpc_err(ident, -32601, "没有这个方法：%s" % method)


def _emit(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve(inst):
    sys.stderr.write("[%s] serving base=%s tools=%d\n" % (SERVER_NAME, inst["base"], len(TOOLS)))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if len(line) > _MAX_LINE:
            _emit(_rpc_err(None, -32700, "这一行太长，不读"))
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            _emit(_rpc_err(None, -32700, "这一行不是 JSON"))
            continue
        try:
            out = handle(msg, inst)
        except Exception as exc:  # 请求处理里的意外变成 -32603，循环不死——控制面崩了，主人就少一只眼睛
            ident = msg.get("id") if isinstance(msg, dict) else None
            out = None if ident is None else _rpc_err(ident, -32603, "内部错误：%s" % str(exc)[:200])
        if out is not None:
            _emit(out)


def main():
    if len(sys.argv) < 2:
        _die("用法：python mcp_server.py <agents/配置.json>    （stdio 协议，由 MCP 客户端按配置拉起）")
    serve(load_instance(sys.argv[1]))


if __name__ == "__main__":
    main()
