# kb_sync 拉文档：优先 lark-cli.exe，参数是列表。只剩 .cmd 时拒绝命令元字符。
import json, os, shutil, sys, tempfile

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401
import kb_sync
import tools

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(str(detail)[-1500:])


root = tempfile.mkdtemp(prefix="agentbot_lark_")
try:
    exe = os.path.join(root, "npm", "node_modules", "@larksuite", "cli", "bin", "lark-cli.exe")
    cmd = os.path.join(root, "npm", "lark-cli.cmd")
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    os.makedirs(os.path.dirname(cmd), exist_ok=True)
    open(exe, "w", encoding="utf-8").write("")
    open(cmd, "w", encoding="utf-8").write("@echo off\n")
    check("Windows 上 exe 和 cmd 都在时用 exe",
          kb_sync.lark_exe(platform="nt", appdata=root) == [exe])
    os.remove(exe)
    check("没有 exe 时才退回 cmd",
          kb_sync.lark_exe(platform="nt", appdata=root) == [cmd])
    check("不是 Windows 时仍是 PATH 里的 lark-cli",
          kb_sync.lark_exe(platform="posix", appdata=root) == ["lark-cli"])
    check("元字符规则和工具层是同一条",
          tools._CMD_UNSAFE.pattern == r'["&|<>^%!\r\n]')
    blocked = []
    for ch in ['"', "&", "|", "<", ">", "^", "%", "!", "\r", "\n"]:
        argv = kb_sync.lark_fetch_argv("prof_test", "dox" + ch, [cmd])
        blocked.append(kb_sync.lark_argv_rejected(argv))
    check("走 cmd 时每个元字符都拒绝", all(blocked), blocked)
    check("普通文档编号在 cmd 上不拒绝",
          not kb_sync.lark_argv_rejected(kb_sync.lark_fetch_argv("prof_test", "doxTEST", [cmd])))
    bat = os.path.join(root, "npm", "lark-cli.bat")
    check("bat 和 cmd 一样拒绝 &",
          kb_sync.lark_argv_rejected(kb_sync.lark_fetch_argv("prof_test", "dox&x", [bat])))
    fetched = kb_sync.lark_fetch_argv("prof_test", "dox&x", [exe])
    check("直接调 exe 时 & 留在参数列表里，不拒绝",
          not kb_sync.lark_argv_rejected(fetched) and isinstance(fetched, list)
          and fetched[fetched.index("--doc") + 1] == "dox&x")

    calls = []

    def _run(argv, **_kw):
        calls.append(list(argv))
        class _R:
            stdout = json.dumps({"ok": True, "data": {"title": "笔记", "markdown": "hello"}}, ensure_ascii=False)
            stderr = ""
            returncode = 0
        return _R()

    base = tempfile.mkdtemp(prefix="agentbot_pull_")
    try:
        cfg = {"profile": "prof_test", "kb_dir": "kb", "kb_sync": {"docs_tokens": ["dox&bad"]}}
        dst, n = kb_sync.pull_docs(cfg, base, [], run=_run, exe=[cmd], today="20261109")
        report = open(os.path.join(dst, "_REPORT.md"), encoding="utf-8").read()
        check("cmd 遇到危险参数不启动命令，报告不回显这段参数",
              n == 0 and calls == [] and "已拒绝执行" in report and "&" not in report and "dox" not in report, report)
        cfg_ok = {"profile": "prof_test", "kb_dir": "kb", "kb_sync": {"docs_tokens": ["doxOK"]}}
        dst2, n2 = kb_sync.pull_docs(cfg_ok, base, [], run=_run, exe=[exe], today="20261109")
        body = open(os.path.join(dst2, "feishu_docs", "笔记.md"), encoding="utf-8").read()
        check("exe 用参数列表拉取，不经过 shell",
              n2 == 1 and len(calls) == 1 and calls[0][0] == exe and isinstance(calls[0], list)
              and "--doc" in calls[0] and calls[0][calls[0].index("--doc") + 1] == "doxOK"
              and "hello" in body and "shell" not in " ".join(calls[0]), " ".join(calls[0]))
    finally:
        shutil.rmtree(base, ignore_errors=True)
finally:
    shutil.rmtree(root, ignore_errors=True)

failed = [name for name, ok in results if not ok]
print("%d checks, %d failed" % (len(results), len(failed)))
sys.exit(1 if failed else 0)
