# Yield core runtime / Yield 核心运行时

## Purpose / 目录用途

The core runtime owns product training contracts, attempt coordination, engine adapters, executors, preflight, dry-run gates, and checkpoint publication.

核心运行时负责产品训练契约、尝试协调、引擎适配器、执行器、前置校验、试运行门禁与检查点发布。

## Files and responsibilities / 文件与职责

| Path | Responsibility / 职责 |
|---|---|
| [`../../../../training/core/src/cy_exec/training/contracts/`](../../../../training/core/src/cy_exec/training/contracts/) | Stable training domain types / 稳定训练领域类型 |
| [`../../../../training/core/src/cy_exec/training/runtime.py`](../../../../training/core/src/cy_exec/training/runtime.py) | Training attempt coordinator / 训练尝试协调器 |
| [`../../../../training/core/src/cy_exec/training/engines/`](../../../../training/core/src/cy_exec/training/engines/) | Engine adapter boundary / 引擎适配边界 |
| [`../../../../training/core/src/cy_exec/training/executors/`](../../../../training/core/src/cy_exec/training/executors/) | Process and kernel execution / 进程与内核执行 |
| [`../../../../training/core/src/cy_exec/training/checkpoint/`](../../../../training/core/src/cy_exec/training/checkpoint/) | Checkpoint verification and artifacts / 检查点验证与制品 |
| [`../../../../training/core/tests/`](../../../../training/core/tests/) | Core regression tests / 核心回归测试 |

## Suggested reading order / 推荐阅读顺序

1. Read `contracts/spec.py`, `contracts/status.py`, and `contracts/attempt.py`.
2. Follow `runtime.py` into `preflight.py` and `tiny_dry_run.py`.
3. Read engine adapters and executors.
4. Finish with checkpoint and validation modules, then tests.

1. 阅读 `contracts/spec.py`、`contracts/status.py` 与 `contracts/attempt.py`。
2. 从 `runtime.py` 跟踪到 `preflight.py` 与 `tiny_dry_run.py`。
3. 阅读引擎适配器与执行器。
4. 最后阅读检查点/校验模块与测试。
