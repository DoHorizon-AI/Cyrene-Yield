# training/core/src/cy_exec/training/executors / training/core/src/cy_exec/training/executors

Local, kernel, and plugin execution boundaries.

本地、内核与插件执行边界。

## Files / 文件

| Entry | Responsibility / 职责 |
|---|---|
| `training/core/src/cy_exec/training/executors/__init__.py` | Package initializer and public import boundary. / 包初始化与公开导入边界。 |
| `training/core/src/cy_exec/training/executors/base.py` | Python implementation or test module: base.py. / Python 实现或测试模块：base.py。 |
| `training/core/src/cy_exec/training/executors/cyrene_kernel.py` | Python implementation or test module: cyrene_kernel.py. / Python 实现或测试模块：cyrene_kernel.py。 |
| `training/core/src/cy_exec/training/executors/inprocess_kernel.py` | Python implementation or test module: inprocess_kernel.py. / Python 实现或测试模块：inprocess_kernel.py。 |
| `training/core/src/cy_exec/training/executors/kernel_commands.py` | Python implementation or test module: kernel_commands.py. / Python 实现或测试模块：kernel_commands.py。 |
| `training/core/src/cy_exec/training/executors/kernel_events.py` | Python implementation or test module: kernel_events.py. / Python 实现或测试模块：kernel_events.py。 |
| `training/core/src/cy_exec/training/executors/kernel_mapping.py` | Python implementation or test module: kernel_mapping.py. / Python 实现或测试模块：kernel_mapping.py。 |
| `training/core/src/cy_exec/training/executors/kernel_port.py` | Python implementation or test module: kernel_port.py. / Python 实现或测试模块：kernel_port.py。 |
| `training/core/src/cy_exec/training/executors/kernel_uds.py` | Python implementation or test module: kernel_uds.py. / Python 实现或测试模块：kernel_uds.py。 |
| `training/core/src/cy_exec/training/executors/local_process.py` | Python implementation or test module: local_process.py. / Python 实现或测试模块：local_process.py。 |
| `training/core/src/cy_exec/training/executors/plugin_control.py` | Python implementation or test module: plugin_control.py. / Python 实现或测试模块：plugin_control.py。 |
| `training/core/src/cy_exec/training/executors/workload_stager.py` | Python implementation or test module: workload_stager.py. / Python 实现或测试模块：workload_stager.py。 |

## Suggested reading order / 推荐阅读顺序

Start with `training/core/src/cy_exec/training/executors/__init__.py` and then follow the package entry point or imports.
Read sibling modules in runtime order; use the parent README for ownership boundaries.
从 `training/core/src/cy_exec/training/executors/__init__.py` 开始，再按包入口或导入关系继续阅读。
按运行时顺序阅读同级模块；职责边界请查阅父目录 README。
