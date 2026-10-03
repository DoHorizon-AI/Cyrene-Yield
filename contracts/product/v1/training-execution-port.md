# Yield local training-execution port

The Python `TrainingEngineAdapter` (`inspect`, `validate`, `compile`,
`parse_event`, and `collect_result`) is an internal Yield application port. It
translates Product `TrainingRun` intent into one selected implementation and
interprets execution evidence. Yield alone owns submit, poll, cancel, retry,
run and attempt lifecycle state.

The retired Platform `training.engine.v1` and `TrainingBackend.run_training_step`
surfaces did not match a real implementation and are not copied here. Existing
official Plugins expose narrower owner-scoped capabilities:

- `training.distributed.v1` is a pure DeepSpeed configuration and topology
  planner;
- `training.custom-script.v1` remains `MIGRATING_COMPATIBILITY` until its
  implementation delegates process isolation to Platform's generic sandbox and
  worker lifecycle primitives.

Yield calls a selected Plugin contract directly. Platform may admit resources,
create a sandbox, supervise a process and return an opaque connection, but it
does not receive or interpret training requests, events, checkpoints or results.
LLaMA Factory, Transformers Trainer and later engines keep their own contracts
beside their implementations instead of rebuilding a monolithic TrainingBackend
SPI.

`TrainingEngineAdapter` 是 Yield 内部应用端口。旧 Platform `training.engine.v1`
没有对应真实实现，已删除且不在这里复制。Yield 直接调用各训练插件自己的窄接口；
Platform 只提供通用资源、隔离和进程生命周期，不代理训练业务负载。
---

<!-- Chinese Translation / 中文翻译 -->

# Yield 本地 training-execution 端口

Python TrainingEngineAdapter（inspect、validate、compile、parse_event 和 collect_result）是 Yield 内部应用端口。它将 Product TrainingRun 意图转换为选定的一种实现，并解释执行证据。只有 Yield 拥有 submit、poll、cancel、retry 以及 run 和 attempt 生命周期状态。

已退役的 Platform training.engine.v1 和 TrainingBackend.run_training_step 接口与真实实现不匹配，因此未复制到这里。现有官方 Plugins 提供更窄的 owner-scoped 能力：

- training.distributed.v1 是纯 DeepSpeed 配置与拓扑规划器。
- training.custom-script.v1 仍标记为 MIGRATING_COMPATIBILITY，直到其实现委托 Platform 的通用 sandbox 和 worker 生命周期基元来完成进程隔离。

Yield 直接调用选定的 Plugin 契约。Platform 可以准入资源、创建 sandbox、监管进程并返回不透明 connection，但不会接收或解释训练请求、事件、checkpoint 或结果。LLaMA Factory、Transformers Trainer 及后续引擎各自在实现旁保留自己的契约，而不重建单体 TrainingBackend SPI。
