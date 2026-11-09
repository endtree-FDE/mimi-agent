# 工具调用的超时档位。总开关默认关：关着时各调用点仍用原来的秒数（多数 60，附件 120），
# 超时仍按原来的网络错误重试。打开后按读 / 写 / 长任务三档限时，超时杀进程、不重试。
# 这套钟只管「这一次命令最多跑多久」。确认码和按钮的时效仍是 write.confirm_ttl_sec / confirm.ttl_sec，
# 到点没确认走 write_expired，跟这里的 tool_timeout_* 不是一回事。
import json

# 保守默认：读比现在的 60 秒短，写接近原来的 60 秒，长任务与附件现在的 120 秒相同。
# 越界退回这些默认值，避免写成 0（有的接口把 0 当成一直等）或写成很大把处理线程占死。
DEFAULT_SEC = {"read": 20, "write": 45, "long": 120}
_BOUNDS = {"read": (5, 60), "write": (10, 120), "long": (30, 180)}
# 下载和本机门禁脚本可能比一次查询慢。其余只读走 read，真正改飞书的命令走 write。
_LONG = {
    "attachment", "message_attachment",
    "evidencegate_check", "decision_gate_check", "evidence_replay_check", "receipt_verify",
}
_WRITE = {
    "docs_create", "docs_append", "calendar_create", "calendar_create_batch",
    "calendar_update", "calendar_delete", "base_create", "memory_propose",
}
REASON = {
    "read": "tool_timeout_read",
    "write": "tool_timeout_write",
    "long": "tool_timeout_long",
}
USER = {
    "read": "这次读取超时了，没有拿到结果，请稍后再试。",
    "write": "这次写入执行超时了，没有改成，请重新发起。",
    "long": "这次耗时任务超时了，已经停掉，请稍后再试。",
}


def _block(cfg):
    tools = (cfg or {}).get("tools")
    if not isinstance(tools, dict):
        return {}
    raw = tools.get("timeouts")
    return raw if isinstance(raw, dict) else {}


def enabled(cfg):
    """只有 JSON 真值 true 才打开。缺省、false、字符串都不改变原来的秒数。"""
    return _block(cfg).get("enabled") is True


def tier_of(tool):
    name = str(tool or "")
    if name in _LONG:
        return "long"
    if name in _WRITE:
        return "write"
    return "read"


def _seconds(raw, tier):
    default = DEFAULT_SEC[tier]
    low, high = _BOUNDS[tier]
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    if isinstance(raw, bool) or n < low or n > high:
        return default
    return n


def settings(cfg):
    raw = _block(cfg)
    return {
        "enabled": enabled(cfg),
        "read_sec": _seconds(raw.get("read_sec", DEFAULT_SEC["read"]), "read"),
        "write_sec": _seconds(raw.get("write_sec", DEFAULT_SEC["write"]), "write"),
        "long_sec": _seconds(raw.get("long_sec", DEFAULT_SEC["long"]), "long"),
    }


def limit_for(cfg, tool, fallback):
    """开关关着时原样退回调用点自己的秒数，连确认时效的数字也不看。"""
    if not enabled(cfg):
        return fallback
    tier = tier_of(tool)
    return settings(cfg)[tier + "_sec"]


def reap_sec(cfg):
    """杀掉子进程后再等管道结束的秒数。开着时改短，避免收尸把处理线程再拖一轮。"""
    return 2 if enabled(cfg) else 15


def pack(tier):
    name = tier if tier in USER else "read"
    code = REASON[name]
    return {
        "tier": name,
        "code": code,
        "user_msg": USER[name],
        "detail": json.dumps({"code": code, "tier": name}, ensure_ascii=False),
    }


def is_user_message(text):
    return str(text or "") in USER.values()
