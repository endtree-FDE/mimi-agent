# checks/verify_deploy.py 的离线用例：只喂临时目录和假进程表，不联网、不起进程、不调 lark-cli。
import json, os, shutil, sys, tempfile, time

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FW)
import utf8io  # noqa: F401
import checks.verify_deploy as vd

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond and detail:
        print(str(detail)[-1500:])


EXAMPLE = json.load(open(os.path.join(FW, "agents", "example.json"), encoding="utf-8-sig"))
NOW = 1793600000.0


def sandbox(overrides=None, heartbeat=None):
    d = tempfile.mkdtemp(prefix="agentbot_vd_")
    os.makedirs(os.path.join(d, "state"))
    os.makedirs(os.path.join(d, "agents"))
    if heartbeat is not None:
        open(os.path.join(d, "state", "heartbeat"), "w", encoding="ascii").write(heartbeat)
    cfg = json.loads(json.dumps(EXAMPLE))
    cfg["base_dir"] = d.replace("\\", "/")
    for key, value in (overrides or {}).items():
        cfg[key] = value
    path = os.path.join(d, "agents", "t.json")
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return d, path, cfg


def procs(base, serving=1, consume=2, bus=1, other=0, profile=None):
    profile = profile if profile is not None else EXAMPLE.get("profile")
    nb = base.replace("\\", "/")
    out = []
    pid = 1000
    for _ in range(serving):
        pid += 1
        out.append({"pid": pid, "cmdline": "python.exe %s/agentbot.py %s/agents/t.json" % (nb, nb)})
    for _ in range(consume):
        pid += 1
        out.append({"pid": pid, "cmdline": "lark-cli.exe event consume im.message.receive_v1 --profile %s --as bot" % profile})
    for _ in range(bus):
        pid += 1
        out.append({"pid": pid, "cmdline": "lark-cli.exe event _bus --profile %s" % profile})
    for _ in range(other):
        pid += 1
        out.append({"pid": pid, "cmdline": "python.exe C:/other/agentbot.py C:/other/agents/x.json"})
    return out


def nb_of(base):
    return base.replace("\\", "/")


d, cp, _ = sandbox(heartbeat=str(int(NOW)))
try:
    got = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("心跳新鲜且拓扑正常时判 PASS", got["status"] == "PASS" and got["fails"] == [], got)
    check("心跳年龄按秒给出", got["heartbeat"]["age_sec"] is not None and got["heartbeat"]["alive"] is True, got["heartbeat"])
    check("进程拓扑分 serving/consume/bus",
          got["topology"]["serving"] == 1 and got["topology"]["consume"] == 2 and got["topology"]["bus"] == 1, got["topology"])
    check("别的实例的 agentbot 只计数不判失败",
          got["topology"]["other_agentbot"] == 0
          and vd.verify(d, cp, with_doctor=False, now=NOW,
                        processes=procs(d, other=2))["topology"]["other_agentbot"] == 2)
    check("配置给出哈希和 profile",
          len(got["config"]["sha256"]) == 64 and got["config"]["profile"] == EXAMPLE.get("profile"), got["config"])
    check("默认例子没有定时输出开着",
          got["config"]["scheduled"] == {"broadcast": False, "digest": False, "report": False}, got["config"]["scheduled"])
    check("知识库在仓库内时 kb_outside_repo 为假", got["config"]["kb_outside_repo"] is False, got["config"])
    check("不是仓库时只提示，不判失败",
          got["git"].get("error") and got["warns"] and got["status"] == "PASS", got)
    diag = vd.verify(d, cp, with_doctor=False, now=NOW, processes=[
        {"pid": 9, "cmdline": "python.exe %s/agentbot.py %s/agents/t.json --doctor" % (nb_of(d), nb_of(d))}])
    check("只读诊断进程不算正在服务", diag["topology"]["serving"] == 0 and diag["status"] == "FAIL", diag["topology"])
finally:
    shutil.rmtree(d, ignore_errors=True)

d, cp, _ = sandbox(heartbeat=str(int(NOW) - 200))
try:
    got = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("心跳超过告警线判 FAIL 并写明年龄",
          got["status"] == "FAIL" and any("心跳年龄" in x for x in got["fails"]), got["fails"])
finally:
    shutil.rmtree(d, ignore_errors=True)

