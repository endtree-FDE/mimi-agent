# 接待桥。默认关。只进不出：从公网端点拉合作意向，去重后追加写进本机待审文件，自己一条消息都不发。
# 这一版不调模型、不读日历、不写飞书。发不发、发给谁，由人看完那个文件决定。
# win-path-fixture：待审文件故意写成盘符开头的绝对路径，测的是它被退回默认相对路径。
import datetime, json, os, shutil, socket, subprocess, sys, tempfile

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401
import broadcast, digest, guard, intake

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(str(detail)[-1500:])


EXAMPLE = json.load(open(os.path.join(FW, "agents", "example.json"), encoding="utf-8-sig"))
SCHEMA = json.load(open(os.path.join(FW, "agents", "config.schema.json"), encoding="utf-8-sig"))


def _cfg(**over):
    raw = {"enabled": True, "url": "https://example.com/leads.json"}
    raw.update(over)
    return {"intake": raw}


PUB = {"example.com": ["93.184.216.34"], "lan.example": ["10.0.0.5"]}
os.environ["AGENTBOT_FAKE_DNS"] = json.dumps(PUB)

# ---- 配置与例子 ----
check("例子里接待桥是关的，地址是占位符，配置里没有密钥值",
      EXAMPLE.get("intake", {}).get("enabled") is False
      and str(EXAMPLE.get("intake", {}).get("url", "")).startswith("REPLACE_")
      and EXAMPLE.get("intake", {}).get("token_env") == ""
      and EXAMPLE.get("intake", {}).get("out_file") == "intake/leads.md"
      and "Bearer " not in json.dumps(EXAMPLE.get("intake"), ensure_ascii=False))
check("模式里补了 intake，且写清只进不出",
      "intake" in SCHEMA.get("properties", {})
      and "只进不出" in json.dumps(SCHEMA["properties"]["intake"], ensure_ascii=False))
check("没写 intake 时不启用；intake 不是字典也不启用；不会因为开了它就顺手打开播报",
      intake.enabled({}) is False and intake.enabled(EXAMPLE) is False
      and intake.enabled({"intake": True}) is False and intake.enabled({"intake": {"url": "https://example.com/a"}}) is False
      and intake.enabled(_cfg()) is True and broadcast.enabled(_cfg()) is False)

# ---- settings：边界、地址、时区、待审文件位置 ----
s = intake.settings(_cfg(interval_min=1, timeout_sec=0))
check("间隔和超时写越界时退回默认，不自己猜一个能用的数",
      s["interval_min"] == 30 and s["timeout"] == 8
      and intake.settings(_cfg(interval_min=99999))["interval_min"] == 30
      and intake.settings(_cfg(timeout_sec=99))["timeout"] == 8)
check("认不出的时区标成不可用，不自己造 UTC 偏移",
      intake.settings(_cfg(timezone="Mars/Olympus"))["tz_ok"] is False
      and intake.settings({})["tz_ok"] is True
      and intake.settings(_cfg(timezone="Asia/Shanghai"))["tz_ok"] is True)
check("内网、占位符、带账号密码、地址里夹密钥的都不算可连的公网",
      intake.settings(_cfg(url="REPLACE_LEADS_HTTPS_URL"))["url_ok"] is False
      and intake.settings(_cfg(url=""))["url_ok"] is False
      and intake.settings(_cfg(url="http://10.1.2.3/leads"))["url_ok"] is False
      and intake.settings(_cfg(url="https://lan.example/leads"))["url_ok"] is False
      and intake.settings(_cfg(url="https://example.com/a?token=supersecretvalue"))["url_ok"] is False
      and intake.settings(_cfg(url="https://user:pass@example.com/a"))["url_ok"] is False
      and intake.settings(_cfg(url="https://example.com/leads.json"))["url_ok"] is True
      and intake.settings(_cfg(url="http://example.com/leads\nX-Evil: 1"))["url_ok"] is False)
