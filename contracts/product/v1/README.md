# Yield Product contract v1

Status: `IMPLEMENTED_RC`; the Product API and local runtime adapter are covered
by contract and unit evidence. Real CUDA, remote Artifact storage, and upstream
trainer acceptance remain separate release gates.

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
measurements, not Product events. A durable outbox publisher is not claimed.

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
---

<!-- Chinese Translation / 中文翻译 -->

# Yield Product 契约 v1

状态：IMPLEMENTED_RC；Product API 和本地 runtime 适配器已有契约与单元证据。真实 CUDA、远程 Artifact 存储以及上游 trainer 验收仍是彼此独立的 release 门禁。

此目录冻结外部 Training Product 边界。由于 trainer、controller、runtime、executor、capability resolver、LLaMA Factory fork 和既有适配器均有各自并行的所有者，此目录有意不修改这些部分，也不宣称它们已经验收。

## Product 权威归属

Yield 拥有 TrainingRun、TrainingAttempt、取消/重试策略、输出制品关系、ModelVersion 组合与 lineage 身份，以及它们的持久化状态。训练环境意图与确定性选择也属于 Yield 策略。

- Attempt 变为 LOST 后，run 进入 AWAITING_RETRY 是 Product 策略。LOST 永远不能改写为 COMPLETED。
- Kernel operation/worker/lease/fence 标识符属于内部执行证据，不会暴露在公开 TrainingAttempt schema 中。
- 引擎适配器负责检查、验证、编译、解析事件并收集候选结果。它不能提交/取消 Product run，也不能决定重试状态。
- Artifact 字节保留在 Artifact Plane。Yield 持久化带类型的 ArtifactRef 值和 derivedFromDigests lineage。
- ModelVersion 由此 Product 契约中的 model-version.schema.json 定义。它组合 Platform 所有的 ArtifactRef，但不会将制品存储权转移给 Yield。
- engineBindingId 用于选择 Product runtime 适配器或直接的 owner-scoped Plugin binding；它永远不是 Platform 业务路由。
- 事件是由已提交状态派生的通知，不是真实数据来源。

## 通知

在持久化提交后，Yield 可以为 training-run 和 training-attempt 发布 created/updated 通知，类型示例为 dev.cyrene.yield.training-run.updated.v1。通用 Product 事件 envelope 仅包含资源 URI/版本和变更类型；消费者应重新读取 Yield，并容忍重复、乱序和更新版本。引擎输出 frame 是测量数据，不是 Product 事件。本文不宣称存在持久化 outbox publisher。

## 状态

TrainingRun：QUEUED -> RUNNING -> COMPLETED | FAILED | CANCELLING；CANCELLING -> CANCELLED | FAILED；以及 RUNNING -> AWAITING_RETRY -> RUNNING。

TrainingAttempt：QUEUED -> RUNNING -> COMPLETED | FAILED | LOST | CANCELLING；随后 CANCELLING -> CANCELLED | FAILED。

取消首先是意图。提供方的取消基元即使成功，也不一定证明实际委派的执行已停止；在 reconciliation 证据将 run 判定为终态前，run 保持 CANCELLING。

## 兼容性

API 根路径为 /api/v1，使用 Workspace 的 product-http-v1 兼容配置。OpenAPI 固定为 3.1.2，JSON Schema 固定为 Draft 2020-12，错误遵循 RFC 9457。创建与取消为异步操作：遵循 RFC 7240 的 Prefer: respond-async 时，返回 202、Preference-Applied: respond-async，以及指向 Product 所有 TrainingRun 的 Location。run 本身是轮询与失败资源；它不是 Kernel Operation。Idempotency-Key 是 Cyrene 定义的重放键；重复使用同一键但请求体冲突时，返回稳定的 YIELD_IDEMPOTENCY_CONFLICT。

弃用、迁移窗口和移除遵循通用兼容配置。状态含义或取消语义改变时必须升至 v2。

## 既有代码映射与差异

- TrainingEngineAdapter 是 Yield 本地已有的应用端口，说明见 training-execution-port.md；它不是新增的 capability 契约。
- 外部 v1 规范使用 ArtifactRef 且省略 engine kind。当前内部 TrainingSpec 仍包含文件系统路径、output_dir 和 EngineKind；在实现可称为契约完整前，需要增加适配器投影。
- 当前 cyrene.yield.training-runtime.v1 兼容接缝围绕 TrainingRuntime 暴露 submit/poll/cancel，并标记为 MIGRATING_COMPATIBILITY。生产 Plugin 适配器直接使用自身的 owner-scoped 契约；Platform 只提供通用资源、sandbox 和进程生命周期事实。
- Product runtime 编排和 trainer 行为未改变。针对性修正将 Linux zombie PID 视为已停止；CI 现在通过显式 checkout 路径解析规范 Platform SDK。
