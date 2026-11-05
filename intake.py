# 接待桥。默认关。从配置里的公网 HTTPS 端点拉「合作意向」，去重后追加写进一个待审文件。
# 只进不出：不发消息、不调用模型、不读日历、不写飞书。发不发、发给谁，由人看完那个文件决定。
# 为什么是拉不是收：这台机器只有出去的长连接，没有能对公网开放的入口。
# 官网把意向攒在自己的接口上，这边定时来取——和播报探站点健康是同一个方向，钥匙也只在环境变量里。
import datetime, hashlib, json, os, re, time
import broadcast, digest, guard

_BODY_LIMIT = 4096      # 一次最多读这么多字节，与播报的 _HTTP_LIMIT 同一量级
_MAX_ITEMS = 20         # 一次最多处理几条，防止对端返一个大的就把磁盘写满
_FIELD_LIMIT = 200      # 单个短字段的上限
_NOTE_LIMIT = 600       # 需求小结的上限
_MIN_INTERVAL = 15      # 最短多少分钟拉一次，比看门狗那三分钟宽
_KEEP_IDS = 500         # 去重账本最多记多少条编号
_DEFAULT_OUT = "intake/leads.md"
# 对端的字段名各家不一样，这里只认这几组别名，认不到就当这一项没有。
_NEED = ("need", "form", "type", "service", "形式", "需求类型")
_WHEN = ("when", "time", "date", "deadline", "时间", "档期")
_NOTE = ("note", "summary", "detail", "text", "body", "简述", "需求")
_WHERE = ("page", "path", "source", "from", "url", "来源")
_ID = ("id", "key", "lead_id", "uuid", "编号")
_BAD_HEADER = re.compile(r"[\r\n\t\x00]")


def _num(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < low or number > high:
        return default
    return number


def enabled(cfg):
    raw = (cfg or {}).get("intake")
    return isinstance(raw, dict) and bool(raw.get("enabled"))


def _clean_url(value):
    """先做形状检查。内网判定留给 acp_client._public_http_url，和播报用同一把尺。"""
    text = str(value or "").strip()
    if not text or text.startswith("REPLACE_"):
        return ""
    if any(c in text for c in "\\\x00\r\n\t") or len(text) > 1024:
        return ""
    return text


def _out_file(value):
    """待审文件的位置。绝对路径、盘符、.. 一律回到默认相对路径，不猜。"""
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith("REPLACE_"):
        return _DEFAULT_OUT
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text) or ".." in text.split("/"):
        return _DEFAULT_OUT
    return text[:200]


def _out_file_asked(value):
    """主人原样写的那个路径（没写或写的是占位符时给空），只为让自检能说清被换掉了什么。"""
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith("REPLACE_") or any(c in text for c in "\x00\r\n\t"):
        return ""
    return text[:200]


