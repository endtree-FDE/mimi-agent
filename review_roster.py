# 双人复核值班表。默认关。
# 只回答「这一时刻谁可以当第二位」，不决定要不要双人复核，也不代替写入白名单。
# 未启用时 on_duty_ids 返回 None，tools.review 完全不看这里，行为和从前一样。
import datetime


def block(cfg):
    raw = ((cfg or {}).get("write") or {}).get("review_roster")
    return raw if isinstance(raw, dict) else {}


def active(cfg):
    # 只有 JSON true 才启用。写成 "true" 或 1 都当没开，避免笔误把复核收窄。
    return block(cfg).get("enabled") is True


def _offset_hours(raw):
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    if raw < -12 or raw > 14:
        return None
    return raw


def offset_ok(cfg):
    raw = block(cfg)
    if "utc_offset_hours" not in raw or raw.get("utc_offset_hours") in (None, ""):
        return True
    return _offset_hours(raw.get("utc_offset_hours")) is not None


def resolve_now(cfg, now=None):
    if now is not None:
        return now
    raw = block(cfg)
    if "utc_offset_hours" not in raw or raw.get("utc_offset_hours") in (None, ""):
        return datetime.datetime.now()
    hours = _offset_hours(raw.get("utc_offset_hours"))
    tz = datetime.timezone(datetime.timedelta(hours=hours))
    return datetime.datetime.now(tz)


def _minutes(text, allow_24=False):
    if not isinstance(text, str):
        return None
    parts = text.strip().split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if allow_24 and hour == 24 and minute == 0:
        return 24 * 60
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _weekdays(raw):
    if not isinstance(raw, list):
        return set()
    days = set()
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        if 1 <= item <= 7:
            days.add(item)
    return days


def _open_ids(raw):
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            out.append(text)
    return out


def _matches(slot, when):
    if not isinstance(slot, dict):
        return False
    days = _weekdays(slot.get("weekdays"))
    start = _minutes(slot.get("start"))
    end = _minutes(slot.get("end"), allow_24=True)
    if not days or start is None or end is None or start == end or not _open_ids(slot.get("open_ids")):
        return False
    weekday = when.isoweekday()
    minute = when.hour * 60 + when.minute
    if start < end:
        return weekday in days and start <= minute < end
    # 跨午夜：早晨算前一天的班次。只写了周一的 18:00–09:00，盖住周一晚上，盖不住周一早晨。
    if minute >= start and weekday in days:
        return True
    prev = 7 if weekday == 1 else weekday - 1
    return minute < end and prev in days


def on_duty_ids(cfg, now=None):
    """None 表示没启用。set 是当前班次上的编号，可能为空（启用了但对不上，或时区写错）。"""
    if not active(cfg):
        return None
    if not offset_ok(cfg):
        return set()
    when = resolve_now(cfg, now)
    slots = block(cfg).get("slots")
    if not isinstance(slots, list):
        return set()
    found = set()
    for slot in slots:
        if _matches(slot, when):
            found.update(_open_ids(slot.get("open_ids")))
    return found


def eligible_ids(cfg, allowed, now=None):
    """None 表示没启用。列表是「在班次上且在写入白名单里」的编号，按班次顺序，不重复。"""
    duty = on_duty_ids(cfg, now)
    if duty is None:
        return None
    allowed = allowed if isinstance(allowed, dict) else {}
    slots = block(cfg).get("slots")
    ordered, seen = [], set()
    if isinstance(slots, list):
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            for uid in _open_ids(slot.get("open_ids")):
                if uid in duty and uid in allowed and uid not in seen:
                    seen.add(uid)
                    ordered.append(uid)
    return ordered


def eligible_names(cfg, allowed, now=None):
    """给回复用的称呼。None 表示没启用。不返回编号。"""
    ids = eligible_ids(cfg, allowed, now)
    if ids is None:
        return None
    allowed = allowed if isinstance(allowed, dict) else {}
    names, seen = [], set()
    for uid in ids:
        name = str(allowed.get(uid) or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names
