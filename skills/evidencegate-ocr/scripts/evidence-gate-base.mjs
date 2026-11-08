import fs from "node:fs";
import crypto from "node:crypto";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, value, index, all) => {
    if (value.startsWith("--")) pairs.push([value.slice(2), all[index + 1]]);
    return pairs;
  }, [])
);

const readText = (path) => fs.readFileSync(path, "utf8").replace(/^\uFEFF/, "");
const sha256 = (text) => crypto.createHash("sha256").update(text).digest("hex");
const error = (code, message, field = null) => ({ code, field, message });

function parseCandidate(raw, contractErrors) {
  let text = raw.trim();
  if (text.startsWith("```")) {
    contractErrors.push(error("MARKDOWN_WRAPPER", "Candidate output is wrapped in Markdown."));
    text = text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  }

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    contractErrors.push(error("INVALID_JSON", "Candidate output is not valid JSON."));
    return { fields: {}, evidence: {}, meta: {} };
  }

  const content = parsed?.choices?.[0]?.message?.content;
  if (typeof content === "string") {
    const nested = parseCandidate(content, contractErrors);
    nested.meta = { model: parsed.model ?? null, usage: parsed.usage ?? null };
    return nested;
  }

  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    contractErrors.push(error("ROOT_NOT_OBJECT", "Candidate root must be a JSON object."));
    return { fields: {}, evidence: {}, meta: {} };
  }

  if ("fields" in parsed) {
    if (!parsed.fields || Array.isArray(parsed.fields) || typeof parsed.fields !== "object") {
      contractErrors.push(error("FIELDS_NOT_OBJECT", "Envelope fields must be an object."));
    }
    return {
      fields: parsed.fields && typeof parsed.fields === "object" && !Array.isArray(parsed.fields) ? parsed.fields : {},
      evidence: parsed.evidence && typeof parsed.evidence === "object" && !Array.isArray(parsed.evidence) ? parsed.evidence : {},
      meta: {}
    };
  }

  return { fields: parsed, evidence: {}, meta: {} };
}

function typeMatches(value, spec) {
  if (spec.type === "string") return typeof value === "string";
  if (spec.type === "number") return typeof value === "number" && Number.isFinite(value);
  if (spec.type === "integer") return Number.isInteger(value);
  if (spec.type === "boolean") return typeof value === "boolean";
  if (spec.type === "array") {
    return Array.isArray(value) && (!spec.items || value.every((item) => typeof item === spec.items));
  }
  return false;
}

function validateEvidence(evidence, fieldNames, contractErrors) {
  for (const [field, item] of Object.entries(evidence)) {
    if (!fieldNames.includes(field)) {
      contractErrors.push(error("UNKNOWN_EVIDENCE_FIELD", `Evidence references unknown field: ${field}.`, field));
      continue;
    }
    if (!item || Array.isArray(item) || typeof item !== "object") {
      contractErrors.push(error("EVIDENCE_NOT_OBJECT", "Field evidence must be an object.", field));
      continue;
    }
    if (item.confidence != null && (typeof item.confidence !== "number" || item.confidence < 0 || item.confidence > 1)) {
      contractErrors.push(error("INVALID_CONFIDENCE", "Confidence must be null or a number from 0 to 1.", field));
    }
    if (item.source_text != null && typeof item.source_text !== "string") {
      contractErrors.push(error("INVALID_SOURCE_TEXT", "Source text must be null or a string.", field));
    }
    if (item.match_count != null && (!Number.isInteger(item.match_count) || item.match_count < 0)) {
      contractErrors.push(error("INVALID_MATCH_COUNT", "Match count must be null or a non-negative integer.", field));
    }
  }
}