def settings(cfg):
    raw = (cfg or {}).get("intake")
    if not isinstance(raw, dict):
        raw = {}
    url = _clean_url(raw.get("url"))
    timezone = str(raw.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    out_file = _out_file(raw.get("out_file"))
    return {
        "enabled": bool(raw.get("enabled")),
        "url": url,
        "url_ok": bool(url) and _url_ok(url, ()),
        "token_env": str(raw.get("token_env") or "").strip()[:64],
        "interval_min": _num(raw.get("interval_min", 30), 30, _MIN_INTERVAL, 1440),
        "timeout": _num(raw.get("timeout_sec", 8), 8, 1, 20),
        "timezone": timezone,
        "tz_ok": digest.zone(timezone) is not None,
        "out_file": out_file,
        "out_file_asked": _out_file_asked(raw.get("out_file")),
    }


def _url_ok(url, names):
    """两道，和播报一样：地址里不夹客户名或密钥，主机不是内网。"""
    import acp_client
    if guard.embeds_secret(url, names):
        return False
    return bool(acp_client._public_http_url(url))


def _state_path(base):
    return os.path.join(base or ".", "state", "intake_state.json")


def _load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(path, state):
    """先写临时文件再换过去，进程被中断也不会留下半个账本。"""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def _local(now, spec):
    tz = digest.zone(spec["timezone"]) or datetime.timezone.utc
    return digest.local_now(now, tz)


def _field(value, limit=_FIELD_LIMIT):
    """去控制字符和零宽、折成一行、按上限截断。不是字符串就当没有。"""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = re.sub(r"[\x00-\x1f\x7f\u200b-\u200d\u2060]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _pick(item, names):
    low = {}
    for key, val in item.items():
        low[str(key).strip().lower()] = val
    for key in names:
        val = low.get(key.lower())
        if val is not None and str(val).strip():
            return val
    return ""


def _lead_id(item, need, when, note):
    """有编号就用编号。没有就用内容做哈希，对端重复推送不会记两遍。"""
    raw = _pick(item, _ID)
    text = _field(raw, 80)
    if text:
        return text
    return hashlib.sha1("|".join((need, when, note)).encode("utf-8", "replace")).hexdigest()[:16]


def normalize(item, names):
    """一条对端记录 → 一条人看的意向。三项全空、或正文里夹着密钥的，丢掉并计数。"""
    if not isinstance(item, dict):
        return None
    need = _field(_pick(item, _NEED))
    when = _field(_pick(item, _WHEN))
    note = _field(_pick(item, _NOTE), _NOTE_LIMIT)
    where = _field(_pick(item, _WHERE))
    if not (need or when or note):
        return None
    joined = "\n".join(part for part in (need, when, note) if part)
    if guard.embeds_secret(joined, names):
        return None
    return {"id": _lead_id(item, need, when, note), "need": need, "when": when,
            "note": note, "where": where}


def parse_body(raw):
    """对端返 JSON 数组最好，{"leads": [...]} 也认。形状不对就整批丢掉，不猜。"""
    text = (raw or "").strip()
    if not text or len(text) > _BODY_LIMIT:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("leads") or data.get("items") or data.get("data")
    if not isinstance(data, list):
        return []
    return data[:_MAX_ITEMS]


def block(lead, moment):
    head = "## %s" % moment.strftime("%Y-%m-%d %H:%M")
    if lead.get("where"):
        head += " 来自 %s" % _field(lead["where"], 80)
    lines = [head]
    if lead.get("need"):
        lines.append("- 形式：%s" % lead["need"])
    if lead.get("when"):
        lines.append("- 时间：%s" % lead["when"])
    if lead.get("note"):
        lines.append("- 小结：%s" % lead["note"])
    return "\n".join(lines)


def render_body(leads, moment, names):
    """写进待审文件之前先打码，再拆掉历史正文里可能夹带的工具标记。"""
    parts = []
    for lead in leads:
        parts.append(guard.neutralize(guard.redact(block(lead, moment), names)))
    return "\n\n".join(parts)


def _headers(spec):
    """密钥只从环境变量来，配置文件里不出现它的值。返回（请求头，原因）：
    没写变量名时不需要头；变量空了报 no_token；带控制字符的不发——那是请求头注入。"""
    if not spec["token_env"]:
        return None, ""
    token = str(os.environ.get(spec["token_env"]) or "").strip()
    if not token:
        return None, "no_token"
    if _BAD_HEADER.search(token):
        return None, "bad_token"
    return {"authorization": "Bearer %s" % token[:256], "accept": "application/json"}, ""


def _fetch_default(url, timeout, headers):
    return broadcast._http_get(url, timeout, _BODY_LIMIT, headers=headers)


def _due(state, spec, now):
    last = state.get("last_poll")
    if isinstance(last, (int, float)) and now - float(last) < spec["interval_min"] * 60:
        return False
    return True


def tick(cfg, base, names, now=None, fetch=None, log=None):
    """到点拉一次，把没见过的新意向追加进待审文件。返回一个结论字典，调用方只记账，不发送。
    分两段拿锁：记账本用一次，写完再用一次，中间那一次网络等待不占着锁。
    那把锁只有五秒耐心，而拉一次最长能等二十秒——占着锁去等网络，另一段代码只会白撞 TimeoutError。"""
    spec = settings(cfg)
    if not spec["enabled"]:
        return {"ok": True, "reason": "disabled", "new": 0, "seen": 0, "skipped": 0}
    now = time.time() if now is None else float(now)
    out = {"ok": False, "reason": "", "new": 0, "seen": 0, "skipped": 0}
    if not spec["url_ok"]:
        out["reason"] = "no_url"
        return out
    if not spec["tz_ok"]:
        out["reason"] = "bad_timezone"
        return out
    headers, why = _headers(spec)
    if why:
        out["reason"] = why
        return out
    path = _state_path(base)
    try:
        with digest.outbound_lock(path):
            state = _load(path)
            if not _due(state, spec, now):
                out["ok"] = True
                out["reason"] = "too_soon"
                return out
            state["last_poll"] = now
            _save(path, state)
    except TimeoutError:
        out["reason"] = "busy"
        return out
    got = (fetch or _fetch_default)(spec["url"], spec["timeout"], headers) or {}
    if got.get("_error"):
        out["reason"] = str(got.get("_error"))
        return out
    try:
        status = int(got.get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    if status not in (200, 204):
        out["reason"] = "status"
        return out
    try:
        with digest.outbound_lock(path):
            state = _load(path)
            seen = {str(x) for x in (state.get("ids") or []) if x}
            fresh, skipped = [], 0
            for item in parse_body(got.get("body")):
                lead = normalize(item, names)
                if lead is None:
                    skipped += 1
                    continue
                if lead["id"] in seen:
                    continue
                seen.add(lead["id"])
                fresh.append(lead)
            out["skipped"] = skipped
            out["seen"] = len(seen)
            if fresh:
                dest = guard.safe_path(base, spec["out_file"])
                if dest is None:
                    out["reason"] = "bad_out_file"
                    return out
                _append(dest, render_body(fresh, _local(now, spec), names), log)
                state["ids"] = sorted(seen)[-_KEEP_IDS:]
                out["new"] = len(fresh)
            out["ok"] = True
            out["reason"] = "polled"
            _save(path, state)
    except TimeoutError:
        out["reason"] = "busy"
    return out


def _append(dest, body, log):
    if not body:
        return
    directory = os.path.dirname(dest)
    if directory:
        os.makedirs(directory, exist_ok=True)
    is_new = not os.path.isfile(dest)
    with open(dest, "a", encoding="utf-8", newline="\n") as handle:
        if is_new:
            handle.write("# 待看的合作意向（机器人只写这个文件，不会自己发出去）\n\n")
        handle.write(body.rstrip() + "\n")
    if log:
        log.info("intake wrote %d items", body.count("## "))


def hints(cfg, base):
    """给 --check 和启动提示看的一几句。只说会不会收、会不会写，不碰网络。"""
    spec = settings(cfg)
    if not spec["enabled"]:
        return []
    lines = []
    if not spec["url_ok"]:
        lines.append("intake 已打开，但 url 不是可连的公网 http(s) 地址（内网、带账号密码、带密钥的都算不是）。不会去拉。")
    if not spec["tz_ok"]:
        lines.append("intake.timezone 认不出来，这一版不会拉。")
    if spec["token_env"] and not str(os.environ.get(spec["token_env"]) or "").strip():
        lines.append("intake.token_env 写了 %s，但那个环境变量是空的。不带密钥去拉，对端多半会挡。" % spec["token_env"])
    if spec["out_file_asked"] and spec["out_file_asked"] != spec["out_file"]:
        lines.append("intake.out_file 写了 %s，认不出来（绝对路径、盘符或 ..），这一版按默认 %s 落。"
                     % (spec["out_file_asked"], spec["out_file"]))
    elif guard.safe_path(base, spec["out_file"]) is None:
        lines.append("intake.out_file 认不出来（绝对路径、盘符或 ..），这一版按默认 %s 落。" % _DEFAULT_OUT)
    return lines


def status_line(cfg, base):
    """给 /状态 用的一行。没打开时返回空，那一行都不加，正文和没有这项时一样。"""
    spec = settings(cfg)
    if not spec["enabled"]:
        return ""
    state = _load(_state_path(base))
    last = state.get("last_poll")
    count = len([x for x in (state.get("ids") or []) if x])
    when = _local(float(last), spec).strftime("%m-%d %H:%M") if isinstance(last, (int, float)) else "还没拉过"
    return "合作意向接待：开，只收不发。%s，攒下 %d 条在 %s。要不要发出去看你点头，这一项自己不会发。" % (
        when, count, spec["out_file"])
