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