d, cp, _ = sandbox(heartbeat=str(int(NOW)))
try:
    got = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d, serving=2))
    check("同目录两个 agentbot 判 FAIL", got["status"] == "FAIL" and any("应为 1" in x for x in got["fails"]), got["fails"])
    none = vd.verify(d, cp, with_doctor=False, now=NOW, processes=None)
    check("拿不到进程表时不猜拓扑，只提示",
          "topology" not in none and any("列不出进程" in x for x in none["warns"]), none["warns"])
finally:
    shutil.rmtree(d, ignore_errors=True)

d, cp, _ = sandbox(heartbeat=str(int(NOW) - 100), overrides={"alerts": {"enabled": True, "unhealthy_after_sec": 60,
                                                                            "owner_open_ids": ["ou_owner1"]},
                                                           "report": {"enabled": True}})
try:
    got = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("告警线读配置，60 秒没心跳就不算活着",
          got["heartbeat"]["threshold_sec"] == 60.0 and got["heartbeat"]["alive"] is False, got["heartbeat"])
    check("报表开着时定时输出如实标出", got["config"]["scheduled"]["report"] is True, got["config"]["scheduled"])
finally:
    shutil.rmtree(d, ignore_errors=True)

d, cp, _ = sandbox(heartbeat=str(int(NOW)), overrides={"kb_dir": "C:/outside/mumu-kb"})
try:
    got = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("kb_dir 写绝对路径时按原样落在仓外",
          got["config"]["kb_path"] == "C:/outside/mumu-kb" and got["config"]["kb_outside_repo"] is True
          and got["status"] == "PASS", got["config"])
    check("仓外的 kb_dir 不存在时提醒「迁出后忘了改配置」这类错",
          any("目录不存在" in x and "C:/outside/mumu-kb" in x for x in got["warns"]), got["warns"])
finally:
    shutil.rmtree(d, ignore_errors=True)

d, cp, _ = sandbox(heartbeat=str(int(NOW)))
try:
    got = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("没有 kb 目录时报出来，但不改结论",
          got["config"]["kb"]["exists"] is False and got["config"]["kb"]["files"] == 0
          and got["status"] == "PASS" and any("kb_dir" in x for x in got["warns"]), got["warns"])
    os.makedirs(os.path.join(d, "kb"))
    empty = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("kb 目录空着也算问题：检索得到的是零条资料",
          empty["config"]["kb"]["exists"] is True and empty["config"]["kb"]["files"] == 0
          and any("一个能检索的文件都没有" in x for x in empty["warns"]), empty["warns"])
    os.makedirs(os.path.join(d, "kb", "notes"))
    open(os.path.join(d, "kb", "a.md"), "w", encoding="utf-8").write("# 甲\n")
    open(os.path.join(d, "kb", "notes", "b.txt"), "w", encoding="utf-8").write("乙\n")
    open(os.path.join(d, "kb", "skip.docx"), "w", encoding="utf-8").write("不算\n")
    open(os.path.join(d, "kb", ".hidden.md"), "w", encoding="utf-8").write("不算\n")
    filled = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("条数按能检索的后缀算，点开头和不认的类型不算",
          filled["config"]["kb"]["files"] == 2
          and not any("一个能检索的文件都没有" in x for x in filled["warns"]), filled["config"]["kb"])
    import tools as _tb
    open(os.path.join(d, "outside.md"), "w", encoding="utf-8").write("# 仓库外\n")
    try:
        os.symlink(os.path.join(d, "outside.md"), os.path.join(d, "kb", "link.md"))
        _linked = True
    except OSError:
        _linked = False
    _cfg = json.load(open(cp, encoding="utf-8"))
    _brief = _tb.kb_brief(d, _cfg)
    _rows = (_tb.kb_catalog(d, _cfg, []) or "").splitlines()
    check("核对的条数和提示词里那份目录是同一个口径，跳出目录的链接两边都不算",
          _brief["files"] == 2 and len([r for r in _rows if r.startswith("- ")]) == 2
          and ("link.md" not in "\n".join(_rows) if _linked else True), (_brief, _rows))
finally:
    shutil.rmtree(d, ignore_errors=True)

d, cp, _ = sandbox(heartbeat=str(int(NOW)),
                   overrides={"kb_index": {"enabled": False}, "knowledge": {"enabled": False}})
try:
    got = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("检索两条路都关着时，没有 kb 目录是正常配置，不提醒",
          got["config"]["kb"]["exists"] is False and not any("kb_dir" in x for x in got["warns"]), got["warns"])
finally:
    shutil.rmtree(d, ignore_errors=True)

