# 接待桥的下一跳：把「官网攒下的合作意向」带到飞书里的人面前。默认关。
# 分工写死在这儿：intake.py 只进不出（tests/test_intake.py 结构上钉着它不能碰发送），
# 会发消息的只有本模块，而且只有主人本人在私聊回了确认码才发群。
# 这一版不调模型、不读日历、不自己决定发给谁。
# win-path-fixture：C:\\ 只用来断言提醒正文里不出现机器上的绝对路径，不是拿去拼文件的夹具。
import datetime, json, os, shutil, sys, tempfile

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401
import intake_notify

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(str(detail)[-1500:])


EXAMPLE = json.load(open(os.path.join(FW, "agents", "example.json"), encoding="utf-8-sig"))
SCHEMA = json.load(open(os.path.join(FW, "agents", "config.schema.json"), encoding="utf-8-sig"))
NAMES = ("杭州某某科技有限公司",)
OWNER = "ou_owner_1"
OTHER = "ou_other_1"
CHAT = "oc_group_1"


def _cfg(**over):
    """接待桥本体开着，提醒按需开。over 里的键写进 notify。"""
    notify = {"enabled": True, "owner_open_ids": [OWNER], "chat_ids": [CHAT]}
    notify.update(over)
    raw = {"enabled": True, "url": "https://example.com/leads.json", "notify": notify}
    return {"intake": raw}


