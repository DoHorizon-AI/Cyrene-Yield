# training/core/src/cy_exec/training/validation / training/core/src/cy_exec/training/validation

Yield training-admission invariants and the direct dataset-validator Plugin adapter.

Yield 训练准入不变量与数据集校验插件直连适配器。

## Files / 文件

| Entry | Responsibility / 职责 |
|---|---|
| `training/core/src/cy_exec/training/validation/__init__.py` | Package initializer and public import boundary. / 包初始化与公开导入边界。 |
| `training/core/src/cy_exec/training/validation/dataset_plugin.py` | Product port and fail-closed `tool.dataset.validator.v1` adapter. / Product 端口与故障关闭的 `tool.dataset.validator.v1` 适配器。 |
| `training/core/src/cy_exec/training/validation/files.py` | Python implementation or test module: files.py. / Python 实现或测试模块：files.py。 |
| `training/core/src/cy_exec/training/validation/model.py` | Python implementation or test module: model.py. / Python 实现或测试模块：model.py。 |
| `training/core/src/cy_exec/training/validation/params.py` | Python implementation or test module: params.py. / Python 实现或测试模块：params.py。 |
| `training/core/src/cy_exec/training/validation/pipeline.py` | Combines Product admission invariants with the Plugin result. / 组合 Product 准入不变量与插件结果。 |

## Suggested reading order / 推荐阅读顺序

Start with `training/core/src/cy_exec/training/validation/__init__.py` and then follow the package entry point or imports.
Read sibling modules in runtime order; use the parent README for ownership boundaries.
从 `training/core/src/cy_exec/training/validation/__init__.py` 开始，再按包入口或导入关系继续阅读。
按运行时顺序阅读同级模块；职责边界请查阅父目录 README。
