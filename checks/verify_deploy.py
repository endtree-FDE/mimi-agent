#!/usr/bin/env python3
# 升级或回滚之后跑这一条命令，拿到机器可读的部署结论。
# 全程只读：不发消息、不写心跳、不启动也不结束任何进程；诊断复用 doctor 的只读接口。
# 用法: python checks/verify_deploy.py --base C:/Users/x/mumu-agent-v3 [-c agents/mumu.json] [--no-doctor]
# 退出码：0 结论 PASS；1 结论 FAIL；2 参数或目录不对。
import argparse, hashlib, json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "checks")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import utf8io  # noqa: F401  控制台输出统一 UTF-8
import proc_identity as pi


_AUTO = object()


def run_git(base, args):
    try:
        got = subprocess.run(["git", "-C", base] + list(args), capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if got.returncode != 0:
        return None
    return (got.stdout or b"").decode("utf-8", "replace").strip()


def git_info(base):
    head = run_git(base, ["rev-parse", "HEAD"])
    info = {"head": head, "branch": run_git(base, ["rev-parse", "--abbrev-ref", "HEAD"]),
            "subject": None, "dirty": [], "tags": []}
    if not head:
        info["error"] = "git 不可用，或者这个目录不是仓库"
        return info
    info["subject"] = run_git(base, ["log", "-1", "--format=%s"])
    porcelain = run_git(base, ["-c", "core.quotePath=false", "status", "--porcelain"]) or ""
    info["dirty"] = [line for line in porcelain.splitlines() if line.strip()]
    info["tags"] = [t for t in (run_git(base, ["tag", "--points-at", "HEAD"]) or "").splitlines() if t]
    return info


def heartbeat_info(base, now, threshold):
    path = os.path.join(base, "state", "heartbeat")
    out = {"path": path.replace("\\", "/"), "threshold_sec": threshold, "ts": None,
           "age_sec": None, "alive": False, "missing": True}
    try:
        out["ts"] = int((open(path, encoding="utf-8").read() or "").strip())
    except (OSError, ValueError):
        return out
    out["missing"] = False
    out["age_sec"] = int(now - out["ts"])
    out["alive"] = out["age_sec"] < threshold
    return out


def deploy_lock_info(base, now):
    """升级或回滚期间看门狗靠 state/deploy.lock 让路。这里的读法和 scripts/botproc.ps1 的 Get-DeployLock 一致，
    核对脚本只报告，不删锁也不改锁。"""
    path = os.path.join(base, "state", "deploy.lock")
    out = {"path": path.replace("\\", "/"), "present": False, "held": False,
           "age_sec": None, "ttl_sec": None}
    if not os.path.isfile(path):
        return out
    out["present"] = True
    stamp, ttl = None, 900
    try:
        for line in open(path, encoding="utf-8", errors="replace").read().splitlines():
            text = line.strip().lstrip("﻿").strip()
            if stamp is None and re.fullmatch(r"(?:created=)?(\d+)", text, re.IGNORECASE):
                stamp = int(text.rsplit("=", 1)[-1]) if "=" in text else int(text)
            elif re.fullmatch(r"ttl=(\d+)", text, re.IGNORECASE):
                ttl = int(text.split("=", 1)[1])
        if stamp is None:
            stamp = int(os.path.getmtime(path))
    except OSError as exc:
        out["error"] = "锁文件读不到：%s" % exc
        return out
    out["ttl_sec"] = max(1, ttl)
    out["age_sec"] = max(0, int(now - stamp))
    out["held"] = out["age_sec"] < out["ttl_sec"]
    return out


def load_config(path):
    try:
        raw = open(path, "rb").read()
    except OSError as exc:
        return None, {"path": path.replace("\\", "/"), "error": str(exc)}
    info = {"path": path.replace("\\", "/"), "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "profile": None, "kb_dir": "kb", "kb_path": None,
            "kb_outside_repo": None, "scheduled": {}, "chat_ids": 0, "p2p_allow": 0,
            "alerts_enabled": None}
    try:
        cfg = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        info["error"] = "不是合法 JSON：%s" % exc
        return None, info
    info["profile"] = cfg.get("profile")
    kb_dir = cfg.get("kb_dir") or "kb"
    info["kb_dir"] = kb_dir
    return cfg, info


def scheduled_info(cfg):
    """定时发送由各自模块判定，避免这里和配置语义走偏。"""
    out = {}
    try:
        import broadcast
        out["broadcast"] = bool(broadcast.enabled(cfg))
    except Exception as exc:
        out["broadcast"] = "读取失败：%s" % exc
    try:
        import digest
        out["digest"] = bool(digest.enabled(cfg))
    except Exception as exc:
        out["digest"] = "读取失败：%s" % exc
    try:
        import usage
        out["report"] = bool(usage.enabled(cfg))
    except Exception as exc:
        out["report"] = "读取失败：%s" % exc
    return out


def topology(processes, base, profile):
    """进程归属沿用 verify_report 的判定，不在这里再写一套匹配规则。
    带 --doctor/--check/--dry-run 的进程不算在服务里。"""
    import verify_report as vr
    nbase, nprof = pi.norm_path(base), pi.norm_path(profile)
    serving, consume, bus, other = [], [], [], []
    for proc in processes or []:
        cmd = proc.get("cmdline") or ""
        pid = proc.get("pid")
        if vr.is_serving_agent(cmd):
            directory = pi.norm_path(vr.script_dir(cmd) or (proc.get("cwd") or ""))
            (serving if directory == nbase else other).append(pid)
            continue
        event = vr.consume_event(cmd)
        same_profile = bool(nprof) and pi.norm_path(vr.profile_of(cmd)) == nprof
        if event and same_profile:
            consume.append(pid)
        elif "event _bus" in cmd.lower() and same_profile:
            bus.append(pid)
    return {"serving": len(serving), "consume": len(consume), "bus": len(bus),
            "serving_pids": serving, "consume_pids": consume, "bus_pids": bus,
            "other_agentbot": len(other)}


def current_processes():
    import doctor
    return doctor.default_processes()


def lark_exe():
    if os.name == "nt":
        npm = os.path.join(os.environ.get("APPDATA", ""), "npm")
        exe = os.path.join(npm, "node_modules", "@larksuite", "cli", "bin", "lark-cli.exe")
        return [exe] if os.path.isfile(exe) else [os.path.join(npm, "lark-cli.cmd")]
    return ["lark-cli"]


def doctor_rows(cfg, base, procs):
    """doctor 返回的是给人看的行，这里拆成 level/name/info，机器读起来不用再猜格式。
    进程表用外面已经取到的那一份，避免同一次核对里重复启动 powershell 取到不一致结果。"""
    import doctor
    lines, code = doctor.report(cfg, base, lark_exe(), doctor.default_run, lambda: procs,
                                doctor.default_resolve, doctor.default_connect, doctor.default_modules(), None)
    rows = []
    for line in lines:
        parts = (line or "").split(None, 2)
        rows.append({"level": parts[0] if parts else "", "name": parts[1] if len(parts) > 1 else "",
                     "info": parts[2] if len(parts) > 2 else ""})
    return rows, code


def config_schema_problems(path):
    import check_config
    errors, hints = check_config.check_file(path, check_config.load_schema())
    return list(errors), list(hints)


def verify(base, config_path, with_doctor=True, now=None, processes=_AUTO):
    now = time.time() if now is None else float(now)
    base = os.path.abspath(base)
    result = {"base": base.replace("\\", "/"), "checked_at": int(now),
              "git": git_info(base), "status": "PASS", "fails": [], "warns": []}
    if result["git"].get("error"):
        result["warns"].append("读不到 git 版本：%s" % result["git"]["error"])
    else:
        # 这两条只提醒，不判失败：线上目录常留着本地想保留的文件（未跟踪、故意删掉的占位），
        # 但「HEAD 上没有部署标注 tag」和「工作区不干净」会直接影响能不能说清跑的是哪版。
        dirty = result["git"].get("dirty") or []
        if dirty:
            result["warns"].append("工作区有 %d 处未提交改动：%s（核对以 HEAD %s 为准）"
                                   % (len(dirty), "、".join(dirty[:2]), (result["git"].get("head") or "")[:7]))
        if not result["git"].get("tags"):
            result["warns"].append("HEAD %s 上没有标注 tag，说不清这台机器跑的是哪次部署"
                                   % (result["git"].get("head") or "?")[:7])
    lock = deploy_lock_info(base, now)
    result["deploy_lock"] = lock
    if lock.get("error"):
        result["warns"].append("deploy.lock：%s" % lock["error"])
    elif lock["held"]:
        result["warns"].append("deploy.lock 还在（年龄 %ss / ttl %ss），看门狗正在让路"
                               % (lock["age_sec"], lock["ttl_sec"]))
    elif lock["present"]:
        result["warns"].append("deploy.lock 已过期没删（年龄 %ss / ttl %ss）"
                               % (lock["age_sec"], lock["ttl_sec"]))
    cfg, cinfo = load_config(config_path)
    result["config"] = cinfo
    if cfg is None:
        result["fails"].append("配置读不到：%s" % cinfo.get("error"))
        result["status"] = "FAIL"
        result["heartbeat"] = heartbeat_info(base, now, 180)
        return result
    alerts = cfg.get("alerts") or {}
    threshold = float(alerts.get("unhealthy_after_sec") or 180)
    kb = os.path.join(base, cfg.get("kb_dir") or "kb")
    cinfo.update({"kb_path": kb.replace("\\", "/"), "kb_outside_repo": not pi.under_base(kb, base),
                  "chat_ids": len(cfg.get("chat_ids") or []),
                  "p2p_allow": len(((cfg.get("p2p") or {}).get("allow_open_ids") or [])),
                  "alerts_enabled": bool(alerts.get("enabled")),
                  "scheduled": scheduled_info(cfg)})
    for _k, _v in cinfo["scheduled"].items():
        if not isinstance(_v, bool):
            result["warns"].append("定时输出 %s 没读成：%s" % (_k, _v))
    import knowledge
    import tools
    brief = tools.kb_brief(base, cfg)
    cinfo["kb"] = brief
    # 资料用得上时才提醒：kb_index 或知识库检索任一开着。两个都关着时没有 kb 目录是正常配置。
    wanted = brief["index_enabled"] or knowledge.enabled(cfg)
    if not brief["exists"] and wanted:
        result["warns"].append("kb_dir=%s 指到 %s，目录不存在（这个实例要用知识库检索）"
                               % (cfg.get("kb_dir") or "kb", brief["path"]))
    elif brief["exists"] and not brief.get("readable", True):
        result["warns"].append("kb 目录读不了：%s" % brief.get("error"))
    elif brief["exists"] and wanted and not brief["files"]:
        result["warns"].append("kb 目录在，但一个能检索的文件都没有（认 %s）。迁出仓库时记得核对 kb_dir"
                               % brief["ext"])
    result["heartbeat"] = heartbeat_info(base, now, threshold)
    if result["heartbeat"]["missing"]:
        result["fails"].append("没有 state/heartbeat，机器人可能没在跑")
    elif not result["heartbeat"]["alive"]:
        result["fails"].append("心跳年龄 %ss 已到告警线 %ss" % (result["heartbeat"]["age_sec"], int(threshold)))
    procs = current_processes() if processes is _AUTO else processes
    if procs is None:
        result["warns"].append("列不出进程，拓扑没有核对")
    else:
        result["topology"] = topology(procs, base, cfg.get("profile"))
        if result["topology"]["serving"] != 1:
            result["fails"].append("本目录 agentbot 进程数=%s，应为 1" % result["topology"]["serving"])
    errors, hints = config_schema_problems(config_path)
    for where, msg in errors:
        result["fails"].append("配置校验：%s：%s" % (where or "（根）", msg))
    for item in hints:
        result["warns"].append("配置提示：%s" % item)
    if with_doctor:
        try:
            rows, code = doctor_rows(cfg, base, procs)
            result["doctor"] = {"exit_code": code, "rows": rows}
            for row in rows:
                if row["level"] == "FAIL":
                    result["fails"].append("doctor FAIL：%s %s" % (row["name"], row["info"]))
                elif row["level"] == "WARN":
                    result["warns"].append("doctor WARN：%s %s" % (row["name"], row["info"]))
        except Exception as exc:
            result["warns"].append("doctor 没跑成：%s" % exc)
    if result["fails"]:
        result["status"] = "FAIL"
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="部署后一条命令给出机器可读结论（只读）")
    ap.add_argument("--base", required=True, help="实例目录，例如 C:/Users/x/mumu-agent-v3")
    ap.add_argument("-c", "--config", default=None, help="配置文件路径，相对 base 也可；agents 里只有一个 json 时自动选它")
    ap.add_argument("--no-doctor", action="store_true", help="只核对本地信息，不调用只读诊断")
    args = ap.parse_args(list(argv) if argv is not None else sys.argv[1:])
    base = os.path.abspath(args.base)
    if not os.path.isdir(base):
        print(json.dumps({"status": "FAIL", "base": base.replace("\\", "/"),
                          "fails": ["目录不存在"]}, ensure_ascii=False, indent=2))
        return 2
    cfg_path = args.config or ""
    if cfg_path and not os.path.isabs(cfg_path):
        cfg_path = os.path.join(base, cfg_path)
    if not cfg_path or not os.path.isfile(cfg_path):
        agents = os.path.join(base, "agents")
        cands = sorted(f for f in os.listdir(agents) if f.endswith(".json") and f != "config.schema.json") \
            if os.path.isdir(agents) else []
        if len(cands) == 1:
            cfg_path = os.path.join(agents, cands[0])
        else:
            print(json.dumps({"status": "FAIL", "base": base.replace("\\", "/"),
                              "fails": ["用 -c 指定配置，agents 里有：%s" % ", ".join(cands)]},
                             ensure_ascii=False, indent=2))
            return 2
    result = verify(base, cfg_path, with_doctor=not args.no_doctor)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
