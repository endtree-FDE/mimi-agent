# 接待桥的下一跳：把「官网攒下的合作意向」带到飞书里的人面前。默认关。
# 分工：intake.py 只进不出（tests/test_intake.py 从结构上钉住了它，本模块不动它）。
# 会发消息的只有这里，而且分两段：先到点给主人私聊发一条「有 N 条待看」并附一个确认码，
# 主人在同一个私聊里本人回「发意向 码」之后，才把那几条发到指定的群。不回复就什么都不发。
# 确认码位数跟着 confirm.code_digits，默认 6 位；正文发出前照例打码、拆工具标记。
import datetime, hashlib, json, os, re, time
import confirm_mode, digest, guard, intake, usage

_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_HEAD = "## "
_DEFAULT_TTL = 86400
_KEEP_HANDLED = 500
_BODY_LIMIT = 3200          # 发送接口那一层还有 3500 的硬上限，这里先留出前缀的余量
_SHOW_LINES = 3             # 提醒里最多摘几条给人看
_STATE = "intake_notify.json"


def _num(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < low or number > high:
        return default
    return number


def _ids(raw):
    """群号和人的编号都照这套规矩：认不出形状的、还是占位符的，一律丢掉。"""
    out = []
    for item in raw or []:
        text = str(item or "").strip()
        if text and not text.startswith("REPLACE_") and _ID.match(text) and text not in out:
            out.append(text)
    return out


def _block(cfg):
    raw = (cfg or {}).get("intake")
    if not isinstance(raw, dict):
        return {}
    notify = raw.get("notify")
    return notify if isinstance(notify, dict) else {}


def _bridge(cfg):
    raw = (cfg or {}).get("intake")
    return raw if isinstance(raw, dict) else {}


def enabled(cfg):
    """接待桥本体和提醒都要打开。只开提醒没有意义——那边一条意向都不会收。"""
    return bool(_bridge(cfg).get("enabled")) and bool(_block(cfg).get("enabled"))


def settings(cfg):
    raw = _block(cfg)
    timezone = str(raw.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    owners = _ids(raw.get("owner_open_ids"))
    if not owners:
        owners = [_clean_one(x) for x in usage.owner_ids(cfg)]
        owners = [x for x in owners if x]
    digits = confirm_mode.code_digits(cfg)
    return {
        "enabled": enabled(cfg),
        "owners": owners,
        "chats": _ids(raw.get("chat_ids")),
        "min_items": _num(raw.get("min_items", 1), 1, 1, 50),
        "max_per_day": _num(raw.get("max_per_day", 2), 2, 1, 10),
        "min_gap_min": _num(raw.get("min_gap_min", 60), 60, 5, 1440),
        "max_items": _num(raw.get("max_items", 5), 5, 1, 20),
        "timezone": timezone,
        "tz_ok": digest.zone(timezone) is not None,
        "ttl": _num(raw.get("confirm_ttl_sec", _DEFAULT_TTL), _DEFAULT_TTL, 60, 7 * 86400),
        "digits": digits,
        "send_rx": re.compile(r"^发意向\s*(\d{%d})$" % digits),
        "skip_rx": re.compile(r"^不发意向\s*(\d{%d})$" % digits),
        "out_file": intake.settings(cfg)["out_file"],
    }


def _clean_one(value):
    text = str(value or "").strip()
    return text if text and not text.startswith("REPLACE_") and _ID.match(text) else ""


def _state_path(base):
    return os.path.join(base or ".", "state", _STATE)


def _load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(path, state):
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


def split_blocks(text):
    """待审文件按 ## 分成一条条。第一截是文件头的说明，不是意向，丢掉。"""
    chunks = (text or "").split(_HEAD)
    return [_HEAD + chunk.strip() for chunk in chunks[1:] if chunk.strip()]


def _read_file(cfg, base):
    dest = guard.safe_path(base, intake.settings(cfg)["out_file"])
    if dest is None or not os.path.isfile(dest):
        return ""
    try:
        with open(dest, encoding="utf-8", errors="replace") as handle:
            return handle.read()[:65536]
    except OSError:
        return ""


def _block_id(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def _open_ids(state, now):
    """还没被处理、且还没过期的码覆盖的那些条目。它们已经提醒过主人一次，不该再提醒第二遍。"""
    out = set()
    for rec in (state.get("codes") or {}).values():
        if not isinstance(rec, dict) or rec.get("used"):
            continue
        if float(rec.get("expires_at") or 0) <= now:
            continue
        out.update(str(x) for x in (rec.get("items") or []))
    return out


def pending(cfg, base, now=None):
    """待审文件里还没发过、也没在提醒里等人表态的条目。返回 [(编号, 正文)]。"""
    spec = settings(cfg)
    state = _load(_state_path(base))
    handled = {str(x) for x in (state.get("handled") or [])}
    stamp = time.time() if now is None else float(now)
    held = _open_ids(state, stamp)
    out = []
    for text in split_blocks(_read_file(cfg, base)):
        bid = _block_id(text)
        if bid in handled or bid in held:
            continue
        out.append((bid, text))
    return out


def _summary(text):
    """提醒里给人看的那一行：先看小结，再看形式，都没有就用那条的抬头。"""
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    for prefix in ("- 小结：", "- 形式：", "- 时间："):
        for line in lines:
            if line.startswith(prefix):
                return guard.neutralize(guard.redact(line, ()))[:120]
    return guard.neutralize(guard.redact(lines[0], ()))[:120] if lines else ""


def _code_in(text):
    """从提醒正文里把确认码抠出来。给状态行、测试和人复述用。"""
    matched = re.search(r"发意向\s*(\d{4,8})", text or "")
    return matched.group(1) if matched else ""


def render_notice(items, total, cap, code, spec, ttl_minutes):
    lines = ["官网那边攒了 %d 条合作意向，还没人看过。共 %d 条，这次带 %d 条。" % (total, total, cap)]
    lines.append("原文都在本机的 %s，可以先翻那一份。" % spec["out_file"])
    for index, text in enumerate(items, 1):
        lines.append("%d. %s" % (index, _summary(text)))
    if total > len(items):
        lines.append("（还有 %d 条没在这条里列出）" % (total - len(items)))
    lines.append("要发到群里就回：发意向 %s" % code)
    lines.append("这批不发出去就回：不发意向 %s" % code)
    lines.append("不回复就什么都不发。%d 分钟内有效，用一次作废。" % ttl_minutes)
    return "\n".join(lines)


def _body(items, names):
    """确认后发进群的那一段。已经落盘打码过一次，这里再打一遍并拆工具标记。"""
    joined = "\n\n".join(items)
    joined = guard.neutralize(guard.redact(joined, names))
    if len(joined) > _BODY_LIMIT:
        joined = joined[:_BODY_LIMIT].rstrip() + "\n（还有内容没有放进这条）"
    return joined


def _gc_codes(codes, now):
    kept = {}
    for code, rec in (codes or {}).items():
        if not isinstance(rec, dict):
            continue
        try:
            expires = float(rec.get("expires_at") or 0)
        except (TypeError, ValueError):
            continue
        if now > expires + 86400:
            continue
        kept[code] = rec
    return kept


def _new_code(codes, digits):
    import random
    for _ in range(12):
        code = "%0*d" % (digits, random.SystemRandom().randint(0, 10 ** digits - 1))
        if code not in codes:
            return code
    return ""


def _record():
    return {"codes": {}, "handled": [], "day": "", "notices": 0, "last": 0}


def _send_owner(sender, spec, text, now):
    """私聊发给每一位主人。幂等键不带群号和编号原样，只带这一批的指纹。"""
    results = []
    stamp = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12]
    for owner in spec["owners"]:
        key = "n" + hashlib.sha256(("%s|%s|%d" % (owner, stamp, int(now))).encode("utf-8")).hexdigest()[:20]
        try:
            results.append(sender("user", owner, text, key))
        except Exception:
            results.append("fail")
    return results


def tick(cfg, base, names, now=None, sender=None, served=None, log=None):
    """到点看一眼待审文件。够条件就给主人发一条待看提醒，确认之前一条群消息都不发。"""
    spec = settings(cfg)
    out = {"ok": False, "reason": "", "new": 0, "sent": 0}
    if not spec["enabled"]:
        return dict(out, ok=True, reason="disabled")
    if sender is None or not spec["owners"]:
        return dict(out, ok=True, reason="no_owner")
    if not spec["chats"]:
        return dict(out, ok=True, reason="no_chat")
    if not spec["tz_ok"]:
        return dict(out, reason="bad_timezone")
    now = time.time() if now is None else float(now)
    moment = _local(now, spec)
    path = _state_path(base)
    try:
        with digest.outbound_lock(path):
            state = _record()
            state.update(_load(path))
            if not _due(state, spec, now, moment):
                return dict(_reason(state, spec, now, moment), **{"ok": True, "sent": 0})
            items = pending(cfg, base, now)
            if not items:
                return {"ok": True, "reason": "nothing_new", "new": 0, "sent": 0}
            total = len(items)
            if total < spec["min_items"]:
                return {"ok": True, "reason": "below_min", "new": total, "sent": 0}
            picked = items[:spec["max_items"]]
            codes = _gc_codes(state.get("codes") or {}, now)
            code = _new_code(codes, spec["digits"])
            if not code:
                return {"reason": "no_code", "new": 0, "sent": 0}
            text = render_notice([x[1] for x in picked], total, len(picked), code, spec,
                                 max(1, int(spec["ttl"] / 60)))
            text = guard.neutralize(guard.redact(text, names))
            results = _send_owner(sender, spec, text, now)
            if "ok" not in results and "unknown" not in results:
                return {"reason": "send_failed", "new": total, "sent": 0}
            codes[code] = {"code": code, "items": [x[0] for x in picked], "owners": spec["owners"],
                           "chats": spec["chats"], "created": now, "expires_at": now + spec["ttl"],
                           "used": False}
            day = moment.strftime("%Y-%m-%d")
            notice_state = state.get("notices")
            count = notice_state if isinstance(notice_state, int) else 0
            if str(state.get("day") or "") != day:
                count = 0
            state.update({"codes": codes, "day": day, "notices": count + 1, "last": now})
            _save(path, state)
            if log:
                log.info("intake_notify noticed %d leads to %d owners", total, len(spec["owners"]))
            return {"ok": True, "reason": "notified", "new": total, "sent": len(results)}
    except TimeoutError:
        return {"reason": "busy", "new": 0, "sent": 0}


def _due(state, spec, now, moment):
    last = state.get("last")
    if isinstance(last, (int, float)) and now - float(last) < spec["min_gap_min"] * 60:
        return False
    day = moment.strftime("%Y-%m-%d")
    if str(state.get("day") or "") == day:
        notice_state = state.get("notices")
        count = notice_state if isinstance(notice_state, int) else 0
        if count >= spec["max_per_day"]:
            return False
    return True


def _reason(state, spec, now, moment):
    """没到时间还是当天已经提醒够了，两种都别发，但说清是哪一种。"""
    last = state.get("last")
    if isinstance(last, (int, float)) and now - float(last) < spec["min_gap_min"] * 60:
        return {"reason": "too_soon", "new": 0}
    return {"reason": "day_limit", "new": 0}


def is_command(cfg, text):
    if not enabled(cfg):
        return False
    q = (text or "").strip()
    spec = settings(cfg)
    return bool(spec["send_rx"].match(q) or spec["skip_rx"].match(q))


def _decide(state, code, ctx, spec, now):
    """返回（记录, 说给人听的话）。话不为空时就是不发，调用方照原样回。"""
    codes = _gc_codes(state.get("codes") or {}, now)
    rec = codes.get(str(code or ""))
    if not rec:
        return None, "确认码不对或已过期，没发。"
    if rec.get("used"):
        return None, "这条已经处理过了，没有重发。"
    if float(rec.get("expires_at") or 0) <= now:
        return None, "确认码已过期，没发。"
    user = str((ctx or {}).get("user") or "")
    if user not in (rec.get("owners") or []):
        return None, "只有主人本人在私聊里回复才作数。没发。"
    if (ctx or {}).get("chat_type") != "p2p":
        return None, "请在私聊里本人回复，群里回复不作数。没发。"
    return rec, ""


def handle_text(cfg, base, text, ctx, names, sender=None, served=None, now=None):
    """是本模块的确认命令就回一句话，否则返回 None 交给原来的处理。"""
    if not enabled(cfg):
        return None
    q = (text or "").strip()
    spec = settings(cfg)
    matched = spec["send_rx"].match(q)
    skip = False
    if not matched:
        matched = spec["skip_rx"].match(q)
        skip = True
    if not matched:
        return None
    code = matched.group(1)
    now = time.time() if now is None else float(now)
    path = _state_path(base)
    try:
        with digest.outbound_lock(path):
            state = _record()
            state.update(_load(path))
            rec, why = _decide(state, code, ctx, spec, now)
            if why:
                return why
            rec["used"] = True
            handled = [str(x) for x in (state.get("handled") or [])]
            texts = _blocks_by_id(cfg, base, rec.get("items") or [])
            sent_chats = 0
            if not skip:
                targets = [c for c in (rec.get("chats") or []) if _served_ok(c, served)]
                if not targets:
                    # 这批意向还留在待看里（不进 handled），但这个码说作废就得真作废：
                    # 落盘 used，否则换个群再回同一个码还是能发出去。
                    state.update({"codes": _gc_codes(state.get("codes") or {}, now)})
                    _save(path, state)
                    return "那个群不在本实例的服务范围内，没发。确认码已作废。"
                body = _body(texts, names)
                stamp = hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]
                for chat in targets:
                    key = "l" + hashlib.sha256(("%s|%s|%s" % (chat, stamp, "lead")).encode("utf-8")).hexdigest()[:20]
                    try:
                        result = sender("chat", chat, body, key)
                    except Exception:
                        result = "fail"
                    if result in ("ok", "unknown"):
                        sent_chats += 1
            if skip or sent_chats:
                for bid in (rec.get("items") or []):
                    if bid not in handled:
                        handled.append(bid)
            state.update({"codes": _gc_codes(state.get("codes") or {}, now),
                          "handled": handled[-_KEEP_HANDLED:]})
            _save(path, state)
    except TimeoutError:
        return "这一条正被另一个动作占用，稍后再回一次。没发。"
    if skip:
        return "%d 条已记账，没发。" % len(texts)
    if sent_chats == 0:
        return "一条都没发出去（发送接口没认这笔），这批还留在待看里，下一轮会换个码再提醒。"
    return "已发到 %d 个群，这批 %d 条算处理过了。" % (sent_chats, len(texts))


def _blocks_by_id(cfg, base, ids):
    wanted = set(str(x) for x in (ids or []))
    out = []
    for text in split_blocks(_read_file(cfg, base)):
        if _block_id(text) in wanted:
            out.append(text)
    return out


def _served_ok(chat, served):
    if served is None:
        return True
    return str(chat or "") in {str(x) for x in served}


def hints(cfg, base):
    spec = settings(cfg)
    if not _block(cfg).get("enabled"):
        return []
    lines = []
    if not spec["enabled"]:
        lines.append("intake_notify 已打开，但接待桥本体（intake.enabled）是关的。没有意向可提醒。")
        return lines
    if not spec["owners"]:
        lines.append("intake_notify 已打开，但没有可用的主人编号。不会有人收到待看提醒。")
    if not spec["chats"]:
        lines.append("intake_notify.chat_ids 是空的。就算本人回了确认码也没有群可发。")
    if not spec["tz_ok"]:
        lines.append("intake_notify.timezone 认不出来，提醒不会发。")
    if guard.safe_path(base, spec["out_file"]) is None:
        lines.append("intake_notify 认不出待审文件的位置（绝对路径、盘符或 ..）。不会提醒。")
    return lines


def status_line(cfg, base):
    spec = settings(cfg)
    if not spec["enabled"]:
        return ""
    state = _load(_state_path(base))
    handled = len([x for x in (state.get("handled") or []) if x])
    return ("合作意向提醒：开，只私聊提醒主人，本人回确认码之前不发群。"
            "现在有 %d 条等你确认（今天最多提醒 %d 次），处理过 %d 条，不回复就不发。") % (
        len(pending(cfg, base)), spec["max_per_day"], handled)