def _fill(base, items, start=0):
    """往待审文件里放几条已经落盘的意向（接待桥写出来的那个样子）。"""
    os.makedirs(os.path.join(base, "intake"), exist_ok=True)
    lines = ["# 待看的合作意向（机器人只写这个文件，不会自己发出去）", ""]
    for index, note in enumerate(items):
        lines.append("## 2026-11-0%d 09:%02d 来自 合作页" % (1 + (start + index) % 9, (start + index) % 60))
        lines.append("- 形式：数字展陈")
        lines.append("- 小结：%s" % note)
        lines.append("")
    with open(os.path.join(base, "intake", "leads.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    return [x for x in items]


class Sender:
    def __init__(self, result="ok"):
        self.calls = []
        self.result = result

    def __call__(self, kind, target, text, key):
        self.calls.append({"kind": kind, "target": target, "text": text, "key": key})
        return self.result

    def kinds(self, kind):
        return [c for c in self.calls if c["kind"] == kind]


class _Dir:
    """临时目录，退出就删。"""

    def __enter__(self):
        self.path = tempfile.mkdtemp(prefix="intake_notify_")
        return self.path

    def __exit__(self, *_a):
        shutil.rmtree(self.path, ignore_errors=True)


T0 = 1730000000.0

# ---- 默认关 ----
check("例子里提醒是关的，模式里补了这一项并写清要确认码",
      EXAMPLE.get("intake", {}).get("notify", {}).get("enabled") is False
      and "notify" in json.dumps(SCHEMA.get("properties", {}), ensure_ascii=False)
      and "确认" in json.dumps(SCHEMA["properties"]["intake"], ensure_ascii=False))
check("不写 notify、写成别的、接待桥本体关着，都算提醒关",
      intake_notify.enabled({}) is False
      and intake_notify.enabled({"intake": {"enabled": True}}) is False
      and intake_notify.enabled({"intake": {"enabled": True, "notify": True}}) is False
      and intake_notify.enabled({"intake": {"enabled": False, "notify": {"enabled": True}}}) is False
      and intake_notify.enabled(_cfg()) is True)
sent = Sender()
with _Dir() as base:
    got = intake_notify.tick({"intake": {"enabled": True, "notify": {"enabled": False}}}, base, NAMES, T0, sent)
    check("关着时一次发送都不做，也不建任何目录",
          sent.calls == [] and got["reason"] == "disabled" and os.listdir(base) == [],
          json.dumps([sent.calls, got, os.listdir(base)]))

# ---- settings：越界退回、时区、主人来源 ----
s = intake_notify.settings(_cfg(min_items=0, max_per_day=99, min_gap_min=0, max_items=999))
check("提醒的阈值写越界时退回默认，不自己放宽",
      s["min_items"] == 1 and s["max_per_day"] == 2 and s["min_gap_min"] == 60 and s["max_items"] == 5
      and intake_notify.settings(_cfg(min_items=-3))["min_items"] == 1
      and intake_notify.settings(_cfg(max_items=0))["max_items"] == 5)
check("认不出的时区标成不可用，不会因此提醒",
      intake_notify.settings(_cfg(timezone="Mars/Olympus"))["tz_ok"] is False
      and intake_notify.settings(_cfg())["tz_ok"] is True)
check("没写主人编号时退回用量周报/断线提醒那一份；占位符不算编号",
      intake_notify.settings({"intake": {"enabled": True, "notify": {"enabled": True}}})["owners"] == []
      and intake_notify.settings(_cfg(owner_open_ids=["REPLACE_OWNER_OPEN_ID"]))["owners"] == []
      and intake_notify.settings(
          {"intake": {"enabled": True, "notify": {"enabled": True}},
           "alerts": {"owner_open_ids": [OWNER]}})["owners"] == [OWNER])

# ---- 一轮提醒：只私聊，不群发 ----
with _Dir() as base:
    _fill(base, ["甲", "乙"])
    sent = Sender()
    got = intake_notify.tick(_cfg(), base, NAMES, T0, sent)
    p2p = sent.kinds("user")
    check("攒够条数才提醒，而且只私聊发给主人，一条群消息都不发",
          got["reason"] == "notified" and got["new"] == 2 and len(p2p) == 1
          and p2p[0]["target"] == OWNER and sent.kinds("chat") == [], json.dumps([got, sent.calls]))
    text = p2p[0]["text"] if p2p else ""
    code = intake_notify._code_in(text)
    check("提醒里讲清几条、记在哪个相对路径、不回复就什么都不发",
          "2 条" in text and "intake/leads.md" in text and "不发" in text
          and "C:\\" not in text and not os.path.dirname(os.path.abspath(FW)) in text, text)
    check("确认码是六位数字，正文里没有客户名也没有工具标记",
          len(code) == 6 and code.isdigit() and "杭州某某" not in text and "<<TOOL" not in text, text)
    check("账本落在 state 里，先写临时文件再换过去",
          os.path.isfile(os.path.join(base, "state", "intake_notify.json"))
          and not os.path.exists(os.path.join(base, "state", "intake_notify.json.tmp")))
    again = intake_notify.tick(_cfg(), base, NAMES, T0 + 60, sent)
    check("同一批内容不会第二次提醒（还没有人处理，等下一次间隔）",
          again["reason"] in ("too_soon", "nothing_new") and len(sent.kinds("user")) == 1,
          json.dumps([again, sent.calls]))
    n_before = len(sent.kinds("user"))
    _fill(base, ["甲", "乙", "丙"])
    late = intake_notify.tick(_cfg(), base, NAMES, T0 + 3700, sent)
    check("闲下来没到间隔不提醒，到了间隔且有新内容才提醒",
          late["reason"] == "notified" and len(sent.kinds("user")) == n_before + 1,
          json.dumps([late, len(sent.kinds("user"))]))

# ---- 不够条数 / 一天封顶 ----
with _Dir() as base:
    _fill(base, ["甲"])
    sent = Sender()
    got = intake_notify.tick(_cfg(min_items=3), base, NAMES, T0, sent)
    check("没攒够 min_items 不发提醒", got["reason"] == "below_min" and sent.calls == [], json.dumps([got, sent.calls]))
with _Dir() as base:
    sent = Sender()
    for index in range(4):
        _fill(base, ["甲%d" % index, "乙%d" % index], start=index * 2)
        got = intake_notify.tick(_cfg(min_gap_min=5), base, NAMES, T0 + index * 400, sent)
    check("同一个本地日最多 max_per_day 条提醒，多的攒着",
          got["reason"] == "day_limit" and len(sent.kinds("user")) == 2,
          json.dumps([got, len(sent.kinds("user"))]))

# ---- 确认之前不往群里发 ----
def _issue(cfg, base, notes, now=T0):
    sent = Sender()
    _fill(base, notes)
    got = intake_notify.tick(cfg, base, NAMES, now, sent)
    text = sent.kinds("user")[0]["text"]
    return sent, intake_notify._code_in(text), got


CTX_OK = {"user": OWNER, "chat_type": "p2p", "chat_id": ""}
OK_NOW = T0 + 120          # 主人收到提醒之后、在有效期内本人回复


def _ht(cfg, base, q, ctx, sender, names=NAMES, served=None, now=OK_NOW):
    return intake_notify.handle_text(cfg, base, q, ctx, names, sender, served=served, now=now)


with _Dir() as base:
    sent, code, _ = _issue(_cfg(), base, ["甲", "乙"])
    before = len(sent.kinds("chat"))
    reply = _ht(_cfg(), base, "随便聊两句", CTX_OK, sent)
    check("不是本模块命令的话一句都不接，也不会发群",
          reply is None and len(sent.kinds("chat")) == before, json.dumps(reply))
    wrong = _ht(_cfg(), base, "发意向 %s" % code, {"user": OTHER, "chat_type": "p2p"}, sent)
    check("别人拿同一个码也不能发", wrong is not None and "本人" in wrong
          and len(sent.kinds("chat")) == before, wrong)
    in_group = _ht(_cfg(), base, "发意向 %s" % code,
                   {"user": OWNER, "chat_type": "group", "chat_id": CHAT}, sent)
    check("主人在群里回复同样不算确认（提醒发在私聊，确认就回在私聊）",
          in_group is not None and "本人" in in_group and len(sent.kinds("chat")) == before, in_group)
    ok = _ht(_cfg(), base, "发意向 %s" % code, CTX_OK, sent, served=[CHAT])
    chats = sent.kinds("chat")
    check("主人本人在私聊回确认码之后才发群，正文带的是那两条意向",
          ok is not None and "已发" in ok and len(chats) == 1 and chats[0]["target"] == CHAT
          and "甲" in chats[0]["text"] and "乙" in chats[0]["text"], json.dumps([ok, chats]))
    twice = _ht(_cfg(), base, "发意向 %s" % code, CTX_OK, sent, served=[CHAT])
    check("同一个码用第二次不会重发", twice is not None and "处理过" in twice
          and len(sent.kinds("chat")) == 1, json.dumps([twice, sent.calls]))

# ---- 不在服务范围的群不发；过期不发 ----
with _Dir() as base:
    sent, code, _ = _issue(_cfg(), base, ["甲"])
    out = _ht(_cfg(), base, "发意向 %s" % code, CTX_OK, sent, served=["oc_other"])
    check("配置里的群不在服务范围时一条都不发，并说明原因",
          out is not None and "没发" in out and sent.kinds("chat") == [], out)
with _Dir() as base:
    sent, code, _ = _issue(_cfg(), base, ["甲"])
    _ht(_cfg(), base, "发意向 %s" % code, CTX_OK, sent, served=["oc_other"])
    again = _ht(_cfg(), base, "发意向 %s" % code, CTX_OK, sent, served=[CHAT])
    state = json.load(open(intake_notify._state_path(base), encoding="utf-8"))
    check("说「确认码已作废」就真作废：再换成服务范围内的群回同一个码也不发，但这批意向还留在待看里",
          again is not None and sent.kinds("chat") == []
          and bool((state.get("codes") or {}).get(code, {}).get("used"))
          and intake_notify.pending(_cfg(), base) != [],
          json.dumps([again, (state.get("codes") or {}).get(code)]))
with _Dir() as base:
    sent, code, _ = _issue(_cfg(), base, ["甲"])
    stale = _ht(_cfg(), base, "发意向 %s" % code, CTX_OK, sent, served=[CHAT], now=T0 + 90000)
    check("确认码过期后不发，正文和账本都不动",
          stale is not None and "过期" in stale and sent.kinds("chat") == [], stale)
with _Dir() as base:
    sent, code, _ = _issue(_cfg(), base, ["甲"])
    skip = _ht(_cfg(), base, "不发意向 %s" % code, CTX_OK, sent, served=[CHAT])
    check("回「不发意向」就只记账不发群，这批之后也不再提醒",
          skip is not None and "没发" in skip and sent.kinds("chat") == []
          and intake_notify.pending(_cfg(), base) == [], json.dumps([skip, sent.calls]))

# ---- 发出去才算处理过 ----
with _Dir() as base:
    sent, code, _ = _issue(_cfg(), base, ["甲", "乙"])
    _ht(_cfg(), base, "发意向 %s" % code, CTX_OK, sent, served=[CHAT])
    check("确认发出去的这批不再提醒，之后的新内容才会提醒",
          len(intake_notify.pending(_cfg(), base)) == 0, json.dumps(intake_notify.pending(_cfg(), base)))
    _fill(base, ["甲", "乙", "丙"], start=0)
    sent2 = Sender()
    got = intake_notify.tick(_cfg(), base, NAMES, T0 + 7200, sent2)
    check("重写过文件也不会把已发过的那几条算成新的",
          got["reason"] == "notified" and got["new"] == 1 and "丙" in sent2.kinds("user")[0]["text"],
          json.dumps([got, sent2.calls]))

# ---- 一条都没发出去时不要把账记成已处理 ----
with _Dir() as base:
    sent, code, _ = _issue(_cfg(), base, ["甲", "乙"])
    broken = Sender("fail")
    out = _ht(_cfg(), base, "发意向 %s" % code, CTX_OK, broken, served=[CHAT])
    check("发送接口一条都没认，回话照实说没发出去",
          out is not None and "没发出去" in out, out)
    check("这一批没发成就留在待看里，下一轮提醒会换个新码",
          len(intake_notify.pending(_cfg(), base)) == 2, json.dumps(intake_notify.pending(_cfg(), base)))

# ---- 一次最多带几条 ----
with _Dir() as base:
    many = ["内容%d" % i for i in range(9)]
    sent = Sender()
    _fill(base, many)
    got = intake_notify.tick(_cfg(max_items=5), base, NAMES, T0, sent)
    code = intake_notify._code_in(sent.kinds("user")[0]["text"])
    text = sent.kinds("user")[0]["text"]
    check("一次最多带 max_items 条，提醒里说清总共几条、这次带几条",
          got["new"] == 9 and "共 9 条" in text and "这次带 5 条" in text, text)
    _ht(_cfg(max_items=5), base, "发意向 %s" % code, CTX_OK, sent, served=[CHAT])
    body = sent.kinds("chat")[0]["text"]
    check("确认后发的正是提醒里圈定那几条，剩下的等下一轮",
          body.count("## ") == 5 and "内容0" in body and "内容8" not in body
          and len(intake_notify.pending(_cfg(max_items=5), base, now=OK_NOW)) == 4, body)
    check("发出去的正文不超过发送接口的上限，超了就写明还有内容没放进来",
          len(body) <= 3500, len(body))

# ---- 码位数跟着确认方式走 ----
with _Dir() as base:
    cfg = _cfg()
    cfg["confirm"] = {"code_digits": 4}
    sent, code, _ = _issue(cfg, base, ["甲"])
    check("位数按 confirm.code_digits 取，回四位码才对",
          len(code) == 4 and _ht(cfg, base, "发意向 %s" % code, CTX_OK, Sender(), served=[CHAT]) is not None, code)

# ---- 提示、状态行与结构红线 ----
check("没打开时不提示、状态行为空",
      intake_notify.hints({"intake": {"enabled": True}}, ".") == [] and intake_notify.status_line({}, ".") == "")
with _Dir() as base:
    lines = " ".join(intake_notify.hints(
        {"intake": {"enabled": False, "notify": {"enabled": True, "chat_ids": []}}}, base))
    check("开了提醒但接待桥本体关着、或没主人、或没群号时，自检把原因说清楚",
          "intake_notify" in lines and "接待桥" in lines, lines)
    one = intake_notify.status_line(_cfg(), base)
    check("状态行讲明要本人确认码才发群",
          one.startswith("合作意向提醒：开") and "确认" in one and "不回复就不发" in one, one)

src = open(os.path.join(FW, "intake.py"), encoding="utf-8").read()
check("接待桥本体仍然没有任何发送通路（这条红线不动）",
      "outbound." not in src and "_send" not in src and "sender" not in src, src[:400])
bot = open(os.path.join(FW, "agentbot.py"), encoding="utf-8").read()
start = bot.find("def maintenance_tick")
seg = bot[start:bot.find("\ndef ", start + 1)]
check("自检、演练、诊断在提醒桥之前就返回；它拿到的是发送接口而不是自己造一条",
      "if DRY or CHECK or DOCTOR:" in seg and seg.find("intake_notify.tick") > seg.find("if DRY or CHECK or DOCTOR:")
      and "intake_notify.tick(CFG, BASE, REDACT_NAMES, now, _outbound_send" in seg)
check("接线里确认走的是同一条纪律：命令先登记再分发",
      "intake_notify.handle_text" in bot and "intake_notify.is_command" in bot)

print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