export function evaluate({ candidateText, schema, expected = null }) {
  const started = process.hrtime.bigint();
  const contractErrors = [];
  const businessRuleErrors = [];
  const expectedMismatches = [];
  const parsed = parseCandidate(candidateText, contractErrors);
  const fields = parsed.fields;
  const fieldNames = Object.keys(schema.fields);

  for (const [name, spec] of Object.entries(schema.fields)) {
    if (!(name in fields) || fields[name] === null) {
      if (spec.required) contractErrors.push(error("FIELD_REQUIRED", "Required field is missing or null.", name));
      continue;
    }
    if (!typeMatches(fields[name], spec)) {
      contractErrors.push(error("FIELD_TYPE", `Expected ${spec.type}.`, name));
    }
  }

  if (schema.additional_fields === "reject") {
    for (const name of Object.keys(fields)) {
      if (!fieldNames.includes(name)) contractErrors.push(error("UNKNOWN_FIELD", "Field is not declared in the schema.", name));
    }
  }

  validateEvidence(parsed.evidence, fieldNames, contractErrors);

  for (const rule of schema.rules ?? []) {
    if (rule.kind === "date_order") {
      const before = fields[rule.before];
      const after = fields[rule.after];
      if (typeof before === "string" && typeof after === "string" && before >= after) {
        businessRuleErrors.push(error("RULE_DATE_ORDER", `${rule.before} must be earlier than ${rule.after}.`, rule.before));
      }
    } else if (rule.kind === "sum_equals") {
      const values = rule.fields.map((name) => fields[name]);
      const target = fields[rule.target];
      if (values.every((value) => typeof value === "number") && typeof target === "number") {
        const delta = Math.abs(values.reduce((sum, value) => sum + value, 0) - target);
        if (delta > (rule.tolerance ?? 0)) {
          businessRuleErrors.push(error("RULE_SUM_EQUALS", `${rule.fields.join(" + ")} must equal ${rule.target}.`, rule.target));
        }
      }
    } else if (rule.kind === "array_contains_all") {
      const actual = fields[rule.field];
      if (Array.isArray(actual)) {
        const missing = rule.values.filter((value) => !actual.some((item) => item.includes(value)));
        if (missing.length) {
          businessRuleErrors.push(error("RULE_ARRAY_CONTAINS_ALL", `Missing required evidence labels: ${missing.join(", ")}.`, rule.field));
        }
      }
    } else {
      contractErrors.push(error("UNKNOWN_RULE", `Unsupported rule kind: ${rule.kind}.`));
    }
  }

  if (expected) {
    for (const name of expected.exact_fields ?? []) {
      if (JSON.stringify(fields[name]) !== JSON.stringify(expected.expected_fields?.[name])) {
        expectedMismatches.push({
          code: "EXPECTED_MISMATCH",
          field: name,
          expected: expected.expected_fields?.[name] ?? null,
          actual: fields[name] ?? null
        });
      }
    }
  }

  const status = contractErrors.length
    ? "MODEL_OUTPUT_INVALID"
    : businessRuleErrors.length || expectedMismatches.length
      ? "HUMAN_REVIEW"
      : "ACCEPT_CANDIDATE";

  const fieldEnvelope = Object.fromEntries(fieldNames.map((name) => {
    const fieldContract = contractErrors.filter((item) => item.field === name);
    const fieldRules = businessRuleErrors.filter((item) => item.field === name);
    const fieldExpected = expectedMismatches.filter((item) => item.field === name);
    const evidence = parsed.evidence[name] ?? {};
    return [name, {
      value: name in fields ? fields[name] : null,
      source: "model_output",
      locator: evidence.locator ?? null,
      confidence: evidence.confidence ?? null,
      source_text: evidence.source_text ?? null,
      match_count: evidence.match_count ?? null,
      contract_errors: fieldContract,
      business_rule_errors: fieldRules,
      expected_mismatches: fieldExpected,
      human_correction: null,
      final_status: fieldContract.length ? "INVALID" : fieldRules.length || fieldExpected.length ? "NEEDS_REVIEW" : "CANDIDATE"
    }];
  }));

  return {
    gate_version: "0.2.0",
    schema_id: schema.schema_id,
    status,
    model: parsed.meta.model ?? null,
    usage: parsed.meta.usage ?? null,
    contract_errors: contractErrors,
    business_rule_errors: businessRuleErrors,
    expected_mismatches: expectedMismatches,
    fields: fieldEnvelope,
    human_required: schema.safety?.human_required !== false,
    erp_write_allowed: schema.safety?.erp_write_allowed === true,
    validator_duration_ms: Number(process.hrtime.bigint() - started) / 1e6
  };
}

function main() {
  if (!args.candidate || !args.schema) {
    throw new Error("Usage: node evidence-gate.mjs --candidate <file> --schema <file> [--expected <file>] [--output <file>]");
  }
  const candidateText = readText(args.candidate);
  const schemaText = readText(args.schema);
  const schema = JSON.parse(schemaText);
  const expected = args.expected ? JSON.parse(readText(args.expected)) : null;
  const result = {
    ...evaluate({ candidateText, schema, expected }),
    candidate_sha256: sha256(candidateText),
    schema_sha256: sha256(schemaText)
  };
  const json = JSON.stringify(result, null, 2);
  if (args.output) fs.writeFileSync(args.output, `${json}\n`, "utf8");
  process.stdout.write(`${json}\n`);
}

if (process.argv[1] && import.meta.url === `file:///${process.argv[1].replaceAll("\\", "/")}`) {
  try {
    main();
  } catch (err) {
    process.stderr.write(`${err.message}\n`);
    process.exit(2);
  }
}

