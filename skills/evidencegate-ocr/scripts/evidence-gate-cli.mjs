import fs from "node:fs";
import crypto from "node:crypto";
import { evaluate } from "./evidence-gate.mjs";

const pairs = [];
for (let index = 2; index < process.argv.length; index += 1) {
  if (process.argv[index].startsWith("--")) pairs.push([process.argv[index].slice(2), process.argv[index + 1]]);
}
const args = Object.fromEntries(pairs);
const readText = (path) => fs.readFileSync(path, "utf8").replace(/^\uFEFF/, "");

try {
  if (!args.candidate || !args.schema) throw new Error("Usage: node evidence-gate-cli.mjs --candidate <file> --schema <file> [--expected <file>] [--output <file>]");
  const candidateText = readText(args.candidate);
  const schemaText = readText(args.schema);
  const result = {
    ...evaluate({ candidateText, schema: JSON.parse(schemaText), expected: args.expected ? JSON.parse(readText(args.expected)) : null }),
    candidate_sha256: crypto.createHash("sha256").update(candidateText).digest("hex"),
    schema_sha256: crypto.createHash("sha256").update(schemaText).digest("hex")
  };
  const json = `${JSON.stringify(result, null, 2)}\n`;
  if (args.output) fs.writeFileSync(args.output, json, "utf8");
  process.stdout.write(json);
} catch (err) {
  process.stderr.write(`${err.message}\n`);
  process.exit(2);
}
