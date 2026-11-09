# 只读诊断。不启动 event consume，不发消息，不写心跳。
# 外部命令、进程列表、域名解析都由调用方传入，测试不必连真的飞书。
import base64, csv, io, json, os, re, socket, subprocess, time
import confirm_mode, guard, lifecycle, pending_queue, proc_identity

_SCOPE_RX = re.compile(r"\b[a-z][a-z0-9_.]*(?::[a-z0-9_.]+){1,8}\b")
_SECRET_KEY = re.compile(r"^(app_secret|api_key|api_secret|password|passwd)$", re.I)
_FAKE_SECOND = {18, 19}


def secret_keys(obj, prefix=""):
    """只返回键名。不返回值，避免把密钥打进诊断输出。"""
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            name = str(key)
            path = prefix + name
            if _SECRET_KEY.match(name):
                found.append(path)
            else:
                found.extend(secret_keys(value, path + "."))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(secret_keys(item, prefix))
    return found


def _enabled(cfg, name):
    spec = (cfg.get("tools") or {}).get(name)
    if isinstance(spec, dict) and "enabled" in spec:
        return bool(spec.get("enabled"))
    if name in ("calendar_create_batch", "calendar_update", "calendar_delete") and name not in (cfg.get("tools") or {}):
        return bool(((cfg.get("tools") or {}).get("calendar_create") or {}).get("enabled"))
    return False


def required_scopes(cfg):
    """按已经启用的能力列出必须有的 scope。没开的工具不因此失败。"""
    cfg = cfg or {}
    need = ["im:message.group_at_msg:readonly", "im:message:send_as_bot"]
    feat = cfg.get("features") or {}
    if feat.get("p2p"):
        need.append("im:message.p2p_msg:readonly")
    if _enabled(cfg, "history"):
        need.extend(["im:message:readonly", "im:message.group_msg"])
    if feat.get("attachments", True):
        need.extend(["im:message:readonly", "im:resource"])
    progress = cfg.get("progress")
    if progress is None or (isinstance(progress, dict) and progress.get("enabled", True)):
        need.extend(["im:message.reactions:write_only", "im:message:update", "cardkit:card:write"])
    if _enabled(cfg, "docs_read"):
        need.append("docx:document:readonly")
    if _enabled(cfg, "docs_search"):
        need.append("search:docs:read")
    if _enabled(cfg, "docs_create"):
        need.append("docx:document:create")
    if _enabled(cfg, "docs_append"):
        need.append("docx:document:write_only")
    if _enabled(cfg, "calendar_read"):
        need.append("calendar:calendar.event:read")
    if _enabled(cfg, "calendar_create") or _enabled(cfg, "calendar_create_batch"):
        need.append("calendar:calendar.event:create")
    if _enabled(cfg, "calendar_update"):
        need.append("calendar:calendar.event:update")
    if _enabled(cfg, "calendar_delete"):
        need.append("calendar:calendar.event:delete")
    if _enabled(cfg, "base_read"):
        need.append("base:record:read")
    if _enabled(cfg, "base_create"):
        need.append("base:record:create")
    chats = cfg.get("chats") or {}
    if chats.get("auto_join") and not (cfg.get("chat_ids") or []):
        need.extend(["im:chat:read", "im:chat.members:read"])
    p2p = cfg.get("p2p") or {}
    if isinstance(p2p, dict) and p2p.get("allow_group_members"):
        need.append("im:chat.members:read")
    # 早晨摘要自己去读日历和任务表。工具开关没开时，这两项权限仍要有，否则摘要读不到。
    digest_cfg = cfg.get("digest") if isinstance(cfg.get("digest"), dict) else {}
    if digest_cfg.get("enabled"):
        import digest as digest_mod
        if digest_mod.settings(cfg).get("include_calendar") and digest_mod.calendar_id(cfg):
            need.append("calendar:calendar.event:read")
        if digest_mod.settings(cfg).get("include_tasks") and digest_mod.task_table(cfg):
            need.append("base:record:read")
    kcfg = cfg.get("knowledge") if isinstance(cfg.get("knowledge"), dict) else {}
    if kcfg.get("enabled"):
        import knowledge as knowledge_mod
        for item in knowledge_mod.scopes_for(cfg):
            need.append(item)
    out = []
    for item in need:
        if item not in out:
            out.append(item)
    return out


def required_events(cfg):
    events = ["im.message.receive_v1"]
    chats = (cfg or {}).get("chats") or {}
    if chats.get("auto_join") and not ((cfg or {}).get("chat_ids") or []):
        events.extend(["im.chat.member.bot.added_v1", "im.chat.member.bot.deleted_v1"])
    if confirm_mode.wants_card_process(cfg):
        events.append(confirm_mode.CARD_EVENT)
    return events


def expected_running_events(cfg, card_state):
    """真正应该在跑的 event consume。卡片没开通或还没连上过时，不把 card.action.trigger 算进去。"""
    events = ["im.message.receive_v1"]
    chats = (cfg or {}).get("chats") or {}
    if chats.get("auto_join") and not ((cfg or {}).get("chat_ids") or []):
        events.extend(["im.chat.member.bot.added_v1", "im.chat.member.bot.deleted_v1"])
    mode = confirm_mode.card_callback_setting(cfg)
    if mode == "on" or (mode != "off" and confirm_mode.wants_cards(cfg) and card_state is True):
        if confirm_mode.wants_cards(cfg) and confirm_mode.CARD_EVENT not in events:
            events.append(confirm_mode.CARD_EVENT)
    return events


def _consume_events(procs, profile):
    found = {}
    for proc in procs or []:
        cmd = proc.get("cmdline") or ""
        low = cmd.lower()
        if "lark-cli" not in low or not re.search(r"(?:^|\s)event\s+consume(?:\s|$)", low):
            continue
        if profile and profile not in cmd:
            continue
        match = re.search(r"event\s+consume\s+(\S+)", cmd, re.I)
        key = match.group(1) if match else "?"
        found[key] = found.get(key, 0) + 1
    return found


