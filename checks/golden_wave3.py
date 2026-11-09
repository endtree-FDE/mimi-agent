#!/usr/bin/env python3
# 成熟度金标的自检。只核对用例文件、白名单和评测钩子，不启动机器人，不调模型，不连飞书。
# 整套假模型回归要另跑，见 docs/回归测试.md。日常 CI 走这里，避免每条都拉起回答流程。
import json, os, re, shutil, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "evals"))
import utf8io  # noqa: E402,F401
import history_scan  # noqa: E402
import run as eval_run  # noqa: E402

CASES = os.path.join(ROOT, "evals", "cases", "golden_wave3.json")
SUITE = os.path.join(ROOT, "evals", "cases", "suite.json")
NEED = ("wake", "write-confirm", "write-deny", "tool-fail")
OBS_MID = re.compile(r"^om_obsfixture[A-Za-z0-9]{1,40}$")
BANNED_ID = (
    ("open_id", re.compile(r"ou_[A-Za-z0-9]+")),
    ("union_id", re.compile(r"on_[A-Za-z0-9]+")),
    ("chat_id", re.compile(r"oc_[A-Za-z0-9]+")),
    ("app_id", re.compile(r"cli_[A-Za-z0-9]+")),
)


def fail(msg):
    print(msg)
    return 1


def scan_text(text):
    bad = []
    for kind, pat in history_scan.PATTERNS.items():
        for match in re.finditer(pat, text):
            if kind == "phone":
                phone = re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", match.group(0))
                if not phone:
                    continue
                value = phone.group(1)
            elif kind == "email":
                value = match.group(0)
            else:
                value = match.group(0)
            if history_scan.fixture(kind, value, "evals/cases/golden_wave3.json"):
                continue
            bad.append("%s %s" % (kind, history_scan.mask(value)))
    for kind, rx in BANNED_ID:
        for match in rx.finditer(text):
            bad.append("%s %s" % (kind, history_scan.mask(match.group(0))))
    for match in re.finditer(r"om_[A-Za-z0-9]+", text):
        if not OBS_MID.fullmatch(match.group(0)):
            bad.append("message_id 不在 om_obsfixture 白名单 %s" % history_scan.mask(match.group(0)))
    if "supersecretvalue123" not in text:
        bad.append("用例里应有占位密钥 supersecretvalue123，用来断言它不会出现在回复里")
    return bad


def check_cases(data):
    bad = []
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        return ["没有 cases"]
    seen = set()
    tags = set()
    for case in cases:
        if not isinstance(case, dict):
            bad.append("有一条不是对象")
            continue
        cid = str(case.get("id") or "")
        if not cid or cid in seen:
            bad.append("用例 id 空着或重复 %s" % cid)
        seen.add(cid)
        case_tags = case.get("tags") or []
        if "golden" not in case_tags:
            bad.append("%s 缺少 golden 标签" % cid)
        if "ci" in case_tags:
            bad.append("%s 带了 ci 标签，会进日常评测" % cid)
        tags.update(case_tags)
        turns = case.get("turns") or []
        if not turns:
            bad.append("%s 没有轮次" % cid)
        for turn in turns:
            if not isinstance(turn, dict):
                bad.append("%s 有一轮不是对象" % cid)
                continue
            mid = str(turn.get("message_id") or "")
            if not OBS_MID.fullmatch(mid):
                bad.append("%s 的 message_id 不是 om_obsfixture*" % cid)
        if not case.get("checks"):
            bad.append("%s 没有检查" % cid)
    for name in NEED:
        if name not in tags:
            bad.append("缺少覆盖标签 %s" % name)
    wake = [c for c in cases if isinstance(c, dict) and "wake" in (c.get("tags") or [])]
    if not any(any(t.get("mention") is False for t in (c.get("turns") or []) if isinstance(t, dict)) for c in wake):
        bad.append("唤醒覆盖里没有「不 @」的一轮")
    if not any(not any(t.get("mention") is False for t in (c.get("turns") or []) if isinstance(t, dict)) for c in wake):
        bad.append("唤醒覆盖里没有「@ 之后回答」的一轮")
    blob = json.dumps(data, ensure_ascii=False)
    if "将要执行" not in blob or "不在写入白名单" not in blob:
        bad.append("确认话术或拒绝未授权写的期望不在用例里")
    if "工具不可用：" not in blob or "飞书限流了，请稍后再试" not in blob:
        bad.append("工具失败的友好说法不在用例里")
    return bad


def check_not_in_ci():
    text = open(SUITE, encoding="utf-8-sig").read()
    if "golden_wave3" in text:
        return "suite.json 引用了金标文件，日常 --tag ci 会把它卷进去"
    return ""


def check_hooks():
    ev = eval_run.build_event({"text": "在吗", "mention": False, "chat_type": "group"}, "小助手")
    if ev.get("mentions"):
        return "没 @ 的用例仍带上了 mentions"
    if "@_user_1" in str(ev.get("content") or ""):
        return "没 @ 的用例正文里仍有 @ 占位"
    ev2 = eval_run.build_event({"text": "在吗", "chat_type": "group"}, "小助手")
    mentions = ev2.get("mentions") or []
    if not mentions or mentions[0].get("id") != eval_run.BOT:
        return "默认群聊用例没有 @ 机器人"
    if eval_run.turn_message_id({"message_id": "om_obsfixturehook"}, "case", "t1") != "om_obsfixturehook":
        return "白名单消息编号没有保留"
    leaked = eval_run.turn_message_id({"message_id": "om_" + "abcdef0123456789"}, "case", "t1")
    if leaked.startswith("om_"):
        return "非白名单消息编号被送进了演练"
    src = {"bot_names": ["小助手"], "texts": {"help": "帮助"}, "system_prompt": "x", "write": {"enabled": True}}
    case = {"id": "hook", "setup": {"lark": {"docs +fetch": {"ok": False}}}, "turns": []}
    folder = tempfile.mkdtemp(prefix="golden_hook_")
    try:
        _cfg, _path, _script, _names, lark_stub = eval_run.prepare_case(
            case, src, os.path.join(ROOT, "skills"), folder, [])
        if not lark_stub or not os.path.isfile(lark_stub):
            return "假飞书夹具没有写进沙箱"
        env = eval_run.case_env({}, "fake", "", os.path.join(folder, "fix.json"), folder, lark_stub)
        if env.get("AGENTBOT_FAKE_LARK") != lark_stub:
            return "假飞书夹具没有放进子进程环境"
        if env.get("AGENTBOT_EVAL_NO_LARK") != "1":
            return "金标子进程仍可能去连飞书"
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return ""


def main():
    if not os.path.isfile(CASES):
        return fail("找不到 " + CASES)
    raw = open(CASES, encoding="utf-8-sig").read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return fail("金标 JSON 读不了：" + str(exc))
    problems = scan_text(raw) + check_cases(data)
    ci = check_not_in_ci()
    if ci:
        problems.append(ci)
    hook = check_hooks()
    if hook:
        problems.append(hook)
    if problems:
        print("golden-wave3 self-check 失败")
        for item in problems:
            print("  " + item)
        return 1
    print("golden-wave3 self-check ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
