# 确认超时后的只读队列，以及可选的私聊升级。不连飞书。
import json, logging, os, sqlite3, subprocess, sys, tempfile, time

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401
import doctor, pending_queue
from tools import Tools

results = []
os.environ.pop("AGENTBOT_CARD_CALLBACK", None)
os.environ.pop("AGENTBOT_FAKE_SEND", None)


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(str(detail)[-1500:])


def actor(user="user_admin", chat="chat_group1", mid="msg_src1"):
    return {"user": user, "chat_id": chat, "chat_type": "group", "message_id": mid,
            "scope": "", "question": "建一份文档"}


def make(dry=True, escalate=None, user="user_admin", cards=False):
    base = tempfile.mkdtemp(prefix="pqueue_")
    os.makedirs(os.path.join(base, "state"), exist_ok=True)
    with open(os.path.join(base, "redact.txt"), "w", encoding="utf-8") as handle:
        handle.write("杭州某某科技有限公司\n")
    os.environ["AGENTBOT_CARD_CALLBACK"] = "1" if cards else "0"
    write = {
        "enabled": True,
        "confirm_ttl_sec": 300,
        "allowed_users": {user: "管理员"},
        "resources": {"folder_token": "fldTEST", "docs_append_tokens": ["doxTEST"],
                      "calendar_id": "calTEST", "base_token": "basTEST", "table_id": "tblTEST"},
    }
    if escalate is not None:
        write["escalate"] = escalate
    cfg = {
        "name": "t",
        "profile": "placeholder",
        "redact_file": "redact.txt",
        "tools": {"docs_create": {"enabled": True}},
        "write": write,
        "report": {"enabled": False, "owner_open_ids": []},
        "alerts": {"enabled": False, "owner_open_ids": []},
        "skills": {"enabled": False},
        "memory": {"enabled": False},
        "confirm": {"mode": "code"},
    }
    log = logging.getLogger("pending-queue-test")
    tools = Tools(cfg, base, lambda: ["lark-cli"], log, dry=dry)
    calls = []

    def fake(argv):
        calls.append(list(argv))
        return {"ok": True, "data": {"url": "https://example.com/docx/NEW"}}

    tools.fake = fake
    return tools, calls, base, cfg


def propose(tools, user="user_admin", chat="chat_group1", title="周报"):
    ctx = actor(user=user, chat=chat)
    text = tools.propose_write("docs_create", {
        "title": title,
        "markdown": "api_key=supersecretvalue123",
    }, ctx)
    return text, ctx


def only(tools):
    code, rec = next(iter(tools.pending.items()))
    return code, rec


def expire(tools, code, rec):
    rec["expires"] = time.time() - 5
    tools.pending[code] = rec
    tools._update_pending(code, rec)
    tools._gc()


def blob(base, names):
    snap = pending_queue.view(base, names=names)
    return snap, json.dumps(snap, ensure_ascii=False)


def sent_rows(path):
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


# ---------- 开关默认关，查询不建库 ----------
empty = tempfile.mkdtemp(prefix="pqueue_empty_")
empty_snap = pending_queue.view(empty)
check("没有队列文件时返回空列表，并且不创建 state.db",
      empty_snap == {"readable": True, "pending": [], "expired": []}
      and not os.path.exists(os.path.join(empty, "state", "state.db"))
      and not os.path.exists(pending_queue.expired_path(empty)))
example = json.load(open(os.path.join(FW, "agents", "example.json"), encoding="utf-8-sig"))
check("示例和缺省配置都不打开超时提醒",
      pending_queue.escalate_settings(example)["enabled"] is False
      and pending_queue.escalate_settings({})["enabled"] is False
      and pending_queue.escalate_settings({"write": {"escalate": {"enabled": "true"}}})["enabled"] is False
      and pending_queue.escalate_settings({"write": {"escalate": {"enabled": True, "notify": "none"}}})["who"] == ())
