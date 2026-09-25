# LLaMA Factory training Plugin boundary / LLaMA Factory 训练插件边界

## Purpose / 目录用途

This Plugins-owned backend provides the optional training engine capability used by Yield's guided WebUI and CLI. Yield invokes it through the unified `TrainingRuntime` and `training.llama-factory.v1` DirectPluginRuntime contract; the Plugin does not own product-level job state.

该 Plugins 后端提供 Yield 引导式 WebUI 与 CLI 使用的可选训练引擎能力。Yield 通过统一 `TrainingRuntime` 和 `training.llama-factory.v1` DirectPluginRuntime 契约调用它；插件不拥有产品级作业状态。

## Files and responsibilities / 文件与职责

| Path | Responsibility / 职责 |
|---|---|
| [Plugin README](https://github.com/DoHorizon-AI/Cyrene-Plugins-Official/blob/3afbac4d386eb7a27f6778149187884820c0b7f6/plugins/training/llama-factory/README.md) | Plugin backend usage and guided workflow / 插件后端用法与引导式工作流 |
| `plugins/training/llama-factory/src/llamafactory/data/` | Dataset and multimodal processing / 数据集与多模态处理 |
| `plugins/training/llama-factory/src/llamafactory/model/` | Model loading and adapters / 模型加载与适配器 |
| `plugins/training/llama-factory/src/llamafactory/train/` | Training workflows and trainers / 训练工作流与训练器 |
| `plugins/training/llama-factory/src/llamafactory/webui/` | Guided training and adapter merge UI / 引导训练与适配器合并界面 |
| `plugins/training/llama-factory/scripts/` | Conversion, evaluation, and operational scripts / 转换、评估与运维脚本 |

## Suggested reading order / 推荐阅读顺序

1. Read the Plugin README and `CYRENE_IMPROVEMENTS.md`.
2. Read `src/llamafactory/cli.py` and `webui/` for product entry points.
3. Follow `hparams/`, `data/`, `model/`, and `train/` into engine execution.
4. Use scripts and upstream docs only for the operation being investigated.

1. 阅读插件 README 与 `CYRENE_IMPROVEMENTS.md`。
2. 阅读 `src/llamafactory/cli.py` 与 `webui/`，了解产品入口。
3. 沿 `hparams/`、`data/`、`model/` 与 `train/` 跟踪引擎执行。
4. 只在排查对应操作时查阅脚本与上游文档。
---

<!-- Chinese Translation / 中文翻译 -->

# LLaMA Factory training Plugin 边界

## 目录用途

此 Plugins 所有的后端提供 Yield 引导式 WebUI 和 CLI 使用的可选训练引擎能力。Yield 通过统一 TrainingRuntime 和 training.llama-factory.v1 DirectPluginRuntime 契约调用它；Plugin 不拥有 Product 级作业状态。

## 文件与职责

| 路径 | 职责 |
|---|---|
| Plugin README | Plugin 后端用法与引导工作流 |
| plugins/training/llama-factory/src/llamafactory/data/ | 数据集与多模态处理 |
| plugins/training/llama-factory/src/llamafactory/model/ | 模型加载与适配器 |
| plugins/training/llama-factory/src/llamafactory/train/ | 训练工作流与 trainer |
| plugins/training/llama-factory/src/llamafactory/webui/ | 引导式训练与适配器合并界面 |
| plugins/training/llama-factory/scripts/ | 转换、评估和运维脚本 |

## 推荐阅读顺序

1. 阅读 Plugin README 和 CYRENE_IMPROVEMENTS.md。
2. 阅读 src/llamafactory/cli.py 与 webui/，了解 Product 入口。
3. 沿 hparams/、data/、model/ 和 train/ 跟踪引擎执行。
4. 仅在排查相关操作时查阅 scripts 和上游文档。
