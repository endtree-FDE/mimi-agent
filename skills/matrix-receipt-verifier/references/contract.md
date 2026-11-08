# `accepted@2` offline verification contract

## Input envelope

The verifier accepts one JSON object:

```json
{
  "expected": {
    "projectId": "demo-project",
    "taskId": "demo-task-01",
    "sessionId": "studio-example-session-0001",
    "threadId": "demo-thread-01",
    "commandId": "11111111-1111-4111-8111-111111111111",
    "runId": "22222222-2222-4222-8222-222222222222",
    "leaderSender": "@leader:matrix.example.invalid",
    "roles": ["material_intake"],
    "workerSenders": {
      "material_intake": "@worker-material:matrix.example.invalid"
    },
    "projectionProfile": "runtime-zero-write"
  },
  "events": [
    {
      "sender": "@worker-material:matrix.example.invalid",
      "origin_server_ts": 1788134400000,
      "content": { "body": "JUCHANG_AGENT_STUDIO_WORKER_RUN: {...}" }
    },
    {
      "sender": "@leader:matrix.example.invalid",
      "origin_server_ts": 1788134401000,
      "content": { "body": "JUCHANG_AGENT_STUDIO_RECEIPT_ACCEPTED: {...}" }
    }
  ]
}
```

`events[].body` is also accepted as an alternative to `events[].content.body`. The event export should contain only the marker-bearing messages needed for the expected scope.

`roles` may be any non-empty subset of these protocol roles:

- `material_intake`
- `evidence_guard`
- `entity_matcher`
- `approval_guard`

Every expected role requires an explicit `workerSenders` entry. This keeps deployment-specific identities in the caller's local input rather than hard-coding private topology into the Skill.

## Accepted marker

An `accepted@2` marker has exactly these fields:

```text
schema, projectId, taskId, sessionId, threadId, commandId, runId,
role, workerId, workerTaskId, receiptDigest, at,
projectionDigest, projection
```

The schema must be `yixun-agent-studio-receipt-accepted@2`. The verifier intentionally rejects legacy `accepted@1` because it cannot carry a cryptographically bound rich projection.

## Projection

The projection schema is `yixun-agent-studio-receipt-projection@1` with exact top-level fields:

```text
schema, conclusion, analysisSummary, facts, conflicts, impacts,
unknownFields, nextAction, safetyCounters, domainSkillReceipt,
runtimeSkillTraceValidated
```

Canonical JSON recursively sorts object keys while preserving array order, then serializes without whitespace. `projectionDigest` is lowercase SHA-256 of the UTF-8 canonical JSON. The canonical projection must not exceed 48 KiB, and the whole accepted marker line must not exceed 56 KiB.

Visible projection text rejects secret-like labels and values, URLs, authorization material, private filesystem paths, prompt text, and chain-of-thought markers. Evidence references use bounded identifiers rather than paths or URLs.

`domainSkillReceipt` cannot name the Runtime orchestration Skills `juchang-dsh-executor`, `juchang-task-submit`, or `juchang-lifecycle-control`; those do not prove domain work.

## Profiles

### `app-compatible`

Checks exact schemas, bounds, safe text, accepted projection hash, declared sender identity, correlation fields, source receipt digest equality, causal ordering, event time proximity, role coverage, and conflicting bindings inside the supplied export.

### `runtime-zero-write`

Includes all `app-compatible` checks and also requires:

- impact areas exactly in this order: `event`, `ticketing`, `customer_service`, `notification`, `knowledge_base`;
- `productionWrites`, `publicPublishes`, `realRefunds`, and `externalMessages` all exactly `0`.

This profile verifies the declared zero-write projection contract. It does not independently observe external systems, authenticate the export, or verify the source receipt bytes, so it must not be presented as proof that no side effect occurred or that the events came from Matrix.

## Trust boundary

The input contains both the expected identities and the exported events. A caller can fabricate both and recompute an ordinary SHA-256 projection digest. Therefore a passing result means only that the supplied data is internally consistent. The result always reports `sourceAuthenticity: "not_verified"` and `scopeAuthority: "caller_supplied"`.

To make a provenance claim, obtain a separate trusted export/signature or re-read the named events from an authenticated homeserver session and compare them outside this Skill. Do not put access credentials into this verifier.

The verifier additionally requires the worker-completed event to precede the leader-accepted event by no more than five minutes. Conflicting completed worker bindings fail even when one of them matches an accepted marker.

## Exit status

- `0`: every expected role has one non-conflicting, valid chain and the selected policy passes.
- `1`: verification failed. Standard output contains a stable non-secret code.
- `2`: CLI usage or input-file error.

Common failure codes include `accepted_projection_digest_mismatch`, `receipt_digest_binding_mismatch`, `leader_sender_mismatch`, `worker_sender_mismatch`, `matrix_timestamp_mismatch`, `conflicting_receipt_bindings`, `missing_expected_role`, and `zero_write_policy_failed`.

> AI生成