check("写错的 notify 退回主人私聊，群号不进接收人",
      pending_queue.escalate_targets(
          {"write": {"escalate": {"enabled": True, "notify": "group"}},
           "report": {"owner_open_ids": ["ou_owner1", "oc_group1", "REPLACE_OWNER"]}},
          {"user": "oc_chat1", "chat_id": "oc_group1"}) == ["ou_owner1"])

# ---------- 待确认列表：只读，不消耗确认码 ----------
tools, calls, base, cfg = make()
text, ctx = propose(tools, title="杭州某某科技有限公司周报")
code, rec = only(tools)
snap, text_blob = blob(base, tools.names)
check("pending 列表有这一条，且没有确认码、编号、参数和客户名",
      len(snap["pending"]) == 1 and snap["pending"][0]["status"] == "pending"
      and snap["pending"][0]["tool"] == "docs_create" and snap["pending"][0]["dual"] is False
      and snap["pending"][0]["left_sec"] > 0
      and code not in text_blob and rec["token"] not in text_blob
      and "user_admin" not in text_blob and "chat_group1" not in text_blob
      and "api_key" not in text_blob and "supersecretvalue123" not in text_blob
      and "杭州某某科技有限公司" not in text_blob and "某客户" in text_blob
      and "code_hash" not in text_blob and code in tools.pending, text_blob)
done = tools.confirm(code, actor(mid="msg_ok1"))
check("查过列表之后，发起人仍要自己确认才会执行",
      done.startswith("已完成") and len(calls) == 1 and code not in tools.pending, done)

# ---------- 超时：作废、可查询、不执行 ----------
tools, calls, base, cfg = make()
propose(tools, title="超时这份")
code, rec = only(tools)
expire(tools, code, rec)
snap, text_blob = blob(base, tools.names)
late = tools.confirm(code, actor(mid="msg_late"))
check("超时后 pending 里没有它，expired 可查，确认码不能再执行",
      code not in tools.pending and snap["pending"] == [] and len(snap["expired"]) == 1
      and snap["expired"][0]["status"] == "expired" and snap["expired"][0]["tool"] == "docs_create"
      and snap["expired"][0]["notify"] == "off" and snap["expired"][0]["left_sec"] == 0
      and "无效或已过期" in late and not calls
      and code not in text_blob and rec["token"] not in text_blob
      and "user_admin" not in text_blob and "chat_group1" not in text_blob, late + "\n" + text_blob)

# 重启再扫到同一条过期记录时，不重复记、也不执行。
tools2 = Tools(cfg, base, lambda: ["lark-cli"], logging.getLogger("pending-queue-test"), dry=True)
again = pending_queue.view(base, names=tools.names)
check("重启不会把同一次超时再记一条，确认码仍然无效",
      code not in tools2.pending and len(again["expired"]) == 1
      and "无效或已过期" in tools2.confirm(code, actor(mid="msg_late2")))

