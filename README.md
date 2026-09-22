# Cyrene Yield

Cyrene Yield is the enterprise training and fine-tuning Product for the Cyrene platform. This repository contains Product state, policy, orchestration, checkpoint, and handoff logic; reusable training and dataset implementations live in Cyrene-Plugins-Official.

This repository is the clean-root source payload for the public Yield release.
Its canonical public history starts at the parentless `main` root commit
created from this snapshot. The former complete repository history is retained
only in the private `Cyrene-Yield-history-archive`; it is not part of the public
source, a dependency, or a release input.

The historical LLaMA Factory demo datasets under
`plugins/llama-factory-training/data` are excluded from the clean root and are
not approved for public redistribution. The checked-in Product tree contains
source and contracts only; runtime datasets, model weights, and checkpoints
remain operator-managed artifacts.

The GitHub repository and the pinned Plugins revision are publicly reachable,
so an anonymous clone can resolve the locked Product installation. Public
source visibility, binary distribution, hosted CI, and real CUDA acceptance
remain separate gates.

本仓库是 Yield 公开 release 的 clean-root 源码内容；公开规范历史从由此快照创建的
无父 `main` 根提交开始。原完整提交历史仅保留在私有的
`Cyrene-Yield-history-archive` 中，不属于公开源码、依赖或 release 输入。

历史 LLaMA Factory demo 数据集（`plugins/llama-factory-training/data`）已排除在
clean root 之外，也未获准公开再分发。当前 Product 树只包含源码与契约；运行时数据集、
模型权重与 checkpoint 仍由 operator 管理。

GitHub 仓库及锁定的 Plugins 修订版均已可公开访问，匿名 clone 可以解析锁定的 Product
安装。公开源码可见性、二进制分发、Hosted CI 与真实 CUDA 验收仍是彼此独立的门禁。