def judge_running_consumes(procs, base, profile, cfg, env=None):
    """接收进程数量。后台没订阅卡片回调时，缺少 card.action.trigger 不算少，也不算断线。"""
    if procs is None:
        return []
    state = confirm_mode.card_note_state(base, env)
    expected = expected_running_events(cfg, state)
    found = _consume_events(procs, profile)
    got = [name for name in expected if found.get(name)]
    missing = [name for name in expected if not found.get(name)]
    mode = confirm_mode.card_callback_setting(cfg)
    wants = confirm_mode.wants_cards(cfg)
    level = "OK"
    info = "预期 %d 个，看到 %d 个" % (len(expected), len(got))
    if mode == "off":
        info += "。card_callback=off，不把卡片进程算进去，确认用确认码"
    elif wants and confirm_mode.CARD_EVENT not in expected:
        info += "。不含 card.action.trigger：没开通时不把它算进接收进程数量，这不算断线，确认已改用确认码"
    if state is False and found.get(confirm_mode.CARD_EVENT):
        level = "WARN"
        info += "。本机记录是没开通，进程表里却还有卡片接收进程。这一版不会再反复拉起它"
    if missing and sum(found.values()):
        level = "WARN"
        info += "。还缺 " + ", ".join(missing)
    return [(level, info)]


def scopes_in(text):
    return list(dict.fromkeys(_SCOPE_RX.findall(text or "")))


def is_fake_ip(ip):
    parts = str(ip or "").split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    return nums[0] == 198 and nums[1] in _FAKE_SECOND


def proxy_covers_feishu(no_proxy):
    text = (no_proxy or "").lower()
    return "feishu.cn" in text or "larksuite.com" in text


def logged_in(code, text):
    if code != 0:
        return False
    low = (text or "").lower()
    bad = ("not login", "not logged", "unauthorized", "please login", "no token", "未登录", "请登录")
    return not any(item in low for item in bad)


def usage_error(code, text):
    """退出码 2，或文本写明不认识这个参数。这是命令写法问题，不是飞书拒绝。"""
    if code == 2:
        return True
    if code == 0:
        return False
    low = (text or "").lower()
    marks = ("unknown flag", "unknown command", "unknown shorthand", "required flag",
             "invalid argument", "flag provided but not defined", "参数错误", "accepts ")
    return any(item in low for item in marks)


def _json_obj(text):
    raw = text or ""
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(raw[start:end + 1])
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def bot_ready(text):
    """True 应用身份就绪，False 明确没有，None 这一版输出里看不出来。"""
    obj = _json_obj(text)
    if not isinstance(obj, dict):
        return None
    identities = obj.get("identities")
    if isinstance(identities, dict) and isinstance(identities.get("bot"), dict):
        bot = identities["bot"]
        if "available" in bot:
            return bool(bot.get("available"))
        return str(bot.get("status") or "") == "ready"
    if obj.get("identity") == "bot":
        return True
    return None


# lark-cli 1.0.98 的 auth scopes 不接受 --as bot（带上退出码 2）。
# 官方实现（cmd/auth/scopes.go + getAppInfo）：开放平台若按身份标了 token_types，
# JSON 固定是 tokenType=user 和 userScopes，里面只有用户 token 的 scope。
# 实机登录后常见 userScopes 只有 offline_access，机器人实际用的 tenant 权限不在这份列表里。
# 接口没按身份分类时字段才是 scopes，那一份才是应用权限。这一版没有别的命令能列出 tenant 权限。
_PLAIN_SCOPE_KEYS = ("scopes", "enabledScopes", "enabled_scopes", "scopeList", "scope_list")
_EXPLICIT_APP_KEYS = ("appScopes", "app_scopes", "tenantScopes", "tenant_scopes", "botScopes", "bot_scopes")
_USER_SCOPE_KEYS = ("userScopes", "user_scopes")
_USER_TOKEN_TYPES = {"user", "uat", "user_access_token"}
_APP_TOKEN_TYPES = {"tenant", "bot", "app", "tat", "tenant_access_token", "application"}
_SCOPE_NESTS = ("data", "result", "app", "appInfo", "application")


def _scope_items(value):
    """列表就返回名字（可以是空列表）。不是列表则返回 None。"""
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if ":" not in raw and "," not in raw:
            return None
        value = [part for part in re.split(r"[\s,]+", raw) if part]
    if not isinstance(value, list):
        return None
    out = []
    for item in value:
        if isinstance(item, dict):
            name = item.get("scope") or item.get("name") or item.get("id") or item.get("key") or ""
            name = str(name).strip()
        else:
            name = str(item).strip().strip(",|")
        if name:
            out.append(name)
    return out


def _find_named(obj, keys, depth=0):
    if not isinstance(obj, dict) or depth > 3:
        return None
    for key in keys:
        found = _scope_items(obj.get(key))
        if found is not None:
            return found
    for key in _SCOPE_NESTS:
        found = _find_named(obj.get(key), keys, depth + 1)
        if found is not None:
            return found
    return None


