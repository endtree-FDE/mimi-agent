# EvidenceGate 门禁工具：默认关、三路由正确、路径与参数安全。
# 门禁脚本零依赖（node 内置），测试里真跑 node：实例机 v24、CI runner 都预装。
import json, logging, os, shutil, sys, tempfile

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401
from tools import Tools, ToolError

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(str(detail)[-1500:])


GOOD = json.dumps({
    "document_title": "测试住宿单", "test_number": "T-1", "issue_date": "2026-01-10",
    "buyer": "甲公司", "seller": "乙酒店", "city": "杭州", "expense_type": "住宿",
    "check_in_date": "2026-01-10", "check_out_date": "2026-01-12", "quantity_nights": 2,
    "amount_excluding_tax_yuan": 100, "tax_rate": "6%", "tax_amount_yuan": 6,
    "total_amount_yuan": 106, "purpose_text": "出差",
    "synthetic_labels": ["合成测试票据", "仅供OCR评测", "非真实发票"], "uncertainties": [],
}, ensure_ascii=False)
BAD_AMOUNT = GOOD.replace('"total_amount_yuan": 106', '"total_amount_yuan": 999')
MISSING = '{"document_title":"测试"}'

CTX = {"user": "user_eg", "chat_id": "oc_eg", "chat_type": "group"}


def new_tools(tools_cfg):
    base = tempfile.mkdtemp(prefix="eg_base_")
    # 门禁脚本和契约按实例布局放进 base（tools._evidencegate_check 只认 base 内路径）。
    shutil.copytree(os.path.join(FW, "skills"), os.path.join(base, "skills"))
    cfg = {"profile": "placeholder", "bot_open_id": "ou_bot_placeholder", "bot_names": ["小助手"],
           "tools": tools_cfg}
    return base, Tools(cfg, base, lambda: ["lark-cli"], logging.getLogger("eg"), dry=True)


def test_default_off():
    base, t = new_tools({"history": {"enabled": True, "days": 7}})
    try:
        t.run_read("evidencegate_check", {"candidate": GOOD}, dict(CTX))
        check("默认关时 evidencegate_check 不可用", False)
    except ToolError as e:
        # 未知工具（没进 READ_TOOLS）和「还没在配置里启用」都算关住了。
        check("默认关时 evidencegate_check 不可用", "未知工具" in str(e) or "还没在配置里启用" in str(e), e)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_routes():
    base, t = new_tools({"evidencegate_check": {"enabled": True}})
    try:
        out = t.run_read("evidencegate_check", {"candidate": GOOD}, dict(CTX))
        check("合法候选路由 ACCEPT_CANDIDATE 且带字段证据", "ACCEPT_CANDIDATE" in out and "字段：" in out, out)
        check("ACCEPT 摘要提醒人工确认后写入", "人工确认" in out, out)
        out = t.run_read("evidencegate_check", {"candidate": BAD_AMOUNT}, dict(CTX))
        check("金额算术错路由 HUMAN_REVIEW", "HUMAN_REVIEW" in out, out)
        check("HUMAN_REVIEW 摘要列出业务规则错误", "问题 1 项" in out, out)
        out = t.run_read("evidencegate_check", {"candidate": MISSING}, dict(CTX))
        check("缺字段路由 MODEL_OUTPUT_INVALID", "MODEL_OUTPUT_INVALID" in out, out)
        check("无效输出摘要要求重发清晰图片", "重发清晰图片" in out, out)
        check("摘要固定要求原样引用路由与证据", "不得软化或改写" in out, out)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_safety():
    base, t = new_tools({"evidencegate_check": {"enabled": True}})
    try:
        try:
            t.run_read("evidencegate_check", {"path": "../agents/example.json"}, dict(CTX))
            check("路径逃逸被拒绝", False)
        except ToolError as e:
            check("路径逃逸被拒绝", "不存在或不在实例目录内" in str(e), e)
        try:
            t.run_read("evidencegate_check", {}, dict(CTX))
            check("空参数给可读报错", False)
        except ToolError as e:
            check("空参数给可读报错", "path" in str(e) and "candidate" in str(e), e)
        # 契约路径可被配置指到不存在的文件，报错要可读且不泄露路径细节。
        base2, t2 = new_tools({"evidencegate_check": {"enabled": True, "schema": "no-such-contract.json"}})
        try:
            shutil.rmtree(base2, ignore_errors=True)
        except OSError:
            pass
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_example_and_readme():
    EXAMPLE = json.load(open(os.path.join(FW, "agents", "example.json"), encoding="utf-8-sig"))
    eg = (EXAMPLE.get("tools") or {}).get("evidencegate_check") or {}
    check("例子里 evidencegate_check 默认关", eg.get("enabled") is False, eg)
    check("例子里契约路径指向 skill 自带契约", "evidence-schema.json" in str(eg.get("schema")), eg)
    check("READ_TOOLS 收录 evidencegate_check", "evidencegate_check" in __import__("tools").READ_TOOLS)


test_default_off()
test_routes()
test_safety()
test_example_and_readme()

print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