d, cp, _ = sandbox(heartbeat=str(int(NOW)))
try:
    lock_path = os.path.join(d, "state", "deploy.lock")
    got = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("没有 deploy.lock 时不提让路",
          got["deploy_lock"]["present"] is False and got["deploy_lock"]["held"] is False
          and not any("deploy.lock" in x for x in got["warns"]), got["warns"])
    open(lock_path, "w", encoding="utf-8").write("created=%d\nttl=900\n" % (int(NOW) - 60))
    held = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("deploy.lock 还生效时只提示，年龄和窗口一起给出",
          held["deploy_lock"]["held"] is True and held["deploy_lock"]["age_sec"] == 60
          and held["deploy_lock"]["ttl_sec"] == 900 and held["status"] == "PASS"
          and any("看门狗正在让路" in x for x in held["warns"]), held["warns"])
    open(lock_path, "w", encoding="utf-8").write("created=abc\n")
    os.utime(lock_path, (NOW - 120, NOW - 120))
    fallback = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("锁里没读到时间就退回文件时间", fallback["deploy_lock"]["age_sec"] == 120, fallback["deploy_lock"])
    open(lock_path, "w", encoding="utf-8").write("created=%d\nttl=30\n" % (int(NOW) - 3600))
    stale = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("过期的锁不算让路，但提醒还没删",
          stale["deploy_lock"]["held"] is False and any("已过期没删" in x for x in stale["warns"]), stale["warns"])
    check("核对脚本不删锁", os.path.isfile(lock_path))
finally:
    shutil.rmtree(d, ignore_errors=True)

d, cp, _ = sandbox(heartbeat=str(int(NOW)))
try:
    import subprocess

    def _git(*args):
        return subprocess.run(["git", "-C", d, "-c", "user.email=t@example.com", "-c", "user.name=t"]
                              + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace")

    check("临时目录能起一个 git 仓库", _git("init", "-q").returncode == 0
          and _git("add", "-A").returncode == 0 and _git("commit", "-q", "-m", "first").returncode == 0)
    head = (_git("rev-parse", "HEAD").stdout or "").strip()[:7]
    plain = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("HEAD 上没有标注 tag 时只提醒，不判失败",
          plain["git"]["dirty"] == [] and plain["status"] == "PASS"
          and any("没有标注 tag" in x and head in x for x in plain["warns"]), plain["warns"])
    _git("tag", "-a", "-m", "部署标注", "deploy/test-20261102", "HEAD")
    open(os.path.join(d, "本地留着的文件.txt"), "w", encoding="utf-8").write("未跟踪\n")
    tagged = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("有标注 tag 后不再提 tag，改成提醒未提交改动",
          tagged["git"]["tags"] == ["deploy/test-20261102"]
          and not any("没有标注 tag" in x for x in tagged["warns"])
          and any("未提交改动" in x and "本地留着的文件.txt" in x for x in tagged["warns"])
          and tagged["status"] == "PASS", tagged["warns"])
finally:
    shutil.rmtree(d, ignore_errors=True)

d, cp, _ = sandbox(heartbeat=str(int(NOW)))
try:
    open(cp, "w", encoding="utf-8").write("{不是 JSON")
    got = vd.verify(d, cp, with_doctor=False, now=NOW, processes=procs(d))
    check("配置坏了直接判 FAIL", got["status"] == "FAIL" and any("配置读不到" in x for x in got["fails"]), got["fails"])
    check("配置坏时不再去猜进程拓扑", "topology" not in got, got)
finally:
    shutil.rmtree(d, ignore_errors=True)

d, cp, _ = sandbox(heartbeat=str(int(NOW)))
try:
    import contextlib, io

    def _main(args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = vd.main(args)
        return code, buf.getvalue()

    code, out = _main(["--base", os.path.join(d, "nope"), "--no-doctor"])
    check("目录不存在返回 2 并说明原因", code == 2 and "目录不存在" in out, out[-400:])
    shutil.copy(cp, os.path.join(d, "agents", "second.json"))
    code, out = _main(["--base", d, "--no-doctor"])
    check("agents 里有多个 json 又没指定 -c 时返回 2", code == 2 and "用 -c 指定配置" in out, out[-400:])
    os.remove(os.path.join(d, "agents", "second.json"))
    open(os.path.join(d, "state", "heartbeat"), "w", encoding="ascii").write(str(int(time.time())))
    code, out = _main(["--base", d, "--no-doctor"])
    only = json.loads(out)
    check("只有一个 json 时自动选中并给出结论",
          code in (0, 1) and only["config"]["path"].endswith("t.json") and only["heartbeat"]["alive"] is True, out[-400:])
finally:
    shutil.rmtree(d, ignore_errors=True)

print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