for bad in ("C:/Windows/temp/leads.md", "/etc/leads.md", "../../outside.md", "..\\outside.md"):
    got = intake.settings(_cfg(out_file=bad))["out_file"]
    check("待审文件写成越界路径时退回默认相对路径：%s" % bad,
          got == "intake/leads.md" and guard.safe_path("base", got) is not None, got)
check("反斜杠写法在两个系统上都归一成同一条相对路径",
      intake.settings(_cfg(out_file="intake\\sub\\leads.md"))["out_file"] == "intake/sub/leads.md")

# ---- 单条记录：清洗、丢弃、去重编号 ----
NAMES = ("杭州某某科技有限公司",)
check("三项全空的丢掉；只填一项的留下",
      intake.normalize({"note": "   "}, NAMES) is None
      and intake.normalize({}, NAMES) is None
      and intake.normalize("字符串", NAMES) is None
      and intake.normalize({"note": "想做数字展陈"}, NAMES)["note"] == "想做数字展陈")
mixed = intake.normalize({"need": "数字展陈\r\n\t下周", "note": "给" + "长" * 900, "when": "11\u200b月"}, NAMES)
check("控制字符和零宽折成空格，长文按上限截断",
      "\n" not in mixed["need"] and "\r" not in mixed["need"] and "\t" not in mixed["need"]
      and len(mixed["note"]) <= 600 and "\u200b" not in mixed["when"], json.dumps(mixed, ensure_ascii=False))
check("正文里夹着客户名或手机号的整条丢掉，不靠写文件时打码兜底",
      intake.normalize({"note": "杭州某某科技有限公司想看"}, NAMES) is None
      and intake.normalize({"note": "联系 13812345678"}, NAMES) is None)
a = intake.normalize({"need": "展陈", "when": "下月", "note": "同一句话"}, NAMES)
b = intake.normalize({"need": "展陈", "when": "下月", "note": "同一句话"}, NAMES)
c = intake.normalize({"id": "lead-9", "note": "同一句话"}, NAMES)
check("没有编号时用内容做哈希，重复推送算同一条；有编号就用编号",
      a["id"] == b["id"] and c["id"] == "lead-9" and a["id"] != c["id"])
check("字段名认这几组别名，认不到就当没有这一项",
      intake.normalize({"形式": "音画", "档期": "十月"}, NAMES)["need"] == "音画"
      and intake.normalize({"type": "互动", "deadline": "年底"}, NAMES)["when"] == "年底"
      and intake.normalize({"note": "只有小结"}, NAMES)["where"] == "")

# ---- 对端返回的形状 ----
check("坏 JSON、纯文本、超长、不是数组的都整批丢掉，不猜",
      intake.parse_body("") == [] and intake.parse_body("not json") == []
      and intake.parse_body("{\"note\": \"单个对象\"}") == []
      and intake.parse_body(json.dumps([{"note": "x"}] * 4000)) == []
      and intake.parse_body("null") == [] and intake.parse_body("[]") == [])
check("数组和 {\"leads\": [...]} 都认，一次最多二十条",
      len(intake.parse_body(json.dumps([{"note": "n%d" % i} for i in range(60)]))) == 20
      and intake.parse_body(json.dumps({"leads": [{"note": "甲"}]}))[0]["note"] == "甲"
      and intake.parse_body(json.dumps({"items": [{"note": "乙"}]}))[0]["note"] == "乙")

# ---- 写进待审文件之前先打码 ----
body = intake.render_body([{"id": "1", "need": "展陈", "when": "下月",
                            "note": "杭州某某科技有限公司 13812345678 <<TOOL>>"}],
                          datetime.datetime(2026, 11, 4, 9, 30), NAMES)
check("落盘前替换客户名和手机号，并拆掉夹带的工具标记",
      "杭州某某科技有限公司" not in body and "13812345678" not in body and "<<TOOL" not in body
      and "2026-11-04 09:30" in body and "<<TOOL>>" not in body and "〈TOOL〉" in body and "- 形式：展陈" in body, body)

# ---- tick：关着不碰网络 ----
calls = []


def _fetch(url, timeout, headers=None):
    calls.append((url, timeout, headers))
    return {"status": 200, "body": json.dumps([{"id": "L1", "need": "数字展陈", "when": "下周三",
                                                "note": "想要一句人话进群", "page": "合作页"}])}