def _token_type(obj, depth=0):
    if not isinstance(obj, dict) or depth > 3:
        return ""
    for key in ("tokenType", "token_type"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    for key in _SCOPE_NESTS:
        found = _token_type(obj.get(key), depth + 1)
        if found:
            return found
    return ""


def classify_scopes(text):
    """返回 ('app', 列表)、('user', 列表) 或 (None, None)。

    app 才能拿去和已启用能力比对。user 是用户 token，不能当成应用权限。
    """
    obj = _json_obj(text)
    if isinstance(obj, dict):
        token = _token_type(obj)
        explicit = _find_named(obj, _EXPLICIT_APP_KEYS)
        plain = _find_named(obj, _PLAIN_SCOPE_KEYS)
        user = _find_named(obj, _USER_SCOPE_KEYS)
        if token in _APP_TOKEN_TYPES:
            for found in (explicit, plain, user):
                if found is not None:
                    return "app", found
        if explicit is not None and token not in _USER_TOKEN_TYPES:
            return "app", explicit
        if token in _USER_TOKEN_TYPES or (explicit is None and plain is None and user is not None):
            return "user", user if user is not None else []
        if plain is not None:
            return "app", plain
        if explicit is not None:
            return "app", explicit
        # 已经是 JSON 就不要再按行去抠权限名，否则用户 token 里的 scope 会被当成应用权限。
        return None, None
    found = scopes_from_text(text)
    if found is not None:
        return "app", found
    return None, None


def scopes_from_text(text):
    """pretty 的圆点列表，或 SCOPE / 权限 这种文本表格。一行一个权限名。"""
    found = []
    for line in (text or "").splitlines():
        body = line.strip()
        if not body or set(body) <= set("-|=:+ "):
            continue
        while body and body[0] in "•·*-|>":
            body = body[1:].strip()
        low = body.lower()
        if low.startswith(("scope", "enabled scopes", "status", "querying", "app id", "权限", "名称")):
            continue
        token = body.split()[0].strip(",|") if body.split() else ""
        if _SCOPE_RX.fullmatch(token):
            found.append(token)
    if found:
        return list(dict.fromkeys(found))
    if re.search(r"Enabled scopes\s*\(\s*0\s*\)", text or "", re.I):
        return []
    return None


def app_scopes(text):
    """应用或 tenant 权限。用户 token（tokenType=user / 只有 userScopes）返回 None。"""
    kind, found = classify_scopes(text)
    if kind == "app":
        return found
    return None


def duplicate_findings(procs, base, profile):
    """只描述重复，不结束任何进程。--doctor / --check / --dry-run 不算正在服务的机器人。"""
    lines = []
    base_norm = (base or "").replace("/", "\\").rstrip("\\").lower()
    serving = []
    consumes = []
    for proc in procs or []:
        cmd = proc.get("cmdline") or ""
        low = cmd.lower()
        if "agentbot.py" in low and not any(flag in low for flag in ("--doctor", "--check", "--dry-run", "--lock-test")):
            if not base_norm or base_norm in low.replace("/", "\\"):
                serving.append(proc)
        if "lark-cli" in low and re.search(r"(?:^|\s)event\s+consume(?:\s|$)", low):
            if profile and profile in cmd:
                consumes.append(proc)
    if len(serving) > 1:
        lines.append(("FAIL", "duplicate agentbot count=%d" % len(serving)))
    by_event = {}
    for proc in consumes:
        found = re.search(r"event\s+consume\s+(\S+)", proc.get("cmdline") or "", re.I)
        key = found.group(1) if found else "?"
        by_event.setdefault(key, []).append(proc)
    for key, group in by_event.items():
        if len(group) > 1:
            lines.append(("FAIL", "duplicate event consume %s count=%d" % (key, len(group))))
    if not lines:
        lines.append(("OK", "serving=%d consume=%d" % (len(serving), len(consumes))))
    return lines


def _line(level, name, info=""):
    return ("%s %s %s" % (level.ljust(4), name, info)).rstrip()


def _pos_int(raw, default, lo, hi):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return min(max(n, lo), hi)


def restart_setting(cfg):
    """(窗口秒数, 几次算多)。没写用 6 小时和 3 次；写 0 或负数表示这条不提醒。"""
    alerts = (cfg or {}).get("alerts")
    alerts = alerts if isinstance(alerts, dict) else {}
    window = _pos_int(alerts.get("restart_window_sec"), 21600, 1, 7 * 86400)
    after = alerts.get("restart_warn_after")
    if after is None:
        after = 3
    else:
        after = _pos_int(after, 3, 0, 1000)
    return window, after


def restart_ledger(path, now, window_sec, warn_after):
    """数一数最近这段时间 consumer 退了几次。

    退避会在连上之后把连续失败清零，所以「每次都自愈」＝永远看不见。这里改看累计：
    只读 logs/events.jsonl 里 kind=consumer 的行，按 cause 分开数，不改任何重启行为。
    ts 认不出来或没有 ts 的行不计数。只看当前文件；刚轮转过的 .1 里可能还压着几条，
    宁可少报也不假装数全了。"""
    if not os.path.isfile(path):
        return ("OK", "没有 events.jsonl，还没有 consumer 退出记录")
    total = 0
    causes = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict) or row.get("kind") != "consumer":
                    continue
                stamp = _stamp_epoch(row.get("ts"))
                if stamp is None:
                    continue
                if now - stamp > window_sec or stamp - now > 60:
                    continue
                total += 1
                cause = str(row.get("cause") or "unknown")[:24]
                causes[cause] = causes.get(cause, 0) + 1
    except OSError as exc:
        return ("WARN", "events.jsonl 读不到：%s" % exc)
    if window_sec >= 3600:
        span = "%d 小时" % (window_sec // 3600)
    elif window_sec >= 60:
        span = "%d 分钟" % (window_sec // 60)
    else:
        span = "%d 秒" % window_sec
    brief = "、".join("%s %d" % (cause, causes[cause]) for cause in sorted(causes, key=lambda k: -causes[k]))
    if not total:
        return ("OK", "近 %s 没有 consumer 退出" % span)
    if warn_after and total >= warn_after:
        return ("WARN", "近 %s consumer 退出 %d 次：%s。每次都自愈重连，所以断线提醒看不出来；"
                        "具体原因看 logs/events.jsonl 里 kind=consumer 的行（stderr 尾部已打码截断）"
                        % (span, total, brief))
    return ("OK", "近 %s consumer 退出 %d 次：%s" % (span, total, brief))


def _stamp_epoch(text):
    """events.jsonl 的 ts 是 observe 写的本地时间字符串。解析不了返回 None。"""
    if not text:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return time.mktime(time.strptime(str(text)[:19], fmt))
        except (TypeError, ValueError):
            continue
    return None


# 起停和最近一次成败都只读已经有的文件：state/bot.lock、state/heartbeat、
# state/shutdown.request、logs/events.jsonl、logs/journal.jsonl、logs/bot.log。
# 不新写状态文件，也不为了探活去连飞书。刚轮转走的 .1 不追，宁可少报。
_SKIP_SERVICE = ("--doctor", "--check", "--dry-run", "--lock-test")
_LOG_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})(?:[,.]\d+)?\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(.*)$")
_FRAME = re.compile(r"^File \".+\", line \d+")
_UNIX_HOME = re.compile(r"(?:/home/|/Users/|/root/)[^\s\"']+")
_OPEN_ID = re.compile(r"\b(?:ou|oc|om|on)_[A-Za-z0-9]{8,}\b")
_CODE_TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,40}")
_TOOL_TOKEN = re.compile(r"[A-Za-z0-9_]{1,40}")
_FIRST_BEAT = 90


