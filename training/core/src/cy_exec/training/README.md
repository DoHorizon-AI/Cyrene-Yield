# training/core/src/cy_exec/training / training/core/src/cy_exec/training

Training contracts, runtime coordination, engines, executors, checkpoints, and validation.

训练契约、运行时协调、引擎、执行器、检查点与校验。

## Files / 文件

| Entry | Responsibility / 职责 |
|---|---|
| `training/core/src/cy_exec/training/checkpoint/` | Checkpoint validation, digest, and artifact publication. / 检查点校验、摘要与制品发布。 |
| `training/core/src/cy_exec/training/contracts/` | Stable product contracts for training intent, attempts, workload, events, and artifacts. / 训练意图、尝试、工作负载、事件与制品的稳定产品契约。 |
| `training/core/src/cy_exec/training/engines/` | Training-engine adapter boundaries. / 训练引擎适配边界。 |
| `training/core/src/cy_exec/training/executors/` | Local, kernel, and plugin execution boundaries. / 本地、内核与插件执行边界。 |
| `training/core/src/cy_exec/training/validation/` | Product admission invariants and dataset-validator Plugin adapter. / Product 准入不变量与数据集校验插件适配器。 |
| `training/core/src/cy_exec/training/worker/` | Nested training module. / 嵌套训练模块。 |
| `training/core/src/cy_exec/training/__init__.py` | Package initializer and public import boundary. / 包初始化与公开导入边界。 |
| `training/core/src/cy_exec/training/artifacts.py` | Python implementation or test module: artifacts.py. / Python 实现或测试模块：artifacts.py。 |
| `training/core/src/cy_exec/training/capability_seam.py` | Python implementation or test module: capability_seam.py. / Python 实现或测试模块：capability_seam.py。 |
| `training/core/src/cy_exec/training/control_plane.py` | Python implementation or test module: control_plane.py. / Python 实现或测试模块：control_plane.py。 |
| `training/core/src/cy_exec/training/preflight.py` | Python implementation or test module: preflight.py. / Python 实现或测试模块：preflight.py。 |
| `training/core/src/cy_exec/training/runtime.py` | Python implementation or test module: runtime.py. / Python 实现或测试模块：runtime.py。 |
| `training/core/src/cy_exec/training/tiny_dry_run.py` | Python implementation or test module: tiny_dry_run.py. / Python 实现或测试模块：tiny_dry_run.py。 |

## Suggested reading order / 推荐阅读顺序

Start with `training/core/src/cy_exec/training/checkpoint/` and then follow the package entry point or imports.
Read sibling modules in runtime order; use the parent README for ownership boundaries.
从 `training/core/src/cy_exec/training/checkpoint/` 开始，再按包入口或导入关系继续阅读。
按运行时顺序阅读同级模块；职责边界请查阅父目录 README。
