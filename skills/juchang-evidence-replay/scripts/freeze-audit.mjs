#!/usr/bin/env node
// freeze-audit.mjs——mimi 账本零写入冻结导出器。
// 把群记忆（memory/groups/**/meta.json）与审计链（audit/*.jsonl）冻结成一份「可重算哈希」的
// 只读回放档案，供 juchang-evidence-replay 核对器（scripts/check.mjs）核验。
// 零写入红线：本脚本只读，绝不写任何文件、不发任何消息；档案由调用方经 stdout 重定向保存。
// 用法：node freeze-audit.mjs --base <实例目录> [--since YYYY-MM-DD] [--label "说明"]
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

const digest = (text) => createHash("sha256").update(text, "utf8").digest("hex");

function parseArgs(argv) {
  const out = { base: process.cwd(), since: null, label: "" };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--base" && argv[i + 1]) { out.base = argv[i + 1]; i++; }
    else if (argv[i] === "--since" && argv[i + 1]) { out.since = argv[i + 1]; i++; }
    else if (argv[i] === "--label" && argv[i + 1]) { out.label = argv[i + 1]; i++; }
    else { process.stderr.write(`未知参数: ${argv[i]}\n`); process.exit(2); }
  }
  return out;
}

function walkFiles(root, prefix = "") {
  const found = [];
  if (!existsSync(root)) return found;
  for (const name of readdirSync(root)) {
    const p = path.join(root, name);
    const rel = path.join(prefix, name).replace(/\\/g, "/");
    if (statSync(p).isDirectory()) found.push(...walkFiles(p, rel));
    else found.push(rel);
  }
  return found;
}

const { base, since, label } = parseArgs(process.argv.slice(2));

// 权威账本：群记忆 meta.json + 审计 jsonl。rel 相对 base，方便后面 path.join(base, rel)。
const memoryRoot = path.join(base, "memory", "groups");
const auditRoot = path.join(base, "audit");
const memoryFiles = walkFiles(memoryRoot)
  .map((r) => path.join("memory", "groups", r).replace(/\\/g, "/"))
  .filter((r) => r.endsWith("/meta.json") || r.endsWith(".md"));
const auditFiles = walkFiles(auditRoot)
  .map((r) => path.join("audit", r).replace(/\\/g, "/"))
  .filter((r) => r.endsWith(".jsonl")).sort();

let files = [];
let totalEvents = 0;
const invocations = new Map();

for (const rel of [...memoryFiles, ...auditFiles]) {
  const abs = path.join(base, rel);
  if (!existsSync(abs)) continue;
  let raw;
  try { raw = readFileSync(abs, "utf8"); } catch (error) { continue; }
  // audit 行按时间窗口过滤
  let text = raw;
  if (rel.endsWith(".jsonl") && since) {
    const keep = raw.split("\n").filter((line) => {
      if (!line.trim()) return false;
      const m = line.match(/"ts"\s*:\s*"([^"]+)"/);
      return m ? m[1].slice(0, 10) >= since : true;
    });
    totalEvents += keep.length;
    text = keep.join("\n");
  } else if (rel.endsWith(".jsonl")) {
    totalEvents += raw.split("\n").filter((l) => l.trim()).length;
  }
  if (!text.trim()) continue;
  // 聚合审计事件：工具调用次数如实登记
  if (rel.endsWith(".jsonl")) {
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      try {
        const ev = JSON.parse(line);
        const tool = String(ev.tool || ev.kind || "");
        if (tool) invocations.set(tool, (invocations.get(tool) || 0) + 1);
      } catch { /* 坏行不计入调用聚合，但哈希照算 */ }
    }
  }
  files.push({ file: rel, sha256: digest(text), bytes: Buffer.byteLength(text) });
}

// 哈希链：逐文件 sha256 → 排序拼接 → 汇总。sourceText 留在档案里，任何人可重算。
files.sort((a, b) => (a.file < b.file ? -1 : a.file > b.file ? 1 : 0));
const sourceText = files.map((f) => `${f.file}:${f.sha256}`).join("\n");
const rawExportSha256 = digest(sourceText);

// 缺口如实登记：窗口内有 write_blocked → needs_revision；未触发的工具保持 not_called。
const hasBlocked = auditFiles.some((rel) =>
  existsSync(path.join(base, rel)) &&
  /"kind"\s*:\s*"write_blocked"/.test(readFileSync(path.join(base, rel), "utf8")));

const skillInvocations = [];
const allTools = ["history", "docs_read", "base_read", "calendar_read", "evidencegate_check",
  "decision_gate_check", "evidence_replay_check", "receipt_verify", "docs_create", "base_create",
  "calendar_create", "calendar_delete", "memory_propose"];
for (const tool of allTools) {
  const count = invocations.get(tool) || 0;
  skillInvocations.push({ skill: tool, status: count ? "completed" : "not_called", count });
}

const replay = {
  schema: "mimi-audit-replay@1",
  readonly: true,
  disclosure: (label ? `${label}；` : "")
    + "mimi 本机账本零写入冻结导出（只读自检）：群记忆与审计链的哈希快照，用于事后复核；它只证明档案与账本一致，不是业务事实的证明。",
  freeze: {
    base: base.replace(/\\/g, "/"),
    since: since || "all",
    files,
    event_count: totalEvents,
    sourceText,
  },
  rawExportSha256,
  digests: { rawExportSha256 },
  skillInvocations,
};
if (hasBlocked) replay.qualityReview = { state: "needs_revision" };

process.stdout.write(`${JSON.stringify(replay, null, 2)}\n`);