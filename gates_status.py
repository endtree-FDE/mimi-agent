#!/usr/bin/env python3
"""门禁状态行：给 /状态 用。只读——扫审计文件做计数，不写任何文件、不发消息。

三个门（evidencegate_check / decision_gate_check / write.decision_gate）都关着时返回空，
那一行都不加，/状态 的正文和没有门禁时一样。这是本仓 status_line 的统一惯例（intake/knowledge 同）。
计数只给「次数」和「最近一次阻断的等级与依据状态」，不含用户、内容、群号——/状态 不打印编号。
"""
import json, os, time

_EV_ZH = {"sufficient": "依据完整", "partial": "依据不完整", "conflict": "依据冲突", "missing": "缺少依据"}


def _settings(cfg):
    t = cfg.get("tools") if isinstance(cfg.get("tools"), dict) else {}
    w = cfg.get("write") if isinstance(cfg.get("write"), dict) else {}
    dg = w.get("decision_gate") if isinstance(w.get("decision_gate"), dict) else {}
    levels = dg.get("tools") if isinstance(dg.get("tools"), dict) else {}
    return {
        "eg": bool((t.get("evidencegate_check") or {}).get("enabled")),
        "dg": bool((t.get("decision_gate_check") or {}).get("enabled")),
        "wr": bool(dg.get("enabled")),
        "levels": levels,
    }


def _audit_stats(base, now=None):
    """最近 7 天的审计计数。审计行 ts 是本地无时区 ISO（如 2026-11-08T20:00:00），同格式字符串可直接比。"""
    now = time.time() if now is None else now
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 7 * 86400))
    stats = {"proposed": 0, "blocked": 0, "eg": 0, "dg": 0}
    last_block = ""
    folder = os.path.join(base, "audit")
    if not os.path.isdir(folder):
        return stats, last_block
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".jsonl"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    ts = str(ev.get("ts") or "")
                    if ts and ts < cutoff:
                        continue
                    kind = ev.get("kind")
                    if kind == "write_proposed":
                        stats["proposed"] += 1
                    elif kind == "write_blocked":
                        stats["blocked"] += 1
                        g = ev.get("gate") if isinstance(ev.get("gate"), dict) else {}
                        src = str(g.get("evidence_source") or "")
                        src_bit = "来自证据门" if src.startswith("evidencegate") else ("默认口径" if src == "default" else src)
                        last_block = "等级 %s、%s（%s）" % (g.get("level") or "?", _EV_ZH.get(g.get("evidence"), g.get("evidence") or "?"), src_bit)
                    elif kind == "read":
                        tool = ev.get("tool")
                        if tool == "evidencegate_check":
                            stats["eg"] += 1
                        elif tool == "decision_gate_check":
                            stats["dg"] += 1
        except OSError:
            continue
    return stats, last_block


def status_line(cfg, base, now=None):
    """门禁那一行。三个门全关时返回空，调用方不要加进行。"""
    s = _settings(cfg)
    if not (s["eg"] or s["dg"] or s["wr"]):
        return ""
    bits = []
    if s["eg"]:
        bits.append("证据门 开")
    if s["dg"]:
        bits.append("决策门 开")
    if s["wr"]:
        bits.append("写提案门 开（已声明 %d 个写工具的等级）" % len(s["levels"]))
    head = "门禁：%s。" % "、".join(bits)
    stats, last_block = _audit_stats(base, now)
    parts = []
    if stats["proposed"]:
        parts.append("放行提案 %d 次" % stats["proposed"])
    if stats["blocked"]:
        parts.append("阻断 %d 次" % stats["blocked"])
    if stats["eg"]:
        parts.append("证据门查询 %d 次" % stats["eg"])
    if stats["dg"]:
        parts.append("决策门查询 %d 次" % stats["dg"])
    if not parts:
        return head + " 最近 7 天没有写提案和门禁查询记录。"
    line = head + " 最近 7 天：" + "、".join(parts) + "。"
    if last_block:
        line += " 最近一次阻断：%s。" % last_block
    return line