# ---------- 提醒：默认不发；开了也只走私聊 ----------
sink = os.path.join(base, "sent.jsonl")
os.environ["AGENTBOT_FAKE_SEND"] = sink
try:
    quiet, quiet_calls, quiet_base, _quiet_cfg = make(dry=False)
    propose(quiet, chat="oc_groupchat9")
    qcode, qrec = only(quiet)
    expire(quiet, qcode, qrec)
    qsnap, _qblob = blob(quiet_base, quiet.names)
    check("没开 escalate 时不发私聊，状态仍是 off",
          qsnap["expired"][0]["notify"] == "off" and sent_rows(sink) == [] and not quiet_calls)

    owners, _calls, owner_base, _cfg = make(
        dry=False,
        escalate={"enabled": True, "notify": "owner"},
        user="ou_init9")
    owners.cfg["report"]["owner_open_ids"] = ["ou_owner1"]
    owners.cfg["alerts"]["owner_open_ids"] = ["oc_should_not_send"]
    propose(owners, user="ou_init9", chat="oc_groupchat9", title="提醒这份")
    ocode, orec = only(owners)
    expire(owners, ocode, orec)
    rows = sent_rows(sink)
    joined = json.dumps(rows, ensure_ascii=False)
    check("打开后只私聊主人，不发给群，正文里没有确认码",
          len(rows) == 1 and rows[0]["kind"] == "user" and rows[0]["target"] == "ou_owner1"
          and rows[0]["via"] == "messages-send"
          and ocode not in joined and "oc_groupchat9" not in joined and "oc_should_not_send" not in joined
          and "expired" in rows[0]["text"] and pending_queue.view(owner_base)["expired"][0]["notify"] == "sent",
          joined)

    open(sink, "w", encoding="utf-8").write("")
    both, _calls, both_base, _cfg = make(
        dry=False,
        escalate={"enabled": True, "notify": "both"},
        user="ou_init9")
    both.cfg["report"]["owner_open_ids"] = ["ou_owner1"]
    propose(both, user="ou_init9", chat="oc_groupchat9")
    bcode, brec = only(both)
    expire(both, bcode, brec)
    targets = sorted(row["target"] for row in sent_rows(sink))
    kinds = {row["kind"] for row in sent_rows(sink)}
    check("both 私聊主人和发起人各一条，仍然不发群",
          targets == ["ou_init9", "ou_owner1"] and kinds == {"user"}
          and pending_queue.view(both_base)["expired"][0]["notify"] == "sent", targets)

    open(sink, "w", encoding="utf-8").write("")
    none, _calls, none_base, _cfg = make(dry=False, escalate={"enabled": True, "notify": "owner"})
    propose(none, chat="oc_groupchat9")
    ncode, nrec = only(none)
    expire(none, ncode, nrec)
    check("没有私聊对象时不发群，状态记 no_route",
          sent_rows(sink) == [] and pending_queue.view(none_base)["expired"][0]["notify"] == "no_route")

    open(sink, "w", encoding="utf-8").write("")
    dry, _calls, dry_base, _cfg = make(dry=True, escalate={"enabled": True, "notify": "initiator"}, user="ou_init9")
    propose(dry, user="ou_init9", chat="oc_groupchat9")
    dcode, drec = only(dry)
    expire(dry, dcode, drec)
    check("演练不外发，状态记 dry",
          sent_rows(sink) == [] and pending_queue.view(dry_base)["expired"][0]["notify"] == "dry")
finally:
    os.environ.pop("AGENTBOT_FAKE_SEND", None)

# ---------- 文件上限、手工投毒、doctor、本地脚本 ----------
cap_base = tempfile.mkdtemp(prefix="pqueue_cap_")
for i in range(105):
    pending_queue.note_expired(cap_base, "%06d" % i, {"tool": "docs_create", "ts": i, "summary": "s"}, "off")
kept = pending_queue._load_file(cap_base)
check("过期文件只留最近 100 条，重复记一次不会再加",
      len(kept) == 100 and kept[0]["code_hash"] == pending_queue._code_hash("000005")
      and pending_queue.note_expired(cap_base, "000050", {"tool": "docs_create"}, "off") is False
      and len(pending_queue._load_file(cap_base)) == 100)

poison = tempfile.mkdtemp(prefix="pqueue_poison_")
os.makedirs(os.path.join(poison, "state"), exist_ok=True)
with open(pending_queue.expired_path(poison), "w", encoding="utf-8") as handle:
    handle.write(json.dumps({
        "status": "expired", "tool": "docs_create", "user": "ou_initiator9", "chat_id": "oc_groupchat9",
        "user_hash": "ou_initiator9", "token": "tokensecretvalue", "code_hash": "deadbeefcafe",
        "summary": "里面夹了 ou_initiator9", "notify": "off", "argv": ["api_key=supersecretvalue123"],
    }, ensure_ascii=False) + "\n")
psnap, pblob = blob(poison, ["杭州某某科技有限公司"])
check("状态文件被加了编号和参数时，读出来仍丢掉",
      psnap["expired"][0]["user_hash"] == "" and "ou_initiator9" not in pblob
      and "oc_groupchat9" not in pblob and "tokensecretvalue" not in pblob
      and "api_key" not in pblob and "code_hash" not in pblob and "argv" not in pblob, pblob)

