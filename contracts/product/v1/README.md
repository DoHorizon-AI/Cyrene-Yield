# Yield Product contract v1 — contract candidate only

Status: `CONTRACT_CANDIDATE_READY`; no Product runtime, production adapter, or
trainer acceptance is claimed by this branch.

This directory freezes the external Training Product boundary. It deliberately
does not modify or claim acceptance for the trainer, controller, runtime,
executor, capability resolver, LLaMA Factory fork, or existing adapters because
those surfaces have parallel owners.

## Product authority

Yield owns `TrainingRun`, `TrainingAttempt`, cancellation/retry policy, output
artifact relationships, `ModelVersion` composition and lineage identity, and
their durable state. Training environment intent and deterministic selection
are also Yield policy.

- A run in `AWAITING_RETRY` is Product policy after an attempt becomes `LOST`.
  `LOST` can never be rewritten as `COMPLETED`.
- Kernel operation/worker/lease/fence identifiers remain internal execution
  evidence and are not exposed by the public TrainingAttempt schema.
- An engine adapter inspects, validates, compiles, parses events, and collects
  candidate results. It cannot submit/cancel Product runs or decide retry state.
- Artifact bytes remain in the Artifact Plane. Yield persists typed
  `ArtifactRef` values and `derivedFromDigests` lineage.
- `ModelVersion` is defined by `model-version.schema.json` in this Product
  contract. It composes Platform-owned ArtifactRefs without moving artifact
  storage authority into Yield.
- `engineBindingId` selects a Product runtime adapter or a direct owner-scoped
  Plugin binding. It is never a Platform business route.
- Events are notifications derived from committed state, not the source of
  truth.

## Notifications

After durable commits, Yield may publish created/updated notifications for
`training-run` and `training-attempt`, using types such as
`dev.cyrene.yield.training-run.updated.v1`. The common Product event envelope
contains only resource URI/version and change kind; consumers re-read Yield and
tolerate duplicates, reordering, and newer versions. Engine output frames are
measurements, not Product events. This contract-only slice does not claim a
durable outbox publisher.

## State

`TrainingRun`: `QUEUED -> RUNNING -> COMPLETED | FAILED | CANCELLING`,
`CANCELLING -> CANCELLED | FAILED`, and `RUNNING -> AWAITING_RETRY -> RUNNING`.

`TrainingAttempt`: `QUEUED -> RUNNING -> COMPLETED | FAILED | LOST |
CANCELLING`, then `CANCELLING -> CANCELLED | FAILED`.

Cancellation is intent first. A provider cancellation primitive may succeed
without proving that a real delegated execution has stopped; the run remains
`CANCELLING` until reconciled evidence makes it terminal.

## Compatibility

The API root is `/api/v1` and consumes the Workspace `product-http-v1`
compatibility profile. OpenAPI is pinned to 3.1.2, JSON Schema to Draft 2020-12,
and errors to RFC 9457. Creates and cancels are asynchronous: honoring RFC 7240
`Prefer: respond-async` returns `202`, `Preference-Applied: respond-async`, and
`Location` naming the Product-owned TrainingRun. The run itself is the polling
and failure resource; it is not a Kernel Operation. `Idempotency-Key` is a
Cyrene-defined replay key and conflicting body reuse returns a stable
`YIELD_IDEMPOTENCY_CONFLICT`.

Deprecation, migration window, and removal follow the common profile. Changed
state meaning or cancellation semantics requires v2.

## Existing-code mapping and deviations

- `TrainingEngineAdapter` is an existing Yield-local application port, described
  by `training-execution-port.md`; it is not an additional capability contract.
- The external v1 spec uses ArtifactRefs and omits engine kind. The current
  internal `TrainingSpec` still includes filesystem paths, `output_dir`, and
  `EngineKind`; an adapter projection is required before implementation can be
  called contract-complete.
- The current `cyrene.yield.training-runtime.v1` compatibility seam exposes
  `submit/poll/cancel` around `TrainingRuntime` and is marked
  `MIGRATING_COMPATIBILITY`. A production Plugin adapter uses its own
  owner-scoped contract directly; Platform supplies only generic resource,
  sandbox and process lifecycle facts.
- Product runtime orchestration and trainer behavior are unchanged. A narrow
  process-liveness correction treats a Linux zombie PID as stopped, and CI now
  resolves the canonical Platform SDK through an explicit checkout path.
