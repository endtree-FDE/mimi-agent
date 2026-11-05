# 测试闸的闸：任何一条 subprocess 慢过上限时，整套测试还得跑完并打出汇总。
# 起因是 2026-11-05 那一趟 cp936 跑了 39 分钟后在 tests/run_tests.py:37 抛了未捕获的
# subprocess.TimeoutExpired，整串中止、连「N/N passed」都没打出来——机器被拖慢的时候，
# 闸自己先碎了，读数就成了「不知道」。这一份只起本地假进程，不连飞书，不发消息。
import contextlib
import io
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
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    hit = harness.note_timeout("前面有点东西\n[TIMEOUT] 这条慢过 240 秒", "dedup", _bucket)
check("带超时标记的输出要自己记一条失败",
      hit is True and _bucket == [("dedup", False)], repr(_bucket))
# 印是印了，但要印进调用方给的这块缓冲里：这一趟本身是被 tests/run_tests.py 当子进程跑的，
# 它往自己 stdout 印「FAIL dedup」，那行就直接混进整套日志（2026-11-05 数过：rt18 混 1 行、
# rt20 混 2 行，可那两趟都报 472/472 passed 并退 0）。整套日志里的 FAIL 只能是真失败。
check("超时记失败时印的那行要落在外面兜住的那块缓冲里，而不是漏进本趟的 stdout",
      _buf.getvalue().strip() == "FAIL dedup", repr(_buf.getvalue()))
_bucket2 = []
_buf2 = io.StringIO()
with contextlib.redirect_stdout(_buf2):
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

# 七、整套里还有五十来处 subprocess.run 直接带 timeout，每一处都能把汇总带走（15:03 的
# UTF-8 那趟就是在 tests/run_tests.py:1148 的 run_oa 上抛穿的，那条我没改到）。所以要一层
# 谁都能用的守卫：超时不许抛，回一条「不是 0」的结果，名字照样印出来、照样记进 results。
def _impl_raises(cmd, *a, **kw):
    raise subprocess.TimeoutExpired(cmd, kw.get("timeout") or 90)


_bucket3 = []
_guard = harness.make_guard(_impl_raises, _bucket3)
_raised = None
_res = None
_buf3 = io.StringIO()
try:
    with contextlib.redirect_stdout(_buf3):
        _res = _guard([sys.executable, os.path.join(FW, "agentbot.py"), "x.json", "--dry-run", "y.jsonl"])
except Exception as exc:  # noqa: BLE001
    _raised = exc
check("守卫要把任何一处 subprocess.run 的超时接住，不许抛给整套测试",
      _raised is None and _res is not None, "抛出了 %r" % (_raised,))
check("超时那条要回一个非 0 的退出码，否则 rc==0 的断言会把它算成通过",
      _raised is None and getattr(_res, "returncode", 0) != 0, repr(_res))
check("超时那条的输出里要带标记，方便看日志的人知道这条是没跑完而不是跑歪了",
      _raised is None and harness.TIMEOUT_MARK in (_res.stdout or ""), repr(_res))
# 同上：这一行名字照样印得出（上面第 5 条跨进程验的就是它），但兜在缓冲里，别漏进整套日志。
check("守卫印的那行 FAIL 也要落在外面兜住的那块缓冲里",
      _buf3.getvalue().strip() == "FAIL 超时：y.jsonl", repr(_buf3.getvalue()))

# 八、不超时的那条路要原样把结果交回去：这一层不许改变任何现有断言看到的对象形状。
_ok = subprocess.CompletedProcess(["x"], 0, stdout="real-out", stderr="")
_bucket4 = []
_res2 = harness.make_guard(lambda cmd, *a, **kw: _ok, _bucket4)(["x"])
check("没超时的要原样拿到那个结果，且不多记一条失败",
      _res2 is _ok and _bucket4 == [], repr(_res2))

# 九、整套里还有一处不走 subprocess.run，是自己 Popen 完再 p.wait(timeout=30)
# （tests/run_tests.py 的「两个进程同时记跟踪」那条）。守卫那层包不到它：机器慢过那 30 秒，
# 照样是一个没人接的 TimeoutExpired，traceback 一穿，汇总就又没了——和这次要修的原始毛病同一个。
_wk_err = None
_wk_codes = None
_wk_bucket = []
_buf4 = io.StringIO()
_wk_procs = []
try:
    _wk_procs = [subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
                 for _ in (1, 2)]
    with contextlib.redirect_stdout(_buf4):
        _wk_codes = harness.wait_all(_wk_procs, 3, _wk_bucket, "超时：trace_parts")
except Exception as exc:  # noqa: BLE001
    _wk_err = exc
for _p_ in _wk_procs:  # 兜一层，别让假进程留在机器上
    try:
        _p_.kill()
    except OSError:
        pass
check("等一批子进程也要有一条不许抛穿的路，且慢过的那几条都算非 0",
      _wk_err is None and _wk_codes == [-1, -1],
      "抛出了 %r；拿到的退出码 %r" % (_wk_err, _wk_codes))
check("那一批慢过了要记一条失败，名字照旧印得出、但兜在缓冲里",
      _wk_err is None and _wk_bucket == [("超时：trace_parts", False)]
      and _buf4.getvalue().strip() == "FAIL 超时：trace_parts",
      "记了 %r，缓冲里是 %r" % (_wk_bucket, _buf4.getvalue()))

# 十、快的那一批要原样拿到真实退出码：上面两条只验了「挂住」这一边，如果这条函数改成
# 无论怎样都交回 -1，那两条照样绿，而整套里那句「退出码都是 0」就永远是红的——
# 一个只会喊失败的闸和不会用的闸是同一种东西。
_wk_fast = [subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(%d)" % n]) for n in (0, 3)]
_wk_fast_codes = harness.wait_all(_wk_fast, 60, [], "超时：不该出现")
check("没慢过的那一批要原样交回真实退出码，且不多记一条失败",
      _wk_fast_codes == [0, 3], repr(_wk_fast_codes))

print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
