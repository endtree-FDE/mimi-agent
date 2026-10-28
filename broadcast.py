# 播报。默认关。到点往配置里的群发一条已经准备好的短正文。
# 不调用模型，不读日历，不读任务表，不抓资讯。
# 正文可以同时来自本机文件、只读命令的标准输出、配置里的静态文字，以及公网地址的状态码和限长摘录。
# 每个群本地日历日最多一条。演练、自检、诊断不进这里。正文不点名所有人。
import json, os, re, subprocess
import digest, guard, outbound

_PROMPT_NOTE = "播报由程序在配置的时间发给指定群，不是你这一轮要写的。回答里不要点名所有人，也不要写出提及所有人的标记。这条不读日历，也不读任务表。"
_SOURCES = ("file", "command", "static", "http")
_ALIAS = {"body_file": "file", "body": "static", "url": "http", "urls": "http", "hook": "command", "cmd": "command"}
_SHELLS = {
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    "bash", "bash.exe", "sh", "sh.exe", "zsh", "zsh.exe",
    "wscript", "wscript.exe", "cscript", "cscript.exe",
}
_SCRIPT_EXT = (".bat", ".cmd", ".ps1", ".vbs")
_ENV_KEEP = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE",
    "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "LANG", "LC_ALL", "LC_CTYPE",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
    "LOCALAPPDATA", "APPDATA",
}
_ENV_DROP = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API_KEY|APP_SECRET)", re.I)
_BODY_LIMIT = 8000
_HTTP_LIMIT = 4096
_EXCERPT = 180