tools, calls, base, cfg = make()
propose(tools)
level, name, info = pending_queue.doctor_line(base, tools.names)
check("doctor 一行能看到待确认条数，不含确认码",
      level == "OK" and name == "pending" and "待确认 1" in info and "docs_create" in info
      and only(tools)[0] not in info and "user_admin" not in info, info)


def run_doc(argv):
    if "consume" in argv or "send" in argv or "reply" in argv:
        return 1, "", "refused"
    if argv[1:2] == ["--version"] or (len(argv) > 1 and argv[1] == "--version"):
        return 0, "lark-cli test\n", ""
    if "show" in argv:
        return 0, "profile ok\n", ""
    if "status" in argv:
        return 0, json.dumps({"identities": {"bot": {"available": True, "status": "ready"}}}) + "\n", ""
    if "scopes" in argv:
        return 0, json.dumps({"scopes": ["im:message.group_at_msg:readonly", "im:message:send_as_bot"]}) + "\n", ""
    return 1, "", "unexpected"


doc_cfg = {"name": "t", "profile": "placeholder", "features": {"attachments": False},
           "progress": {"enabled": False}, "confirm": {"mode": "code"}, "write": {"enabled": True}}
lines, doc_code = doctor.report(doc_cfg, base, ["lark-cli"], run_doc, lambda: [],
                                lambda host: [("1.2.3.4", 443)], lambda host, port: True, {}, {})
doc_text = "\n".join(lines)
check("doctor 报告带 pending 行，且不因此失败、不发消息",
      doc_code == 0 and "OK   pending" in doc_text and "待确认 1" in doc_text and "FAIL" not in doc_text, doc_text)

cli = subprocess.run([sys.executable, os.path.join(FW, "pending_queue.py"), base],
                     capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
cli_out = cli.stdout or ""
check("本地脚本打出同一份只读 JSON",
      cli.returncode == 0 and '"status": "pending"' in cli_out and "user_admin" not in cli_out
      and only(tools)[0] not in cli_out, cli_out[-500:])
bad = subprocess.run([sys.executable, os.path.join(FW, "pending_queue.py")],
                     capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
check("本地脚本缺参数时退出码 2", bad.returncode == 2 and "用法" in (bad.stderr or ""))

# 库里的过期行还没扫掉时，只读视图把它标成 expired，但不删库。
stale_base = tempfile.mkdtemp(prefix="pqueue_stale_")
os.makedirs(os.path.join(stale_base, "state"), exist_ok=True)
conn = sqlite3.connect(os.path.join(stale_base, "state", "state.db"))
conn.execute("create table pending_writes(code text primary key, ts real, payload text)")
old = {"tool": "docs_create", "summary": "还在库里", "user": "ou_initiator9", "chat_id": "oc_groupchat9",
       "token": "tokensecretvalue", "ts": time.time() - 1000, "expires": time.time() - 10, "mode": "code"}
conn.execute("insert into pending_writes(code, ts, payload) values(?,?,?)",
             ("111111", old["ts"], json.dumps(old, ensure_ascii=False)))
conn.commit()
conn.close()
before = os.path.getsize(os.path.join(stale_base, "state", "state.db"))
ssnap, sblob = blob(stale_base, [])
after = os.path.getsize(os.path.join(stale_base, "state", "state.db"))
check("只读视图把库里已超时的行标成 expired，不改数据库",
      ssnap["pending"] == [] and len(ssnap["expired"]) == 1 and ssnap["expired"][0]["status"] == "expired"
      and "111111" not in sblob and "ou_initiator9" not in sblob and "oc_groupchat9" not in sblob
      and "tokensecretvalue" not in sblob and before == after and not os.path.exists(pending_queue.expired_path(stale_base)),
      sblob)

os.environ.pop("AGENTBOT_CARD_CALLBACK", None)
failed = [name for name, ok in results if not ok]
print("%d passed, %d failed" % (len(results) - len(failed), len(failed)))
sys.exit(1 if failed else 0)
