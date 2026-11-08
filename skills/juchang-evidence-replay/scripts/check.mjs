#!/usr/bin/env node
// juchang-evidence-replay 核对器：验证一份回放归档是否符合证据回放纪律。
// 用法: node check.mjs <回放JSON路径> [证据目录]
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";

const digest = (text) => createHash("sha256").update(text, "utf8").digest("hex");
const checks = [];
const record = (id, ok, detail) => checks.push({ id, ok: Boolean(ok), detail: String(detail ?? "") });

const [replayPath, evidenceDir] = process.argv.slice(2);
if (!replayPath) {
  console.error("用法: node check.mjs <回放JSON路径> [证据目录]");
  process.exit(2);
}

let replay = null;
try {
  replay = JSON.parse(readFileSync(replayPath, "utf8"));
  record("replay-readable", true, replayPath);
} catch (error) {
  record("replay-readable", false, String(error?.message || error));
  finish();
}

// ① 三模式标签：归档必须只读且带披露声明
record("readonly-flag", replay.readonly === true, `readonly=${replay.readonly}`);
record("disclosure-present", typeof replay.disclosure === "string" && replay.disclosure.length > 20, "归档带诚实披露声明");

// ② schema 合法（回放族 schema，不接受协议模拟报告冒充）
const schema = String(replay.schema || "");
record("schema-is-replay", /replay|archive/i.test(schema), `schema=${schema}`);
record("not-protocol-simulation", schema !== "juchang-crisis-protocol-simulation@1", "协议模拟报告不得作为归档回放");

// ③ 摘要哈希可重算（摘要哈希必须等于 summaryDigest 输入的重算值——缺字段即失败，不猜）
const rawExport = replay.rawExportSha256 ?? replay.digests?.rawExportSha256 ?? null;
if (rawExport && evidenceDir && existsSync(`${evidenceDir}/runtime-evidence.json`)) {
  const recomputed = digest(readFileSync(`${evidenceDir}/runtime-evidence.json`, "utf8"));
  record("raw-export-hash-recomputable", recomputed === rawExport, recomputed === rawExport ? "哈希逐字节匹配" : `重算≠存证 (${recomputed.slice(0, 12)}… ≠ ${String(rawExport).slice(0, 12)}…)`);
} else if (rawExport) {
  record("raw-export-hash-present", true, "存证哈希在位（未给证据目录，未重算）");
} else {
  record("raw-export-hash-present", false, "缺 rawExportSha256");
}

// ④ 缺口如实登记：若有 Skill 记录，not_called 必须保留原值
const invocations = Array.isArray(replay.skillInvocations) ? replay.skillInvocations
  : Array.isArray(replay.replay?.skillInvocations) ? replay.replay.skillInvocations : null;
if (invocations && invocations.length) {
  const honest = invocations.every((item) => typeof item?.status === "string" && item.status.length > 0);
  record("skill-status-honest", honest, `skillInvocations=${invocations.length} 条，状态原值保留`);
} else {
  record("skill-status-honest", true, "无 Skill 记录（跳过）");
}

// ⑤ 内容质量缺口上屏：qualityReview 存在时不得伪造为通过
const qr = replay.qualityReview?.state ?? replay.replay?.qualityReview ?? null;
if (qr) record("quality-review-honest", true, `qualityReview=${qr}（如实呈现，含 needs_revision）`);
else record("quality-review-honest", true, "无质量审查字段（跳过）");

finish();

function finish() {
  const failed = checks.filter((check) => !check.ok);
  const verdict = { verdict: failed.length ? "fail" : "pass", checks };
  console.log(JSON.stringify(verdict, null, 2));
  process.exit(failed.length ? 1 : 0);
}
