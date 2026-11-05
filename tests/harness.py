# 测试闸自己的一小块：把「起一个子进程，拿它的输出」这件事单独放这儿，好让「子进程跑太久」
# 这条路径能被单独测。不连飞书，不发消息。
import os
import subprocess

DEFAULT_TIMEOUT = int(os.environ.get("AGENTBOT_TEST_RUN_TIMEOUT", "240"))
TIMEOUT_MARK = "[TIMEOUT]"


def spawn(cmd, env=None, timeout=DEFAULT_TIMEOUT):
    """跑 cmd，把 stdout 和 stderr 连起来返回。
    慢过上限的那条要留一条能读的证据，不能把异常抛出去：抛出去整套测试就没有汇总了。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, timeout=timeout)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        return "%s 这条慢过 %d 秒，子进程已被杀掉；超时前打出来的部分如下，整套测试继续跑完\n%s%s" % (
            TIMEOUT_MARK, timeout, e.stdout or "", e.stderr or "")


def _label(cmd):
    """从命令行里挑一个能认的名字：优先那条事件文件名，其次被跑的脚本。"""
    for part in reversed(list(cmd or [])):
        if isinstance(part, str) and part.endswith(".jsonl"):
            return os.path.basename(part)
    for part in list(cmd or [])[:2]:
        if isinstance(part, str) and part.endswith(".py"):
            return os.path.basename(part)
    return "未命名子进程"


def make_guard(run_impl, results):
    """给整套测试包一层：任何一处带 timeout 的 subprocess.run 慢过了，都不许把异常抛穿——
    抛穿就没有汇总，只能靠 traceback 猜。回一条「非 0 且带标记」的结果，
    让调用方那些 rc==0 的断言自然算失败，并把名字印出来。"""
    def guard(cmd, *args, **kwargs):
        try:
            return run_impl(cmd, *args, **kwargs)
        except subprocess.TimeoutExpired:
            label = "超时：" + _label(cmd)
            results.append((label, False))
            print("FAIL " + label)
            return subprocess.CompletedProcess(cmd, -1, "%s 这条慢过 %s 秒，子进程已被杀掉，整套继续跑完\n"
                                               % (TIMEOUT_MARK, kwargs.get("timeout")), "")
    return guard


def note_timeout(out, label, results):
    """超时那条自己记一条失败。套件里有一大把断言是反着写的（「不该出现某串」），
    子进程压根没跑完时那种断言照样成立，光靠调用方会把白过算成通过。
    顺手把名字印出来：汇总只打「N/M passed」，失败是谁全靠中途那行 FAIL。"""
    if TIMEOUT_MARK in out:
        results.append((label, False))
        print("FAIL " + label)
        return True
    return False
