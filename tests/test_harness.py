# 测试闸的闸：任何一条 subprocess 慢过上限时，整套测试还得跑完并打出汇总。
# 起因是 2026-11-05 那一趟 cp936 跑了 39 分钟后在 tests/run_tests.py:37 抛了未捕获的
# subprocess.TimeoutExpired，整串中止、连「N/N passed」都没打出来——机器被拖慢的时候，
# 闸自己先碎了，读数就成了「不知道」。这一份只起本地假进程，不连飞书，不发消息。
import os
import subprocess
import sys

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
sys.path.insert(0, os.path.join(FW, "tests"))
import utf8io  # noqa: F401  管道改为 UTF-8，不依赖 PYTHONUTF8
import harness

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(detail[-1500:])


def py(code):
    return [sys.executable, "-c", code]


# 一、慢过上限：不许抛出来（抛出来就是整串测试没有汇总），要回一条带标记的输出。
raised = None
out = ""
try:
    out = harness.spawn(py("print('PARTIAL', flush=True); import time; time.sleep(30)"),
                        timeout=2)
except subprocess.TimeoutExpired as exc:
    raised = exc
check("单条 subprocess 超时要回一条带标记的输出，而不是把异常抛给整套测试",
      raised is None and harness.TIMEOUT_MARK in out,
      "抛出了 %s；返回的是 %r" % (type(raised).__name__ if raised else "无", out))
check("超时之前已经打出来的那部分要留住，否则看不出卡在哪儿",
      raised is None and "PARTIAL" in out, repr(out))

# 二、正常那条路不能被这次改动弄坏：快的进程照原样拿到它的输出，也不许带超时标记。
fast = harness.spawn(py("print('hello-out'); import sys; print('err-line', file=sys.stderr)"),
                     timeout=60)
check("没超时的进程照旧拿到 stdout 加 stderr",
      "hello-out" in fast and "err-line" in fast and harness.TIMEOUT_MARK not in fast, repr(fast))

# 三、超时那条不许只靠调用方的断言算数：跑套件时有一大把是「不该出现某串」这种反着写的，
# 子进程压根没跑，那种断言照样成立，就白过了。所以超时要自己记一条失败。
_bucket = []
hit = harness.note_timeout("前面有点东西\n[TIMEOUT] 这条慢过 240 秒", "dedup", _bucket)
check("带超时标记的输出要自己记一条失败",
      hit is True and _bucket == [("dedup", False)], repr(_bucket))
_bucket2 = []
miss = harness.note_timeout("普通输出，没有标记", "dedup", _bucket2)
check("没超时的不许记失败，否则正常的用例会被多算一条",
      miss is False and _bucket2 == [], repr(_bucket2))

# 五、记的那条失败要在输出里看得见名字。整套汇总最后只打「N/M passed」，失败是谁全靠
# 中途那行 FAIL；只往 results 里塞一条而不印出来，日志上就成了「多出来的那些失败不知道是哪条」，
# 等于把人推回去猜——和这次要修的原始毛病是同一类。
_p = subprocess.run([sys.executable, "-c",
                     "import sys, os; sys.path.insert(0, os.path.join(%r, 'tests')); "
                     "import harness; "
                     "harness.note_timeout('x\\n[TIMEOUT] 这条慢过 240 秒', 'dedup', [])" % FW],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
check("超时记的失败要把用例名印出来，不能只进汇总的数",
      "FAIL" in _p.stdout and "dedup" in _p.stdout, repr(_p.stdout) + repr(_p.stderr))

# 六、超时的上限要能被读出来：调用方不看签名就不知道这条到底几秒算慢。
check("上限从环境或默认里来，且默认就是原来那个 240 秒",
      harness.DEFAULT_TIMEOUT == 240, repr(harness.DEFAULT_TIMEOUT))

print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