## Authoritative Documentation & Contracts
- **Product API & Training Contract Specification**: [`docs/API.md`](docs/API.md)
- **Architecture Blueprint**: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Repository Lifecycle & Boundaries**: [`docs/REPOSITORY-LIFECYCLE.md`](docs/REPOSITORY-LIFECYCLE.md)
- **Plugin Dependencies**: [`PLUGIN_DEPENDENCIES.md`](PLUGIN_DEPENDENCIES.md)
- **Dependency and SBOM Record**: [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md)
- **License**: [`LICENSE`](LICENSE)
- **Security Policy**: [`SECURITY.md`](SECURITY.md)
- **Contribution Guide**: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- **LLaMA Factory Plugin Improvements**: [`plugins/training/llama-factory/CYRENE_IMPROVEMENTS.md`](https://github.com/DoHorizon-AI/Cyrene-Plugins-Official/blob/3afbac4d386eb7a27f6778149187884820c0b7f6/plugins/training/llama-factory/CYRENE_IMPROVEMENTS.md)
- **Service Manifest**: [`service.json`](service.json)

## Repository layout

- `training/core/` contains `TrainingSpec`, `TrainingRuntime`/`TrainingAttempt`
  (the single Product job-status authority), Product executors, admission
  invariants, checkpoint/Artifact publication, and direct Plugin adapters.
- Cyrene-Plugins-Official contains the LLaMA Factory backend and generic dataset
  validator. Yield calls them through `training.llama-factory.v1` and
  `tool.dataset.validator.v1`; there is no in-tree trainer or dataset parser fallback.

## Plugins-owned LLaMA Factory context / Plugins 所有的 LLaMA Factory 说明

The following table describes the optional LLaMA Factory capability owned by
Cyrene Plugins. It is context for the Product integration, not a Yield-owned
implementation or a claim that the complete upstream tree has been migrated.
The extracted source and upstream notices remain in the Plugin repository;
review [`UPSTREAM_PROVENANCE.md`](https://github.com/DoHorizon-AI/Cyrene-Plugins-Official/blob/3afbac4d386eb7a27f6778149187884820c0b7f6/plugins/training/llama-factory/UPSTREAM_PROVENANCE.md)
before redistribution.

下表描述由 Cyrene Plugins 所有的可选 LLaMA Factory capability，仅用于说明 Product
集成边界；它不是 Yield 自有实现，也不表示已完成上游完整迁移。提取源码与上游
声明保留在 Plugin 仓库中，重新分发前须审阅上述 provenance。

Cyrene Plugins 中的 LLaMA Factory capability 基于 [hiyouga/LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory) 定制，目标是降低企业用户的训练配置门槛，并将可复用引擎能力与 Yield 的产品生命周期分离。

| 改动 | Plugins 提取版本 | 原版 LLaMA Factory |
| --- | --- | --- |
| WebUI 流程 | 类似 Windows OOBE 的四步引导：模型与环境、数据、训练参数、确认并启动 | 单页展示大量参数和功能标签 |
| 参数复杂度 | 根据训练目标、显存、模型规模和优先级生成推荐配置，并按用户选择显示不同参数分支 | 用户需要自行理解并填写大部分超参数 |
| 自动配置 | 推荐配置生成后仍允许用户修改，最终以用户确认值为准 | 以手动配置为主 |
| 显存安全 | 启动前读取模型配置和训练配置，估算单设备峰值显存，并额外增加 10% 安全余量 | WebUI 不提供同等的训练前显存建议和强制启动告警流程 |
| 风险确认 | 显存不足、低于建议值或无法确认时不建议训练；强制启动必须经过二次警告确认 | 无对应的引导式确认窗口 |
| 加速默认值 | 默认使用 `liger_kernel`，依赖固定为 `liger-kernel>=0.8.0` | 可使用 `auto` 或由用户自行选择加速方式 |
| 产品能力 | WebUI 和 CLI 仅保留训练、配置预览/保存、进度监控及适配器合并导出 | 同时提供评估、预测、聊天、WebChat 和 API 等入口 |
| 适配器交付 | 保留并重新设计适配器合并页面，按来源、输出格式和保存位置分步配置 | 通用导出页面 |
| 多语言 | 支持英语、简体中文、俄语、韩语和日语；业务代码不直接写入中文，显示文本统一来自本地化资源 | 支持多语言，但不是针对新增引导流程设计 |
| CLI | 默认路由仅保留 `train`、`export`、`webui`、`env`、`version`；V1 保留训练类型和 `merge` | 还包含 `api`、`chat`、`eval`、`webchat` 等非训练命令 |

### Guided training workflow

This workflow is documented as Plugin behavior for integration context. Yield
owns the Product intent and attempt state around it; it does not ship or own
this WebUI implementation.

以下 workflow 仅作为 Plugin 集成背景记录。Yield 负责外围 Product 意图与尝试状态，
不交付或拥有该 WebUI 实现。

1. Answer four business-oriented questions to generate a safe starting profile.
2. Select the model, adapter, download source, output directory, and compute environment.
3. Select the dataset and expose only the parameter branch relevant to the chosen goal.
4. Review editable generated settings and run the VRAM preflight check.
5. Start training when the recommendation passes, or explicitly acknowledge the warning before a forced run.

### Adapter merge workflow

The adapter merge page reuses the base model and adapter selected in the guided workflow. Operators then choose the output format and destination before producing a standalone deployment artifact. Quantization remains optional.

## Quick start / 快速开始

```bash
git clone https://github.com/DoHorizon-AI/Cyrene-Yield.git
cd Cyrene-Yield
uv sync --locked --extra dev
uv run pytest training/core/tests/
```

The commands above validate the Product core and its local test contracts. They
do not claim hosted CI, a real CUDA device, model downloads, or a complete
upstream LLaMA Factory migration.

上述命令用于验证 Product core 与本地契约测试，不代表 hosted CI、真实 CUDA 设备、
模型下载或上游 LLaMA Factory 完整迁移已经通过。

Completed ModelVersions can optionally be published through a Platform-resolved
`model.registry.v1` direct endpoint. Yield sends only the immutable descriptor
and source reference; model bytes remain in the Artifact Plane. Configure the
endpoint with `--model-registry-connection-ref`. A valid acknowledgement is
stored durably, so reconciliation does not publish the same version twice.

完成的 ModelVersion 可通过 Platform 解析的 `model.registry.v1` 直连端点发布。Yield
只发送不可变描述符和来源引用，模型字节仍由 Artifact Plane 管理。使用
`--model-registry-connection-ref` 配置端点；有效回执会被持久化，避免 reconciliation
重复发布同一版本。

When the Plugins repository is publicly reachable, its immutable revision can
be inspected separately:

当 Plugins 仓库公开可访问后，可单独检查其不可变修订版：

```bash
git clone https://github.com/DoHorizon-AI/Cyrene-Plugins-Official.git
cd Cyrene-Plugins-Official
git checkout 3afbac4d386eb7a27f6778149187884820c0b7f6
cd plugins/training/llama-factory
pip install -e .
llamafactory-cli webui
```

The optional Plugin WebUI contains two product-level entries only:

可选 Plugin WebUI 仅包含两个 Product 级入口：

- **Guided Training**
- **Adapter Merge**

For direct CLI use:

直接使用 CLI：

```bash
llamafactory-cli train path/to/train.yaml
llamafactory-cli export path/to/export.yaml
```

## Upstream and integration references

- Upstream baseline: `hiyouga/LLaMA-Factory`
- Training-focused customization: `Icy-Lunar/LlamaFactory@f5a4a8f8`
- Plugin integration path: [`plugins/training/llama-factory/`](https://github.com/DoHorizon-AI/Cyrene-Plugins-Official/tree/3afbac4d386eb7a27f6778149187884820c0b7f6/plugins/training/llama-factory)

Model weights, checkpoints, generated configurations, logs, and other runtime artifacts remain in operator-managed storage and must not be committed to this repository.
