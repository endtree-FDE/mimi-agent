# 确认超时之后的只读状态。时效仍用 write.confirm_ttl_sec / confirm.ttl_sec，这里不另设时钟。
# 过期记录写在实例目录 state/confirm_expired.jsonl（gitignore）。查询不建库、不删行、不发消息。
# 输出只留工具名、状态和短哈希：确认码、按钮记号、写入参数、open_id 明文都不出去。
import hashlib, json, os, re, sqlite3, sys, time, urllib.request
import guard

_MAX_EXPIRED = 100
_MODES = {"button", "code", "button_or_code", "button_and_code"}
_NOTIFY = {"off", "dry", "no_route", "sent", "fail", "already"}
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_ID_LEAK = re.compile(r"\b(?:ou|oc|on|om|cli)_[A-Za-z0-9]{4,}\b")
_TOOL = re.compile(r"[A-Za-z0-9_]{1,40}")
_PUBLIC = ("status", "tool", "age_sec", "left_sec", "mode", "dual", "first_ok",
           "user_hash", "chat_hash", "summary", "notify")


def expired_path(base):
    return os.path.join(base, "state", "confirm_expired.jsonl")


def _db_path(base):
    return os.path.join(base, "state", "state.db")


def _code_hash(code):
    return hashlib.sha256(str(code or "").encode("utf-8")).hexdigest()[:12]