def _clock(stamp):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(stamp)))
    except (OverflowError, OSError, ValueError, TypeError):
        return ""


def _ago(now, stamp):
    try:
        delta = int(float(now) - float(stamp))
    except (TypeError, ValueError):
        return ""
    if delta < 0:
        delta = 0
    if delta < 60:
        return "%d 秒前" % delta
    if delta < 3600:
        return "%d 分钟前" % (delta // 60)
    if delta < 86400:
        return "%d 小时前" % (delta // 3600)
    return "%d 天前" % (delta // 86400)


def _unhealthy_after(cfg):
    """和部署核对同一条线：没写、写 0 或写错都是 180 秒。这里只用来措辞，不因此判失败。"""
    alerts = (cfg or {}).get("alerts")
    alerts = alerts if isinstance(alerts, dict) else {}
    try:
        n = float(alerts.get("unhealthy_after_sec"))
    except (TypeError, ValueError):
        return 180.0
    if n <= 0:
        return 180.0
    return min(n, 86400.0)


def _serving_here(procs, base):
    """本目录正在服务的 agentbot。诊断、自检、演练不算。进程表没拿到时返回 None。"""
    if procs is None:
        return None
    base_norm = (base or "").replace("/", "\\").rstrip("\\").lower()
    found = []
    for proc in procs:
        cmd = proc.get("cmdline") or ""
        low = cmd.lower().replace("/", "\\")
        if "agentbot.py" not in low or any(flag in low for flag in _SKIP_SERVICE):
            continue
        if base_norm and base_norm not in low:
            continue
        found.append(proc)
    return found


def _read_lock(base):
    """返回 (lock 或 None, 锁文件修改时间或 None, 坏了没有)。坏文件和读不到分开说。"""
    path = os.path.join(base or "", "state", "bot.lock")
    if not os.path.isfile(path):
        return None, None, False
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
        started = os.path.getmtime(path)
    except OSError:
        return None, None, True
    lock = proc_identity.parse_lock(text)
    if not lock:
        return None, started, True
    return lock, started, False


def _heartbeat_ts(base):
    """返回 (epoch 或 None, 文件在但不是时间戳)。没有文件是 (None, False)。"""
    path = os.path.join(base or "", "state", "heartbeat")
    if not os.path.isfile(path):
        return None, False
    try:
        return int(open(path, encoding="utf-8").read().strip()), False
    except (OSError, ValueError):
        return None, True


def _beat_clause(hb, hb_bad, lock_mtime, now, after):
    if hb_bad:
        return "WARN", "state/heartbeat 不是时间戳。"
    if hb is None:
        age = None if lock_mtime is None else now - lock_mtime
        if age is not None and 0 <= age <= _FIRST_BEAT:
            return "OK", "还没有心跳（刚启动时正常）。"
        return "WARN", "还没有 state/heartbeat。"
    age = now - hb
    if age < 0:
        age = 0
    if age < after:
        return "OK", "心跳 %s（%s）。" % (_clock(hb), _ago(now, hb))
    return "WARN", "心跳 %s，已经 %s 没更新（告警线 %d 秒）。" % (_clock(hb), _ago(now, hb), int(after))


def service_status(base, procs, now, cfg=None):
    """在跑、正在停，还是已经停。只读锁、停机请求、心跳和调用方给的进程表。

    不结束进程。「没在跑」也不判失败：诊断经常在启动前跑。归属和 duplicate_findings
    一样，看命令行里有没有本目录，避免另写一套。
    """
    now = float(now)
    serving = _serving_here(procs, base)
    lock, lock_mtime, lock_bad = _read_lock(base)
    stopping = os.path.isfile(lifecycle.request_path(os.path.join(base or "", "state")))
    hb, hb_bad = _heartbeat_ts(base)
    after = _unhealthy_after(cfg)
    if serving is None:
        if lock:
            return "WARN", "列不出进程。state/bot.lock 写着 pid %s，看不出是在跑还是已停。" % lock["pid"]
        if lock_bad:
            return "WARN", "列不出进程。state/bot.lock 读不到或不是以进程号开头。"
        return "WARN", "列不出进程，也没有 state/bot.lock，看不出是在跑还是已停。"
    if lock_bad and not serving:
        return "WARN", "已停止。state/bot.lock 读不到或不是以进程号开头。"
    if not serving:
        if lock and stopping:
            return ("WARN", "已停止。锁里的 pid %s 已经不在，还留着停机请求。"
                            "启动时会当成过期锁接管，不会结束别的进程。" % lock["pid"])
        if lock:
            extra = ""
            if hb is not None:
                extra = "上次心跳 %s（%s）。" % (_clock(hb), _ago(now, hb))
            return ("WARN", "已停止。锁里的 pid %s 已经不在，启动时会当成过期锁接管，不会结束别的进程。%s"
                    % (lock["pid"], extra))
        if stopping:
            return "WARN", "已停止。还留着停机请求，进程已经不在。"
        if hb is not None:
            extra = "上次心跳 %s（%s）。" % (_clock(hb), _ago(now, hb))
        elif hb_bad:
            return "WARN", "已停止。没有 state/bot.lock，进程表里也没有本目录的服务进程。state/heartbeat 不是时间戳。"
        else:
            extra = "没有 state/heartbeat。"
        return "OK", "已停止。没有 state/bot.lock，进程表里也没有本目录的服务进程。%s" % extra
    pids = []
    for proc in serving:
        try:
            pids.append(int(proc.get("pid")))
        except (TypeError, ValueError):
            continue
    pid_s = ",".join(str(pid) for pid in pids) or "?"
    many = "本目录有 %d 个服务进程。" % len(pids) if len(pids) > 1 else ""
    mismatch = ""
    if lock and lock.get("base") and proc_identity.norm_path(lock.get("base")) != proc_identity.norm_path(base):
        mismatch = "锁里的目录和这次诊断不一致。"
    if stopping:
        return "WARN", "正在停止。pid=%s，已收到停机请求。%s%s" % (pid_s, many, mismatch)
    if lock_bad or not lock:
        return "WARN", "进程表里有本目录服务进程 pid=%s，但没有能用的 state/bot.lock。%s" % (pid_s, many)
    if int(lock["pid"]) not in pids:
        return ("WARN", "进程表里有本目录服务进程 pid=%s，锁里却是 pid %s。%s%s"
                % (pid_s, lock["pid"], many, mismatch))
    level, beat = _beat_clause(hb, hb_bad, lock_mtime, now, after)
    if len(pids) > 1 and level == "OK":
        level = "WARN"
    started = ("锁写于 %s。" % _clock(lock_mtime)) if lock_mtime else ""
    return level, "运行中。pid=%s。%s%s%s%s" % (lock["pid"], started, beat, many, mismatch)


def _iter_jsonl(path):
    if not path or not os.path.isfile(path):
        return
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        yield {"_unreadable": True}
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _ok_flag(value):
    if value is True or value == 1:
        return True
    if value is False or value == 0:
        return False
    if isinstance(value, str) and value.strip().lower() in ("1", "true", "yes"):
        return True
    if isinstance(value, str) and value.strip().lower() in ("0", "false", "no"):
        return False
    return None


def collapse_reason(text):
    """收成一句。堆栈行、File 行和 Traceback 头都丢掉，不把调用栈糊进诊断。"""
    for line in (text or "").splitlines():
        raw = line.rstrip()
        body = raw.strip()
        if not body:
            continue
        found = _LOG_LINE.match(body)
        if found:
            body = found.group(3).strip()
        if not body or body.startswith("Traceback") or _FRAME.match(body):
            continue
        if body.startswith(("During handling of the above exception", "The above exception was the direct cause")):
            continue
        if raw[:1] in (" ", "\t") and not found:
            continue
        body = re.split(r"Traceback \(most recent call last\):", body, maxsplit=1)[0]
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            return body[:500]
    return ""


def _public_sentence(text):
    text = collapse_reason(text) or str(text or "")
    text = _UNIX_HOME.sub("[本地路径已隐藏]", text)
    text = guard.redact(text, ())
    text = _OPEN_ID.sub("某编号", text)
    text = re.sub(r"\s+", " ", text).strip()
    if "Traceback" in text or 'File "' in text:
        text = collapse_reason(text)
    if not text:
        return "日志里没有可读的原因。"
    if len(text) > 120:
        text = text[:120].rstrip() + "…"
    if text[-1] not in "。！？.!?":
        text += "。"
    return text


def _token(text, rx, fallback):
    raw = str(text or "").strip()
    if rx.fullmatch(raw):
        return raw
    return fallback


def _scan_outcomes(base):
    """读回答成败。返回 (成功时间或 None, 失败候选列表, 见过回答没有, 读失败的文件名或空)。

    失败候选是 {ts, sentence, vague}。vague 的行只有「没成功」，没有原因；
    附近 5 秒内的 bot.log 可以补上那一句。
    """
    logs = os.path.join(base or "", "logs")
    ok_ts = None
    saw_answer = False
    fails = []
    broken = ""
    for name in ("events.jsonl", "journal.jsonl"):
        for row in _iter_jsonl(os.path.join(logs, name)):
            if row.get("_unreadable"):
                broken = broken or name
                continue
            if str(row.get("kind") or "") != "answer":
                continue
            stamp = _stamp_epoch(row.get("ts"))
            flag = _ok_flag(row.get("ok"))
            if flag is None or stamp is None:
                continue
            saw_answer = True
            if flag:
                ok_ts = stamp if ok_ts is None else max(ok_ts, stamp)
                continue
            tools = row.get("tools") if isinstance(row.get("tools"), list) else []
            bad = [item for item in tools if isinstance(item, dict) and item.get("ok") is False]
            if bad:
                tool = _token(bad[-1].get("tool"), _TOOL_TOKEN, "未知工具")
                code = _token(bad[-1].get("code"), _CODE_TOKEN, "")
                if code and code != "0":
                    sentence = "回答没有成功，工具 %s 返回错误码 %s。" % (tool, code)
                    vague = False
                else:
                    sentence = "回答没有成功，工具 %s 失败。" % tool
                    vague = False
            elif name == "journal.jsonl":
                sentence = "回答没有成功。journal 只记成败，没有原因。"
                vague = True
            else:
                sentence = "回答没有成功，日志里没有更具体的原因。"
                vague = True
            fails.append({"ts": stamp, "sentence": sentence, "vague": vague})
        if broken:
            continue
        if name != "events.jsonl":
            continue
        for row in _iter_jsonl(os.path.join(logs, name)):
            if row.get("_unreadable"):
                continue
            kind = str(row.get("kind") or "")
            stamp = _stamp_epoch(row.get("ts"))
            if stamp is None:
                continue
            if kind == "tool":
                flag = _ok_flag(row.get("ok"))
                code = _token(row.get("code"), _CODE_TOKEN, "")
                if flag is not False and not (code and code != "0"):
                    continue
                tool = _token(row.get("tool"), _TOOL_TOKEN, "未知工具")
                err = collapse_reason(str(row.get("err") or ""))
                if code and code != "0":
                    sentence = "工具 %s 失败，错误码 %s。" % (tool, code)
                elif err:
                    sentence = "工具 %s 失败：%s" % (tool, err)
                else:
                    sentence = "工具 %s 失败。" % tool
                fails.append({"ts": stamp, "sentence": sentence, "vague": False})
            elif kind == "consumer":
                cause = _token(row.get("cause"), _CODE_TOKEN, "unknown")
                code = _token(row.get("code"), _CODE_TOKEN, "")
                try:
                    rc = int(row.get("rc"))
                except (TypeError, ValueError):
                    rc = None
                event = _token(row.get("event"), _CODE_TOKEN, "")
                who = ("接收进程 %s" % event) if event else "接收进程"
                bits = "原因 %s" % cause
                if rc is not None:
                    bits += "，退出码 %s" % rc
                if code:
                    bits += "，错误码 %s" % code
                fails.append({"ts": stamp, "sentence": "%s 退出，%s。" % (who, bits), "vague": False})
    log_hit = _bot_log_failure(os.path.join(logs, "bot.log"))
    if log_hit == "unreadable":
        broken = broken or "bot.log"
    elif log_hit:
        fails.append(log_hit)
    return ok_ts, fails, saw_answer, broken


def _bot_log_failure(path):
    """最后一条 ERROR。只要那一句，后面的 Traceback 不进诊断。读不到返回 'unreadable'。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return "unreadable"
    blocks = []
    current = None
    for line in lines:
        found = _LOG_LINE.match(line.strip())
        if found:
            if current and current["level"] in ("ERROR", "CRITICAL") and current["text"]:
                blocks.append(current)
            current = {"level": found.group(2), "ts": _stamp_epoch(found.group(1)), "text": found.group(3)}
            continue
        if current and current["level"] in ("ERROR", "CRITICAL") and line.strip():
            current["text"] += "\n" + line
    if current and current["level"] in ("ERROR", "CRITICAL") and current["text"]:
        blocks.append(current)
    chosen = None
    for block in blocks:
        if block["ts"] is None:
            continue
        sentence = collapse_reason(block["text"])
        if not sentence:
            continue
        chosen = {"ts": block["ts"], "sentence": sentence, "vague": False}
    return chosen


def _pick_failure(fails):
    """最近的一条。它自己没有原因时，用 5 秒内更具体的那句，避免只看到「没有成功」。"""
    if not fails:
        return None
    newest = max(item["ts"] for item in fails)
    pool = [item for item in fails if abs(item["ts"] - newest) <= 5]
    specific = [item for item in pool if not item.get("vague")]
    group = specific or pool
    return max(group, key=lambda item: item["ts"])


def last_success(base, now):
    """最近一次成功应答。events.jsonl 和 journal.jsonl 都认，取更晚的那次。"""
    ok_ts, _fails, saw_answer, broken = _scan_outcomes(base)
    if broken and ok_ts is None and not saw_answer:
        return "WARN", "%s 读不到，看不出最近一次成功应答。" % broken
    if ok_ts is None and not saw_answer:
        return "OK", "还没有成功应答。logs/events.jsonl 和 logs/journal.jsonl 都没有成功记录。"
    if ok_ts is None:
        return "WARN", "还没有成功应答。已有的回答记录里没有一次成功。"
    return "OK", "最近一次成功应答是 %s（%s）。" % (_clock(ok_ts), _ago(now, ok_ts))


def last_failure(base, now):
    """最近一条失败，收成一句。之后已经成功应答过就仍是 OK，只是把那一句留下。"""
    ok_ts, fails, _saw, broken = _scan_outcomes(base)
    picked = _pick_failure(fails)
    if picked is None:
        if broken:
            return "WARN", "%s 读不到，看不出最近一条失败。" % broken
        return "OK", "没有失败记录。"
    sentence = _public_sentence(picked["sentence"])
    when = "%s（%s）" % (_clock(picked["ts"]), _ago(now, picked["ts"]))
    if ok_ts is not None and ok_ts + 1 >= picked["ts"]:
        return "OK", "上一笔失败是 %s。%s之后已经成功应答过。" % (when, sentence)
    return "WARN", "最近一条失败是 %s。%s" % (when, sentence)


def checklist_row(lines):
    """把这一次诊断收成通过、警告、失败三份名单。同一个名字只进最严重的那一档。"""
    rank = {}
    order = []
    weight = {"OK": 0, "WARN": 1, "FAIL": 2}
    for line in lines or []:
        parts = (line or "").split(None, 2)
        if len(parts) < 2:
            continue
        level, name = parts[0], parts[1]
        if level not in weight or name == "checklist":
            continue
        if name not in rank:
            order.append(name)
            rank[name] = level
        elif weight[level] > weight[rank[name]]:
            rank[name] = level
    buckets = {"OK": [], "WARN": [], "FAIL": []}
    for name in order:
        buckets[rank[name]].append(name)
    def join(items):
        return "、".join(items) if items else "无"
    info = "通过 %s。警告 %s。失败 %s。" % (join(buckets["OK"]), join(buckets["WARN"]), join(buckets["FAIL"]))
    if buckets["FAIL"]:
        return "FAIL", info
    if buckets["WARN"]:
        return "WARN", info
    return "OK", info


def report(cfg, base, exe, run, processes, resolve, connect, modules, env):
    """返回 (输出行, 退出码)。有 FAIL 时退出码为 1，只有 WARN 时仍是 0。"""
    cfg = cfg or {}
    env = env if env is not None else os.environ
    lines = []
    fail = False

    def add(level, name, info=""):
        nonlocal fail
        if level == "FAIL":
            fail = True
        lines.append(_line(level, name, info))

    secrets = secret_keys(cfg)
    if secrets:
        add("FAIL", "config", "含有密钥字段 %s，请从配置里删掉" % ", ".join(secrets))
    else:
        add("OK", "config", "没有 app_secret")
    from providers.settings import doctor_lines
    for level, name, info in doctor_lines(cfg, env):
        add(level, name, info)

    profile = str(cfg.get("profile") or "")
    if not profile:
        add("FAIL", "profile", "未填写")
    else:
        add("OK", "profile", "已填写")

    code, out, err = run(list(exe) + ["--version"])
    if code == 0:
        add("OK", "lark-cli", ((out or err or "").strip().splitlines() or ["ok"])[0][:80])
    else:
        add("FAIL", "lark-cli", "无法运行 --version")

    if profile:
        code, out, err = run(list(exe) + ["config", "show"])
        add("OK" if code == 0 else "FAIL", "lark config", "能读到" if code == 0 else "config show 失败")
        # lark-cli 1.0.98 的 auth status / auth check / event list 不接受 --as。
        # 带上会退出码 2。那是参数错误，不是登录失败。
        code, out, err = run(list(exe) + ["auth", "status", "--json", "--profile", profile])
        auth_text = (out or "") + "\n" + (err or "")
        ready = bot_ready(auth_text)
        if usage_error(code, auth_text):
            add("WARN", "auth", "参数不被这一版接受，没有因此判失败")
        elif ready is True or (ready is None and logged_in(code, auth_text)):
            add("OK", "auth", "bot" if ready is True else "status 成功")
        else:
            add("FAIL", "auth", "应用身份未就绪或 status 失败")
        # 不带 --as。1.0.98 拒绝 --as bot，而且 auth scopes 在按身份分类时只给用户 token。
        scope_code, scope_out, scope_err = run(list(exe) + ["auth", "scopes", "--profile", profile])
        scope_text = (scope_out or "") + "\n" + (scope_err or "")
        kind, found = classify_scopes(scope_text)
        if usage_error(scope_code, scope_text) or (scope_code != 0 and kind is None):
            add("WARN", "scopes", "列不出应用权限，请在开放平台核对")
        elif kind == "user":
            add("WARN", "scopes", "拿到的是用户 token，不是应用权限，请在开放平台核对")
        elif kind != "app" or found is None:
            add("WARN", "scopes", "没有解析到应用权限列表，请在开放平台核对")
        else:
            missing = [item for item in required_scopes(cfg) if item not in found]
            if missing:
                add("FAIL", "scopes", "缺少 " + ", ".join(missing))
            else:
                add("OK", "scopes", "%d 项" % len(found))
        # event list 列的是命令行认识的全部事件，不是这个应用在开放平台的订阅。不能据此判失败。
        need_ev = required_events(cfg)
        add("OK", "events", "需要 %s。订阅请在开放平台核对，这里不根据 event list 判断" % ", ".join(need_ev))
        if not confirm_mode.wants_cards(cfg):
            card_level, card_info = "OK", "当前确认方式不用点按钮"
        elif confirm_mode.card_callback_setting(cfg) == "off":
            card_level, card_info = "OK", "confirm.card_callback=off，不启动卡片接收进程，确认用确认码。这不算断线"
        elif confirm_mode.card_note_state(base, env) is True:
            card_level, card_info = "OK", "本机已经连上卡片回调"
        elif confirm_mode.card_note_state(base, env) is False:
            card_level = "WARN"
            card_info = (
                "本机记下卡片回调没开通，不会启动或反复重启 card.action.trigger。"
                "这不算机器人断线，也不会发断线提醒。确认已改用确认码，只私聊提醒主人一次。"
                + confirm_mode.CARD_STEPS
            )
        else:
            card_level, card_info = confirm_mode.doctor_card(scope_text)
            card_info += (
                " 没订阅时不启动、也不反复重启这个接收进程，消息长连接仍算连着，不会发断线提醒。"
                "确认自动改用确认码，只私聊提醒主人一次。"
            )
        add(card_level, "card", card_info)

    try:
        addresses = list(resolve("open.feishu.cn"))
    except Exception:
        addresses = []
    if not addresses:
        add("FAIL", "network", "无法解析 open.feishu.cn")
    else:
        fake = [ip for ip, _port in addresses if is_fake_ip(ip)]
        if fake and not proxy_covers_feishu(env.get("NO_PROXY") or env.get("no_proxy") or ""):
            add("WARN", "network", "open.feishu.cn 解析到 198.18/15，NO_PROXY 未包含飞书域名")
        else:
            add("OK", "network", "已解析")
        try:
            ok = bool(connect("open.feishu.cn", 443))
        except Exception:
            ok = False
        add("OK" if ok else "FAIL", "tcp443", "open.feishu.cn" if ok else "连不上 443")

    for mod, label in (("pypdf", "pypdf"), ("openpyxl", "openpyxl"), ("PIL", "pillow")):
        if modules.get(mod):
            add("OK", "package", label)
        else:
            add("WARN", "package", label + " 未安装，对应附件会降级")

    try:
        procs = processes()
    except Exception:
        procs = None
    if procs is None:
        add("WARN", "processes", "列不出进程")
    else:
        for level, info in duplicate_findings(procs, base, profile):
            add(level, "processes", info)
        for level, info in judge_running_consumes(procs, base, profile, cfg, env):
            add(level, "consume", info)
    window, warn_after = restart_setting(cfg)
    now = time.time()
    level, info = restart_ledger(os.path.join(base, "logs", "events.jsonl"), now, window, warn_after)
    add(level, "restart", info)
    # 待确认队列只读一行，放在名单之前，让 checklist 把它算进去。
    # 没有库就是 0，不建文件，也不因为有人还没点确认而判失败。
    level, name, info = pending_queue.doctor_line(base)
    add(level, name, info)
    # 起停、最近一次成功、最近一条失败都是只读探针，不新开连接，也不改退出码语义：
    # 没在跑、旧的失败本身不是 FAIL。名单放在最后，把前面每一项收进去。
    level, info = service_status(base, procs, now, cfg)
    add(level, "service", info)
    level, info = last_success(base, now)
    add(level, "last_ok", info)
    level, info = last_failure(base, now)
    add(level, "last_fail", info)
    level, info = checklist_row(lines)
    add(level, "checklist", info)
    return lines, (1 if fail else 0)


def default_run(argv):
    if "consume" in argv:
        return 1, "", "refused"
    try:
        got = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)[:200]
    return got.returncode, got.stdout or "", got.stderr or ""


def default_resolve(host):
    found = []
    for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        ip = item[4][0]
        if (ip, 443) not in found:
            found.append((ip, 443))
    return found


def default_connect(host, port):
    sock = socket.create_connection((host, port), timeout=5)
    sock.close()
    return True


def windows_process_script():
    """固定脚本。单引号里的 `t 在 PowerShell 5.1 不是制表符，所以用 [char]9。

    先打出 #count=。一个都没枚举到是没看见进程表，不是「没有机器人」。
    """
    return r"""$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $OutputEncoding
$rows = @(Get-CimInstance Win32_Process)
Write-Output ('#count=' + $rows.Count)
foreach ($p in $rows) {
  $cmd = [string]$p.CommandLine
  if (-not $cmd) { continue }
  if ($cmd -notmatch 'agentbot\.py|lark-cli') { continue }
  $flat = (($cmd -replace '\s+', ' ').Trim())
  Write-Output ($p.ProcessId.ToString() + [char]9 + $flat)
}
"""


def windows_process_argv():
    """Windows PowerShell 5.1。不用 pwsh。-EncodedCommand 避免 -Command 再剥一层引号。"""
    encoded = base64.b64encode(windows_process_script().encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def decode_process_output(raw):
    if not raw:
        return ""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    if raw.count(b"\x00") > max(1, len(raw) // 4):
        return raw.decode("utf-16-le", "replace")
    return raw.decode("utf-8", "replace")


def _keep_proc(pid, cmd):
    pid = (pid or "").strip()
    cmd = (cmd or "").strip()
    if not pid.isdigit() or not cmd:
        return None
    if "agentbot.py" not in cmd and "lark-cli" not in cmd:
        return None
    return {"pid": int(pid), "cmdline": cmd}


def _split_proc_line(line):
    """pid 与命令行。制表符、5.1 单引号留下的字面 `t、表格里的多空格都认。"""
    raw = (line or "").strip()
    if not raw or raw.startswith("#"):
        return None, None
    if "\t" in raw:
        pid, cmd = raw.split("\t", 1)
        return pid.strip(), cmd.strip()
    mark = "`t"
    if mark in raw:
        pid, cmd = raw.split(mark, 1)
        return pid.strip(), cmd.strip()
    found = re.match(r"^(\d+)\s+(.*)$", raw)
    if not found:
        return None, None
    return found.group(1), found.group(2).strip()


def _join_wrap(prev, extra):
    extra = (extra or "").strip()
    if not prev:
        return extra
    if not extra:
        return prev
    if extra.startswith('"') or extra.startswith("'"):
        return prev + " " + extra
    return prev + extra


def _parse_format_list(lines):
    props = {}
    order = []
    procs = []
    visible = False

    def flush():
        nonlocal visible
        pid = (props.get("ProcessId") or "").strip()
        cmd = props.get("CommandLine") or ""
        if pid.isdigit():
            visible = True
        item = _keep_proc(pid, cmd)
        if item:
            procs.append(item)

    for line in lines:
        found = re.match(r"^([A-Za-z][A-Za-z0-9]*)\s+:\s?(.*)$", line.rstrip())
        if found:
            key, value = found.group(1), found.group(2).strip()
            props[key] = value
            order.append(key)
            continue
        if line.startswith((" ", "\t")) and order:
            key = order[-1]
            props[key] = _join_wrap(props.get(key) or "", line)
            continue
        if not line.strip():
            flush()
            props = {}
            order = []
    flush()
    return procs, visible


def _parse_csv_snapshot(text):
    sample = (text or "").lstrip("\ufeff")
    first = next((line for line in sample.splitlines() if line.strip()), "")
    # Format-Table 的表头是空格对齐，不是 CSV。必须有逗号才按 CSV 读。
    if "," not in first or "ProcessId" not in first or "CommandLine" not in first:
        return None
    reader = csv.DictReader(io.StringIO(sample))
    if not reader.fieldnames:
        return None
    procs = []
    rows = 0
    for row in reader:
        if not row:
            continue
        norm = {(key or "").strip().lower(): (value or "") for key, value in row.items()}
        pid = (norm.get("processid") or "").strip()
        cmd = (norm.get("commandline") or "").strip()
        if not pid and not cmd:
            continue
        rows += 1
        item = _keep_proc(pid, cmd)
        if item:
            procs.append(item)
    return procs, rows > 0


def parse_process_snapshot(text):
    """返回 (匹配的进程, 是否真的看见了进程表)。

    没看见进程表时，调用方应报 WARN，不要报 OK serving=0。
    """
    raw = text or ""
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    csv_found = _parse_csv_snapshot(raw)
    if csv_found is not None:
        return csv_found
    lines = raw.splitlines()
    if any(re.match(r"^(ProcessId|CommandLine)\s+:", line) for line in lines):
        return _parse_format_list(lines)
    procs = []
    visible = False
    counted = None
    for line in lines:
        stripped = line.strip()
        count = re.match(r"^#count=(\d+)\s*$", stripped)
        if count:
            counted = int(count.group(1))
            if counted > 0:
                visible = True
            continue
        pid, cmd = _split_proc_line(line)
        if pid is None:
            continue
        if not str(pid).strip().isdigit():
            continue
        visible = True
        item = _keep_proc(pid, cmd)
        if item:
            procs.append(item)
    if counted == 0 and not procs:
        visible = False
    return procs, visible


def parse_cim_lines(text):
    procs, _visible = parse_process_snapshot(text)
    return procs


def interpret_process_output(returncode, raw):
    """看懂了进程表就返回列表（可以是空的）。没看懂、命令失败、输出是空的，返回 None。"""
    text = decode_process_output(raw or b"")
    if returncode not in (0, None) and not text.strip():
        return None
    procs, visible = parse_process_snapshot(text)
    if not visible:
        return None
    return procs


def _linux_processes():
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            raw = open("/proc/%s/cmdline" % name, "rb").read()
        except OSError:
            continue
        cmd = raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        if "agentbot.py" in cmd or "lark-cli" in cmd:
            out.append({"pid": int(name), "cmdline": cmd})
    return out


def _windows_processes():
    try:
        got = subprocess.run(windows_process_argv(), capture_output=True, timeout=25)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return interpret_process_output(got.returncode, got.stdout or b"")


def default_processes():
    if os.path.isdir("/proc"):
        return _linux_processes()
    return _windows_processes()


def default_modules():
    found = {}
    for name in ("pypdf", "openpyxl", "PIL"):
        try:
            __import__(name)
            found[name] = True
        except Exception:
            found[name] = False
    return found


def run_doctor(cfg, base, exe, run=None, processes=None, resolve=None, connect=None, modules=None, env=None):
    lines, code = report(
        cfg, base, exe,
        run or default_run,
        processes or default_processes,
        resolve or default_resolve,
        connect or default_connect,
        modules if modules is not None else default_modules(),
        env)
    for line in lines:
        print(line)
    return code
