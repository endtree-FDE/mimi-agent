# Evidence contract

## Gate states

| State | Meaning | Allowed next step |
|---|---|---|
| `ACCEPT_CANDIDATE` | Contract and deterministic checks passed | Human review |
| `HUMAN_REVIEW` | Candidate is parseable but contains missing, ambiguous, cropped, obstructed, injected, or conflicting evidence | Inspect source evidence, correct, or request resubmission |
| `MODEL_OUTPUT_INVALID` | Candidate cannot safely enter the workflow | Retry, repair the integration, or reject the model output |

None grants approval, payment, publication, or ERP-write permission.

## Field envelope

```json
{
  "value": null,
  "source": "model_output",
  "source_text": null,
  "locator": null,
  "confidence": null,
  "match_count": null,
  "contract_errors": [],
  "business_rule_errors": [],
  "expected_mismatches": [],
  "human_correction": null,
  "final_status": "CANDIDATE"
}
```

Keep unavailable evidence as `null`; never invent it.

For a critical field, set `"locator_required": true`.

| Condition | Route / code |
|---|---|
| `match_count === 0` | `HUMAN_REVIEW / EVIDENCE_TEXT_NOT_FOUND` |
| `match_count > 1` | `HUMAN_REVIEW / EVIDENCE_AMBIGUOUS` |
| locator absent | `HUMAN_REVIEW / EVIDENCE_LOCATOR_REQUIRED` |
| locator touches configured edge margin | `HUMAN_REVIEW / EVIDENCE_TOUCHES_EDGE` |
| several configured fields terminate on one vertical line | `HUMAN_REVIEW / RULE_ALIGNED_RIGHT_EDGES` |

Locators use a one-based page number and normalized `[x1, y1, x2, y2]`, with every coordinate from 0 to 1.

## Minimum run record

- run and case identifier;
- input classification and SHA-256;
- model, task, schema version, and start/end time;
- raw response reference, request ID, Token usage, and exit code;
- model and validator duration;
- gate state and error codes;
- `human_required` and `erp_write_allowed`;
- retry, failure, implementation-correction, and manual-data-correction events;
- evidence boundary.

## Metric formulas

- dangerous false-accept rate = unacceptable cases routed `ACCEPT_CANDIDATE` / unacceptable cases;
- overblock rate = acceptable cases not routed `ACCEPT_CANDIDATE` / acceptable cases;
- routing accuracy = cases with expected route / labeled cases;
- locator coverage = critical fields with one valid locator / locator-eligible critical fields.

Always publish numerator and denominator. A zero failure count on a small synthetic development set is not production proof.