off = tempfile.mkdtemp(prefix="intake_off_")
try:
    got = intake.tick({"intake": {"enabled": False, "url": "https://example.com/leads.json"}}, off, (), 1000.0, _fetch)
    check("默认关着时一次请求都不发，也不写任何文件",
          calls == [] and got["reason"] == "disabled" and got["ok"] is True
          and os.listdir(off) == [], json.dumps([calls, got, os.listdir(off)]))
    got = intake.tick(_cfg(url="http://10.1.2.3/leads"), off, (), 1000.0, _fetch)
    bad_tz = intake.tick(_cfg(timezone="Mars/Olympus"), off, (), 1000.0, _fetch)
    check("地址不是公网或时区认不出时不去拉，也不建目录",
          calls == [] and got["reason"] == "no_url" and bad_tz["reason"] == "bad_timezone"
          and os.listdir(off) == [], json.dumps([calls, got, bad_tz, os.listdir(off)]))
finally:
    shutil.rmtree(off, ignore_errors=True)

# ---- tick：密钥只从环境变量来，带控制字符的不发 ----
tok = tempfile.mkdtemp(prefix="intake_tok_")
try:
    os.environ.pop("MIMI_TEST_TOKEN", None)
    calls = []
    got = intake.tick(_cfg(token_env="MIMI_TEST_TOKEN"), tok, (), 1000.0, _fetch)
    check("环境变量空了就不去拉，报 no_token（不拿没钥匙的请求去撞对端）",
          got["reason"] == "no_token" and calls == [] and not os.path.isdir(os.path.join(tok, "state")))
    os.environ["MIMI_TEST_TOKEN"] = "abc\r\nX-Evil: 1"
    got = intake.tick(_cfg(token_env="MIMI_TEST_TOKEN"), tok, (), 1000.0, _fetch)
    check("密钥里带换行的当请求头注入拒掉，一个字节都不发出去",
          got["reason"] == "bad_token" and calls == [] and "X-Evil" not in json.dumps(calls))
    os.environ["MIMI_TEST_TOKEN"] = "good-token"
    got = intake.tick(_cfg(token_env="MIMI_TEST_TOKEN"), tok, (), 1000.0, _fetch)
    check("密钥从环境变量取，请求头带的是 Bearer，配置里那份文件不写它的值",
          got["reason"] == "polled" and calls and calls[0][2] == {"authorization": "Bearer good-token",
                                                                  "accept": "application/json"}
          and "good-token" not in open(os.path.join(tok, "intake", "leads.md"), encoding="utf-8").read(),
          json.dumps([got, calls]))
finally:
    os.environ.pop("MIMI_TEST_TOKEN", None)
    shutil.rmtree(tok, ignore_errors=True)