def _actor_hash(value):
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _summary(rec, names, code=""):
    text = str((rec or {}).get("summary") or "")
    token = str((rec or {}).get("token") or "")
    if code and code in text:
        text = text.replace(code, "[确认码]")
    if token and len(token) >= 8 and token in text:
        text = text.replace(token, "[确认]")
    user = str((rec or {}).get("user") or "")
    chat = str((rec or {}).get("chat_id") or "")
    if user and user in text:
        text = text.replace(user, "[编号已隐藏]")
    if chat and chat in text:
        text = text.replace(chat, "[编号已隐藏]")
    text = guard.neutralize(guard.redact(text, names or []))
    text = _ID_LEAK.sub("[编号已隐藏]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 80:
        text = text[:80].rstrip() + "…"
    return text


def _is_stale(rec, now, ttl):
    if not isinstance(rec, dict):
        return True
    if rec.get("expires") not in (None, ""):
        try:
            return now > float(rec["expires"])
        except (TypeError, ValueError):
            return True
    try:
        ts = float(rec.get("ts") or 0)
    except (TypeError, ValueError):
        return True
    return now - ts > float(ttl)


def _public(rec, status, now, names, code="", notify=""):
    """白名单字段。调用方传进来的 payload 里多出来的键（参数、正文、记号）一律丢掉。"""
    rec = rec if isinstance(rec, dict) else {}
    tool = str(rec.get("tool") or "")
    if not _TOOL.fullmatch(tool):
        tool = "unknown"
    mode = rec.get("mode") if rec.get("mode") in _MODES else ""
    try:
        ts = float(rec.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0
    try:
        expires = float(rec.get("expires") or 0)
    except (TypeError, ValueError):
        expires = 0
    age = max(0, int(now - ts)) if ts else 0
    left = max(0, int(expires - now)) if expires and status == "pending" else 0
    item = {
        "status": status,
        "tool": tool,
        "age_sec": age,
        "left_sec": left,
        "mode": mode,
        "dual": bool(rec.get("dual")),
        "first_ok": bool(rec.get("first_ok")),
        "user_hash": _actor_hash(rec.get("user")),
        "chat_hash": _actor_hash(rec.get("chat_id")),
        "summary": _summary(rec, names, code),
    }
    if status == "expired":
        item["notify"] = notify if notify in _NOTIFY else "off"
    return item


def _connect_ro(path):
    uri = "file:%s?mode=ro" % urllib.request.pathname2url(os.path.abspath(path))
    return sqlite3.connect(uri, uri=True)


def _read_db(base, now, names, ttl):
    path = _db_path(base)
    if not os.path.isfile(path):
        return [], []
    conn = _connect_ro(path)
    try:
        rows = list(conn.execute("select code, ts, payload from pending_writes"))
    finally:
        conn.close()
    pending, stale = [], []
    for code, ts, payload in rows:
        try:
            rec = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        if "ts" not in rec and ts is not None:
            rec["ts"] = ts
        code = str(code or "")
        if _is_stale(rec, now, ttl):
            stale.append((code, _public(rec, "expired", now, names, code, "off")))
        else:
            pending.append(_public(rec, "pending", now, names, code))
    pending.sort(key=lambda item: item["age_sec"])
    return pending, stale


def _load_file(base):
    path = expired_path(base)
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                rows.append(rec)
    return rows


def _stored_public(rec, names):
    """文件里可能被人手工加过编号。读出来时再过一遍白名单和打码。"""
    item = {key: rec.get(key) for key in _PUBLIC if key in rec}
    item["status"] = "expired"
    tool = str(item.get("tool") or "")
    item["tool"] = tool if _TOOL.fullmatch(tool) else "unknown"
    if item.get("mode") not in _MODES:
        item["mode"] = ""
    item["dual"] = bool(item.get("dual"))
    item["first_ok"] = bool(item.get("first_ok"))
    for key in ("age_sec", "left_sec"):
        try:
            item[key] = max(0, int(item.get(key) or 0))
        except (TypeError, ValueError):
            item[key] = 0
    item["left_sec"] = 0
    # 短哈希是 8 位十六进制。不是这种形状的（例如被人写成了 open_id）直接丢掉。
    for key in ("user_hash", "chat_hash"):
        value = str(item.get(key) or "")
        item[key] = value if re.fullmatch(r"[0-9a-f]{8}", value) else ""
    item["summary"] = _summary({"summary": item.get("summary") or ""}, names)
    notify = str(item.get("notify") or "off")
    item["notify"] = notify if notify in _NOTIFY else "off"
    return item


def view(base, now=None, names=None, ttl=300):
    """只读。没有 state.db 时返回空列表，不创建文件。"""
    now = time.time() if now is None else float(now)
    try:
        ttl = int(ttl)
    except (TypeError, ValueError):
        ttl = 300
    if ttl < 1:
        ttl = 300
    names = names or []
    try:
        pending, stale = _read_db(base, now, names, ttl)
        noted = []
        seen = set()
        for rec in _load_file(base):
            digest = str(rec.get("code_hash") or "")
            if digest:
                seen.add(digest)
            noted.append(_stored_public(rec, names))
        for code, item in stale:
            digest = _code_hash(code)
            if digest in seen:
                continue
            noted.append(item)
        noted.reverse()
        return {"readable": True, "pending": pending, "expired": noted}
    except Exception:
        return {"readable": False, "pending": [], "expired": []}


def already_noted(base, code):
    want = _code_hash(code)
    if not want:
        return False
    try:
        return any(str(row.get("code_hash") or "") == want for row in _load_file(base))
    except Exception:
        return False


def _write_all(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def note_expired(base, code, rec, notify, names=None, now=None):
    """追加一条 expired。同一个确认码只记一次，避免重启重复刷文件。"""
    now = time.time() if now is None else float(now)
    want = _code_hash(code)
    rows = _load_file(base)
    if any(str(row.get("code_hash") or "") == want for row in rows):
        return False
    item = _public(rec, "expired", now, names or [], code, notify)
    item["code_hash"] = want
    item["expired_at"] = int(now)
    rows.append({key: item[key] for key in list(_PUBLIC) + ["code_hash", "expired_at"] if key in item})
    _write_all(expired_path(base), rows[-_MAX_EXPIRED:])
    return True


def escalate_settings(cfg):
    """不写、或 enabled 不是真布尔 true，就当关。写错 notify 时退回主人私聊，不退回群。"""
    raw = ((cfg or {}).get("write") or {}).get("escalate")
    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        return {"enabled": False, "who": ()}
    who = str(raw.get("notify") or "owner").strip().lower()
    if who not in ("owner", "initiator", "both", "none"):
        who = "owner"
    flags = []
    if who in ("owner", "both"):
        flags.append("owner")
    if who in ("initiator", "both"):
        flags.append("initiator")
    return {"enabled": True, "who": tuple(flags)}


def _private_id(value):
    """私聊对象。群号（oc_ 开头）和占位符不算，避免超时提醒发进群。"""
    text = str(value or "").strip()
    if not text or text.startswith("REPLACE_") or text.startswith("oc_"):
        return ""
    if not _ID.match(text):
        return ""
    return text


def escalate_targets(cfg, rec, plan=None):
    plan = plan or escalate_settings(cfg)
    if not plan["enabled"]:
        return []
    found = []
    if "owner" in plan["who"]:
        import usage
        for oid in usage.owner_ids(cfg):
            text = _private_id(oid)
            if text and text not in found:
                found.append(text)
    if "initiator" in plan["who"]:
        text = _private_id((rec or {}).get("user"))
        if text and text not in found:
            found.append(text)
    return found


def notice_text(rec, names, code=""):
    tool = str((rec or {}).get("tool") or "写入")[:40]
    if not _TOOL.fullmatch(tool):
        tool = "写入"
    summary = _summary(rec, names, code)
    extra = ("摘要：%s。" % summary) if summary else ""
    return ("有一条写入确认超时了，没有执行。工具：%s。%s"
            "本机状态里记为 expired。这条不含确认码，也不会发到群里。" % (tool, extra))


def doctor_line(base, names=None):
    snap = view(base, names=names)
    if not snap["readable"]:
        return "WARN", "pending", "确认队列这次没读到。没有因此判失败，也不发消息。"
    tools = [item["tool"] for item in snap["pending"][:5] if item.get("tool")]
    shown = ("（%s）" % "、".join(tools)) if tools else ""
    info = "待确认 %d%s，近期过期 %d。只读，确认码和编号不在这行里，也不发消息。" % (
        len(snap["pending"]), shown, len(snap["expired"]))
    return "OK", "pending", info


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("用法：python pending_queue.py <实例目录>\n")
        return 2
    base = argv[1]
    names = guard.load_names(os.path.join(base, "redact.txt"))
    snap = view(base, names=names)
    # 本地脚本和 MCP 用同一份白名单。code_hash 只留在状态文件里做去重，不打出来。
    sys.stdout.write(json.dumps(snap, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