def _num(value, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return default
    return number


def _clean_id(value):
    text = str(value or "").strip()
    if not text or text.startswith("REPLACE_") or not outbound._ID.match(text):
        return ""
    return text


def enabled(cfg):
    raw = (cfg or {}).get("broadcast")
    return isinstance(raw, dict) and bool(raw.get("enabled"))


def prompt_note(cfg):
    """放进稳定前缀。关掉时是空字符串，提示词和没有这项时一样。"""
    return _PROMPT_NOTE if enabled(cfg) else ""


def _body_file(value):
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith("REPLACE_") or "/REPLACE_" in text:
        return ""
    if "\x00" in text or len(text) > 200:
        return ""
    return text


def _command_argv(value):
    if not isinstance(value, list) or not value or len(value) > 8:
        return []
    out = []
    for item in value:
        if not isinstance(item, str):
            return []
        out.append(item)
    return out


def _urls(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        url = str(item or "").strip()
        if not url or url.startswith("REPLACE_") or any(c in url for c in "\x00\r\n\t"):
            continue
        url = url[:1024]
        if url not in out:
            out.append(url)
        if len(out) >= 5:
            break
    return out


def _explicit_source(raw):
    text = str(raw.get("source") or "").strip().lower()
    if not text:
        return ""
    text = _ALIAS.get(text, text)
    if text in _SOURCES:
        return text
    return "invalid"


def _parts(explicit, body_file, command, text, urls):
    """不写 source 时，填了的来源都放进同一条。写了 source 就只用那一项。"""
    if explicit == "invalid":
        return []
    if explicit:
        return [explicit]
    out = []
    if text.strip():
        out.append("static")
    if urls:
        out.append("http")
    if body_file:
        out.append("file")
    if command:
        out.append("command")
    return out


def settings(cfg):
    raw = (cfg or {}).get("broadcast")
    if not isinstance(raw, dict):
        raw = {}
    hh, mm = 9, 0
    text = str(raw.get("time") or "09:00").strip()
    matched = re.match(r"^(\d{1,2}):(\d{2})$", text)
    ok_time = False
    if matched:
        hh, mm = int(matched.group(1)), int(matched.group(2))
        ok_time = 0 <= hh <= 23 and 0 <= mm <= 59
    if not ok_time:
        hh, mm = 9, 0
    window = raw.get("window_min", 30)
    if window is None or window == "":
        window = 30
    else:
        window = _num(window, 30)
    chats = []
    for item in raw.get("chat_ids") or []:
        cid = _clean_id(item)
        if cid and cid not in chats:
            chats.append(cid)
    title = str(raw.get("title") or "播报").replace("\r", " ").replace("\n", " ").strip()[:40] or "播报"
    body_file = _body_file(raw.get("body_file"))
    command = _command_argv(raw.get("command"))
    static = str(raw.get("text") or "")
    if len(static) > _BODY_LIMIT:
        static = static[:_BODY_LIMIT]
    urls = _urls(raw.get("urls"))
    explicit = _explicit_source(raw)
    timeout = raw.get("timeout_sec", 8)
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = 8
    if timeout < 1 or timeout > 20:
        timeout = 8
    return {
        "enabled": bool(raw.get("enabled")),
        "hour": hh,
        "minute": mm,
        "time_ok": ok_time or "time" not in raw,
        "window": window,
        "timezone": str(raw.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai",
        "chats": chats,
        "title": title,
        "source": "" if explicit == "invalid" else explicit,
        "parts": _parts(explicit, body_file, command, static, urls),
        "body_file": body_file,
        "command": command,
        "text": static,
        "urls": urls,
        "timeout": timeout,
    }


def hints(cfg, base):
    """给 --check 的人看。关掉时不提这项。"""
    spec = settings(cfg)
    if not spec["enabled"]:
        return []
    lines = []
    if not spec["chats"]:
        lines.append("broadcast.enabled 已打开，但 chat_ids 为空。不会往任何群发播报，也不会去读日历或任务表。")
    if not spec["time_ok"]:
        lines.append("broadcast.time 不是 HH:MM，播报不会发。")
    elif digest.zone(spec["timezone"]) is None:
        lines.append("broadcast.timezone 认不出来，播报不会发。")
    parts = spec["parts"]
    if not parts:
        lines.append("broadcast 已打开，但 body_file、command、text、urls 都空着或 source 认不出来。不会发，也不会去读日历或任务表。")
    if "file" in parts:
        path = guard.safe_path(base or ".", spec["body_file"]) if spec["body_file"] else None
        if not path or not os.path.isfile(path):
            lines.append("broadcast.body_file 读不到。这一段到点会说暂时没有读到；别的段仍可发。")
    if "command" in parts and (not spec["command"] or not _argv_ok(spec["command"], ())):
        lines.append("broadcast.command 要写成程序和参数的数组，不能是 shell。这一段不会执行。")
    if "static" in parts and not str(spec["text"] or "").strip():
        lines.append("broadcast.text 是空的。这一段不会发。")
    if "http" in parts and not spec["urls"]:
        lines.append("broadcast.urls 是空的。站点这一段不会发。")
    return lines


def _state_path(base):
    return os.path.join(base, "state", "broadcast_state.json")


def _load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def _slot(day, chat):
    return "%s|%s" % (day, chat)


def _note_once(base, day, kind, log, message):
    path = _state_path(base)
    slot = "%s|%s" % (day, kind)
    try:
        with digest.outbound_lock(path):
            state = _load(path)
            notes = state.setdefault("notes", {})
            if notes.get(slot):
                return
            notes[slot] = 1
            _save(path, state)
    except TimeoutError:
        return
    if log:
        log.info(message)


def _clip(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    lines = text.split("\n")
    if len(lines) > 40:
        lines = lines[:40] + ["（还有内容没有放进这条）"]
    text = "\n".join(lines)
    if len(text) > _BODY_LIMIT:
        text = text[:_BODY_LIMIT].rstrip()
    return text


def _argv_ok(argv, names):
    if not isinstance(argv, list) or not argv or len(argv) > 8:
        return False
    for item in argv:
        if not isinstance(item, str) or not item.strip() or len(item) > 400:
            return False
        if any(c in item for c in "\x00\r\n"):
            return False
        if guard.embeds_secret(item, names):
            return False
    base = os.path.basename(argv[0].replace("\\", "/")).lower()
    if base in _SHELLS or base.endswith(_SCRIPT_EXT):
        return False
    return True


def _child_env():
    out = {}
    for key, value in os.environ.items():
        if key.upper() not in _ENV_KEEP and key not in _ENV_KEEP:
            continue
        if _ENV_DROP.search(key):
            continue
        out[key] = value
    out["PYTHONIOENCODING"] = "utf-8"
    out["PYTHONUTF8"] = "1"
    return out


def _run_command(argv, cwd, timeout, limit):
    """不经过 shell。标准错误丢掉。超时杀掉进程。失败返回空字符串。"""
    proc = subprocess.Popen(
        argv, cwd=cwd, env=_child_env(), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    try:
        out, _err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.kill()
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        return ""
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (out or "")[:limit]


def _from_file(base, rel):
    path = guard.safe_path(base, rel) if rel else None
    if not path or not os.path.isfile(path):
        return "", False
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            data = handle.read(_BODY_LIMIT)
    except OSError:
        return "", False
    data = _clip(data)
    return (data, True) if data else ("", False)


def _from_command(spec, base, names, run_command):
    argv = spec["command"]
    if not _argv_ok(argv, names) or not base or not os.path.isdir(base):
        return "", False
    try:
        text = run_command(argv, base, spec["timeout"], _BODY_LIMIT)
    except Exception:
        return "", False
    text = _clip(text or "")
    return (text, True) if text else ("", False)


def _from_static(spec):
    text = _clip(spec["text"])
    return (text, True) if text else ("", False)


def _url_allowed(url, names):
    import acp_client
    if guard.embeds_secret(url, names):
        return False
    return bool(acp_client._public_http_url(url))


def _show_url(url):
    from urllib.parse import urlparse
    parts = urlparse(url)
    host = parts.hostname or ""
    path = parts.path or ""
    if len(path) > 60:
        path = path[:60]
    shown = (host + path)[:80]
    return shown or "网页"


def _excerpt(raw):
    import html
    text = re.sub(r"(?is)<script\b.*?>.*?</script>", " ", raw or "")
    text = re.sub(r"(?is)<style\b.*?>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_EXCERPT]


def _http_get(url, timeout, limit):
    """只连接已经判定为公网的地址，不跟随跳转，只读有限长度。"""
    import socket, ssl
    from urllib.parse import urlparse
    import acp_client
    if not _url_allowed(url, ()):
        return {"_error": "blocked"}
    parts = urlparse((url or "").strip())
    host = parts.hostname
    if not host:
        return {"_error": "blocked"}
    addrs = acp_client._public_addrs(host)
    if not addrs:
        return {"_error": "blocked"}
    ip = sorted(addrs)[0]
    try:
        import ipaddress
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return {"_error": "blocked"}
    if acp_client._ip_is_blocked(addr, allow_fake=True):
        return {"_error": "blocked"}
    scheme = (parts.scheme or "").lower()
    port = parts.port or (443 if scheme == "https" else 80)
    path = parts.path or "/"
    if any(c in path for c in "\r\n\x00"):
        return {"_error": "blocked"}
    try:
        host_ascii = host.encode("idna").decode("ascii")
    except Exception:
        return {"_error": "blocked"}
    try:
        timeout = max(1, min(int(timeout or 8), 20))
    except (TypeError, ValueError):
        timeout = 8
    try:
        cap = max(256, min(int(limit or _HTTP_LIMIT), _HTTP_LIMIT))
    except (TypeError, ValueError):
        cap = _HTTP_LIMIT
    sock = socket.create_connection((str(ip), int(port)), timeout=timeout)
    try:
        if scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        req = "GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: mimi-agent-broadcast\r\nConnection: close\r\n\r\n" % (path, host_ascii)
        sock.sendall(req.encode("ascii", "replace"))
        sock.settimeout(timeout)
        buf = b""
        while len(buf) < cap + 4096:
            chunk = sock.recv(1024)
            if not chunk:
                break
            buf += chunk
    except Exception:
        return {"_error": "fetch"}
    finally:
        try:
            sock.close()
        except Exception:
            pass
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1", "replace").split("\r\n")
    if not lines or not lines[0].startswith("HTTP/"):
        return {"_error": "fetch"}
    bits = lines[0].split()
    if len(bits) < 2 or not bits[1].isdigit():
        return {"_error": "fetch"}
    return {"status": int(bits[1]), "body": rest[:cap].decode("utf-8", "replace")}


def _from_http(spec, names, fetch, timeout):
    lines = []
    observed = 0
    for url in spec["urls"]:
        if not _url_allowed(url, names):
            continue
        try:
            got = fetch(url, timeout, _HTTP_LIMIT)
        except Exception:
            got = None
        if not isinstance(got, dict):
            continue
        try:
            status = int(got.get("status"))
        except (TypeError, ValueError):
            continue
        observed += 1
        word = "ok" if 200 <= status <= 299 else "fail"
        lines.append("- %s %s %s" % (_show_url(url), status, word))
        excerpt = _excerpt(str(got.get("body") or ""))
        if excerpt:
            lines.append("  " + excerpt)
    if observed == 0:
        return "", False
    return _clip("\n".join(lines)), True


def collect(cfg, base, names, fetch_http=None, run_command=None):
    """返回 (正文, 是否至少读到一段)。一段都没有时调用方不占坑。"""
    spec = settings(cfg)
    parts = spec["parts"]
    if not parts:
        return "", False
    blocks = []
    got = 0
    for kind in parts:
        if kind == "static":
            body, ok = _from_static(spec)
            if ok:
                blocks.append(body)
                got += 1
        elif kind == "http":
            body, ok = _from_http(spec, names, fetch_http or _http_get, spec["timeout"])
            if ok:
                blocks.append("站点\n" + body)
                got += 1
            else:
                blocks.append("站点\n暂时没有读到。")
        elif kind == "file":
            body, ok = _from_file(base, spec["body_file"])
            if ok:
                blocks.append(body)
                got += 1
            else:
                blocks.append("正文暂时没有读到。")
        elif kind == "command":
            body, ok = _from_command(spec, base, names, run_command or _run_command)
            if ok:
                blocks.append(body)
                got += 1
            else:
                blocks.append("命令暂时没有读到。")
    if got == 0:
        return "", False
    return _clip("\n\n".join(blocks)), True


def render(cfg, moment, body, names):
    spec = settings(cfg)
    name = ""
    bot_names = (cfg or {}).get("bot_names") or []
    if bot_names and isinstance(bot_names[0], str):
        name = bot_names[0].strip()[:40]
    if not name:
        name = "机器人"
    body = _clip(body)
    if not body:
        return ""
    # 正文里如果只剩点名，整条都不发，避免群里只看到一个空标题。
    cleaned = outbound.prepare(guard.neutralize(guard.redact(body, names)), names)
    if not cleaned:
        return ""
    lines = ["【%s】%s（%s）" % (name, spec["title"], moment.date().isoformat()), "", cleaned]
    return outbound.prepare("\n".join(lines), names)


def _retry(path, now, log):
    with digest.outbound_lock(path):
        state = _load(path)
        state["retry_after"] = float(now) + 300
        _save(path, state)
    if log:
        log.info("broadcast retry later")


def deliver(cfg, base, names, now, sender, served, log=None, fetch_http=None, run_command=None):
    """sender(chat, text, key) -> ok/fail/unknown。served 是允许回答的群。"""
    spec = settings(cfg)
    if not spec["enabled"] or not spec["time_ok"]:
        return []
    tz = digest.zone(spec["timezone"])
    if tz is None:
        _note_once(base, "tz", spec["timezone"] or "empty", log, "broadcast skipped: bad timezone")
        return []
    moment = digest.local_now(now, tz)
    if not digest.in_window(moment, spec["hour"], spec["minute"], spec["window"]):
        return []
    day = digest.day_key(moment, spec["hour"], spec["minute"], spec["window"])
    allowed = []
    served_set = {str(item) for item in (served or [])}
    for chat in spec["chats"]:
        if chat in served_set:
            allowed.append(chat)
    if not allowed:
        _note_once(base, day, "no-chat", log, "broadcast skip: no served chat")
        return []
    if not spec["parts"]:
        _note_once(base, day, "no-source", log, "broadcast skip: no source")
        return []
    path = _state_path(base)
    pending = []
    with digest.outbound_lock(path):
        state = _load(path)
        retry = float(state.get("retry_after") or 0)
        items = state.get("items") or {}
        for chat in allowed:
            slot = items.get(_slot(day, chat)) or {}
            if slot.get("status") not in ("posted", "claimed"):
                pending.append(chat)
    if not pending or float(now) < retry:
        return []
    body, ok = collect(cfg, base, names, fetch_http, run_command)
    text = render(cfg, moment, body, names) if ok else ""
    if not ok or not text or outbound.mentions_everyone(text):
        _retry(path, now, log)
        return []
    sent = []
    for chat in pending:
        key = outbound.idem_key("broadcast|%s|%s" % (day, chat))
        with digest.outbound_lock(path):
            state = _load(path)
            items = state.setdefault("items", {})
            slot = items.get(_slot(day, chat)) or {}
            if slot.get("status") in ("posted", "claimed"):
                continue
            items[_slot(day, chat)] = {"status": "claimed", "at": float(now)}
            _save(path, state)
        try:
            result = sender(chat, text, key)
        except Exception:
            result = "fail"
        with digest.outbound_lock(path):
            state = _load(path)
            items = state.setdefault("items", {})
            if result == "ok":
                items[_slot(day, chat)] = {"status": "posted", "at": float(now)}
                sent.append(chat)
            elif result == "fail":
                items.pop(_slot(day, chat), None)
            else:
                items[_slot(day, chat)] = {"status": "claimed", "at": float(now)}
            _save(path, state)
        if log:
            log.info("broadcast %s result=%s", "posted" if result == "ok" else result, result)
    return sent