# ---- tick：正常一轮、去重、间隔 ----
work = tempfile.mkdtemp(prefix="intake_work_")
try:
    calls = []
    t0 = 1730000000.0
    r1 = intake.tick(_cfg(), work, NAMES, t0, _fetch)
    n1 = len(calls)
    dest = os.path.join(work, "intake", "leads.md")
    text1 = open(dest, encoding="utf-8").read()
    r3 = intake.tick(_cfg(), work, NAMES, t0 + 300, _fetch)
    n3 = len(calls)
    r2 = intake.tick(_cfg(), work, NAMES, t0 + 3600, _fetch)
    text2 = open(dest, encoding="utf-8").read()
    check("第一轮攒一条，写的是待审文件不是发送",
          r1["ok"] and r1["new"] == 1 and r1["reason"] == "polled" and n1 == 1
          and os.path.isfile(dest) and "- 形式：数字展陈" in text1 and text1.startswith("# "),
          json.dumps([r1, n1, text1]))
    check("没到间隔不去拉，也不算失败",
          r3["reason"] == "too_soon" and n3 == n1, json.dumps([r3, calls]))
    check("对端重复推同一条不再写第二遍",
          r2["ok"] and r2["new"] == 0 and open(dest, encoding="utf-8").read() == text2 == text1, json.dumps(r2))
    check("账本记在 state 里，先写临时文件再换过去",
          os.path.isfile(os.path.join(work, "state", "intake_state.json"))
          and not os.path.exists(os.path.join(work, "state", "intake_state.json.tmp"))
          and "L1" in json.dumps(json.load(open(os.path.join(work, "state", "intake_state.json"), encoding="utf-8"))))
    # 坏返回值：不写文件，也不占坑到永远
    bad = tempfile.mkdtemp(prefix="intake_bad_")
    calls2 = []

    def _down(url, timeout, headers=None):
        calls2.append(url)
        return {"_error": "blocked"}

    def _notfound(url, timeout, headers=None):
        return {"status": 404, "body": "nope"}

    g1 = intake.tick(_cfg(), bad, (), 2000.0, _down)
    g2 = intake.tick(_cfg(), bad, (), 2000.0 + 3600, _notfound)
    g3 = intake.tick(_cfg(), bad, (), 2000.0 + 7200, _down)
    check("连不上或非 200 都不写待审文件，报的是那一次的原因",
          g1["reason"] == "blocked" and g2["reason"] == "status" and not os.path.exists(os.path.join(bad, "intake"))
          and len(calls2) == 2, json.dumps([g1, g2, g3, calls2]))
    g4 = intake.tick(_cfg(), bad, (), 2000.0 + 7300, lambda *a: {"status": 200, "body": "<html>"})
    check("对端返的不是 JSON 时不写文件，也不算错",
          g4["ok"] and g4["new"] == 0 and not os.path.exists(os.path.join(bad, "intake")), json.dumps(g4))
    shutil.rmtree(bad, ignore_errors=True)

    # 一轮里多条：全部落进同一个文件，按本地时区写时间
    many = tempfile.mkdtemp(prefix="intake_many_")

    def _three(url, timeout, headers=None):
        return {"status": 200, "body": json.dumps([{"id": "a", "note": "甲"}, {"id": "b", "note": "乙"},
                                                   {"id": "c", "note": "杭州某某科技有限公司 想聊"},
                                                   {"id": "d", "note": "丙"}])}

    gm = intake.tick(_cfg(), many, NAMES, 1730000000.0, _three)
    content = open(os.path.join(many, "intake", "leads.md"), encoding="utf-8").read()
    want = datetime.datetime.fromtimestamp(1730000000.0, digest.zone("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    utc = datetime.datetime.fromtimestamp(1730000000.0, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    check("一次里三条能收的收下，夹带客户名的那条丢掉并计数",
          gm["new"] == 3 and gm["skipped"] == 1 and content.count("## ") == 3 and "杭州某某科技有限公司" not in content,
          json.dumps([gm, content]))
    check("落盘的时间按配置时区写，不是 UTC",
          want in content and (utc == want or utc not in content), "%s vs %s\n%s" % (want, utc, content[:200]))
    shutil.rmtree(many, ignore_errors=True)
finally:
    shutil.rmtree(work, ignore_errors=True)

# ---- 只进不出：结构上就没有发送的通路 ----
src = open(os.path.join(FW, "intake.py"), encoding="utf-8").read()
check("接待桥不碰发送接口、飞书写接口和模型",
      "outbound." not in src and "_send" not in src and "import outbound" not in src
      and "import agentbot" not in src and "import providers" not in src and "send_" not in src)
bot = open(os.path.join(FW, "agentbot.py"), encoding="utf-8").read()
start = bot.find("def maintenance_tick")
seg = bot[start:bot.find("\ndef ", start + 1)]
check("自检、演练、诊断在调用接待桥之前就返回；它在发送类之后，也不借道发送",
      "if DRY or CHECK or DOCTOR:" in seg and seg.find("intake.tick") > seg.find("if DRY or CHECK or DOCTOR:")
      and "intake.tick(CFG, BASE, REDACT_NAMES, now, log=log)" in seg)

# ---- 提示与状态行 ----
check("没打开时不提示、状态行为空，正文和没有这一项时一样",
      intake.hints({"intake": {"enabled": False}}, ".") == [] and intake.status_line({}, ".") == "")
hint_dir = tempfile.mkdtemp(prefix="intake_hint_")
try:
    lines = " ".join(intake.hints(_cfg(url="http://10.1.2.3/a", timezone="Mars/Olympus",
                                       token_env="MIMI_NOPE", out_file="C:/x/y.md"), hint_dir))
    check("开了但配错时，自检话术把每一处不会拉、不会写的原因说清楚",
          "url" in lines and "timezone" in lines and "MIMI_NOPE" in lines
          and not os.listdir(hint_dir), lines)
    one = intake.status_line(_cfg(), hint_dir)
    check("状态行讲明只收不发，并指到那个待审文件",
          one.startswith("合作意向接待：开") and "只收不发" in one and "intake/leads.md" in one
          and "还没拉过" in one and os.listdir(hint_dir) == [], one)
finally:
    shutil.rmtree(hint_dir, ignore_errors=True)

# ---- 子进程：自检既不拉也不写 ----
def _load_example(work, **over):
    cfg = json.loads(json.dumps(EXAMPLE))
    cfg["base_dir"] = work
    cfg["bot_open_id"] = "ou_bot_placeholder"
    cfg["profile"] = "prof_intake"
    cfg["chat_ids"] = ["oc_chat1"]
    cfg["rate_limit"] = {"min_gap_per_user": 0, "max_per_hour": 100}
    cfg.update(over)
    path = os.path.join(work, "bot.json")
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    open(os.path.join(work, "redact.txt"), "w", encoding="utf-8").write("杭州某某科技有限公司\n")
    return path


def _stage_fake_lark(env, work):
    """自检（--check）对 lark-cli 只做存在性探测：agentbot.py 的 self_check 是
    shutil.which(lark_exe()[0]) or os.path.exists(lark_exe()[0])。CI runner 上
    没装 lark-cli，探测判 FAIL 并把 --check 的退出码打成 1（issue #86）。
    这里按 lark_exe() 的查找规则（Windows 认 %APPDATA% 下的 npm/lark-cli.cmd，
    POSIX 认 PATH 里的 lark-cli）给这个子进程造一个假的，让探测走 OK。
    只改本测试子进程的环境，不碰机器。"""
    if os.name == "nt":
        npmdir = os.path.join(work, "appdata", "npm")
        os.makedirs(npmdir, exist_ok=True)
        with open(os.path.join(npmdir, "lark-cli.cmd"), "w", newline="") as f:
            f.write("@echo off" + chr(13) + chr(10) + "exit /b 0" + chr(13) + chr(10))
        env["APPDATA"] = os.path.join(work, "appdata")
    else:
        bindir = os.path.join(work, "bin")
        os.makedirs(bindir, exist_ok=True)
        fake = os.path.join(bindir, "lark-cli")
        with open(fake, "w") as f:
            f.write("#!/bin/sh" + chr(10) + "exit 0" + chr(10))
        os.chmod(fake, 0o755)
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")

run_dir = tempfile.mkdtemp(prefix="intake_check_")
try:
    os.makedirs(os.path.join(run_dir, "kb"), exist_ok=True)
    path = _load_example(run_dir, intake={"enabled": True, "url": "https://example.com/leads.json",
                                          "token_env": "", "out_file": "intake/leads.md"})
    env = dict(os.environ)
    env["AGENTBOT_FAKE_AGENT"] = "0"
    env["AGENTBOT_FAKE_SEND"] = os.path.join(run_dir, "sent.jsonl")
    env.pop("AGENTBOT_FAKE_DNS", None)
    env["AGENTBOT_FAKE_DNS"] = json.dumps(PUB)
    _stage_fake_lark(env, run_dir)
    events = os.path.join(run_dir, "events.jsonl")
    open(events, "w", encoding="utf-8").write(json.dumps(
        {"event": {"message_id": "i1", "chat_id": "oc_chat1", "chat_type": "group", "message_type": "text",
                   "sender_id": "ou_sender1", "sender_type": "user", "content": "有人在官网留了合作意向",
                   "mentions": []}}, ensure_ascii=False) + "\n")
    proc = subprocess.run([sys.executable, os.path.join(FW, "agentbot.py"), path, "--check"],
                          cwd=FW, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, timeout=90)
    out = (proc.stdout or "") + (proc.stderr or "")
    # 退出码不能当判据：机器上没装 lark-cli 或没配模型密钥时 --check 本来就非 0，
    # 那和接待桥没关系。这条只判两件事——自检走完了整趟，且接待桥自己没被拖进去拉或写。
    lines = out.splitlines()
    check("自检一路走通，且不建账本、不写待审文件、不发东西",
          proc.returncode in (0, 1)
          and any(l.startswith("OK   redact names") for l in lines)
          and any(l.startswith("OK   skills") for l in lines)
          and not any(l.startswith(("FAIL", "HINT")) and ("intake" in l or "接待" in l) for l in lines)
          and not os.path.exists(os.path.join(run_dir, "state", "intake_state.json"))
          and not os.path.exists(os.path.join(run_dir, "intake"))
          and not os.path.exists(os.path.join(run_dir, "sent.jsonl")), out[-1200:])
    dry = subprocess.run([sys.executable, os.path.join(FW, "agentbot.py"), path, "--dry-run", events],
                         cwd=FW, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=env, timeout=90)
    dout = (dry.stdout or "") + (dry.stderr or "")
    check("演练时同样只落盘不发消息：待审文件和账本都没生成，发送落点也是空的",
          dry.returncode == 0 and not os.path.exists(os.path.join(run_dir, "intake"))
          and not os.path.exists(os.path.join(run_dir, "state", "intake_state.json"))
          and not os.path.exists(os.path.join(run_dir, "sent.jsonl")), dout[-600:])
finally:
    shutil.rmtree(run_dir, ignore_errors=True)

# ---- 请求头注入：默认抓取在拼请求之前就拒 ----
cap = []
real_conn = socket.create_connection


def _spy(addr, timeout=None):
    raise AssertionError("must not connect for a bad header: %r" % (addr,))


socket.create_connection = _spy
try:
    inj = broadcast._http_get("https://example.com/leads", 2, 100,
                              headers={"authorization": "Bearer a\r\nX-Evil: 1"})
    badname = broadcast._http_get("https://example.com/leads", 2, 100, headers={"a\nb": "c"})
    check("自定义头里带换行的当注入拒掉，一个连接都不建",
          inj.get("_error") == "blocked" and badname.get("_error") == "blocked"
          and "status" not in inj and "status" not in badname, json.dumps([inj, badname]))
except AssertionError as exc:
    check("自定义头里带换行的当注入拒掉，一个连接都不建", False, str(exc))
finally:
    socket.create_connection = real_conn


class _Sock:
    def __init__(self, chunks):
        self.sent = b""
        self.chunks = list(chunks)

    def sendall(self, data):
        self.sent += data

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        pass


_plain = _Sock([b"HTTP/1.0 200 OK\r\n\r\nok"])
socket.create_connection = lambda addr, timeout=None: _plain
try:
    a = broadcast._http_get("http://example.com/leads", 2, 100)
    check("不传 headers 时，拼出来的请求和以前逐字节一致",
          _plain.sent == b"GET /leads HTTP/1.0\r\nHost: example.com\r\n"
          b"User-Agent: mimi-agent-broadcast\r\nConnection: close\r\n\r\n"
          and a.get("body") == "ok", repr(_plain.sent))
    _hdr = _Sock([b"HTTP/1.0 200 OK\r\n\r\nok"])
    socket.create_connection = lambda addr, timeout=None: _hdr
    broadcast._http_get("http://example.com/leads", 2, 100, headers={"accept": "application/json"})
    check("带自定义头时插在 User-Agent 之后、Connection 之前，其余不动",
          _hdr.sent.decode("latin-1").index("accept: application/json\r\n")
          < _hdr.sent.decode("latin-1").index("Connection: close"), repr(_hdr.sent))
finally:
    socket.create_connection = real_conn

print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
