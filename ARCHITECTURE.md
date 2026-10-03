# Cyrene-Yield Architecture / Cyrene-Yield 架构

Cyrene-Yield owns the **Model Training and Fine-Tuning Product Domain**:
training intent, run/attempt state, policy, reconciliation, checkpoint
publication, and Product handoffs. It consumes provider-neutral ArtifactRefs and
delegates generic execution to Platform and concrete engines to Plugins.

Cyrene-Yield 负责**模型训练与微调 Product 领域**：训练意图、运行/尝试状态、策略、
协调、检查点发布与 Product 交接。它消费与提供方无关的 ArtifactRef，将通用执行
委托给 Platform，将具体引擎委托给 Plugins。

## Runtime boundary / 运行时边界

```text
TrainingSpec -> preflight -> tiny dry run -> TrainingRuntime
    -> Product/Platform executor -> Plugins capability
    -> checkpoint verification -> ArtifactRef / TrainingResult
```

`TrainingRuntime` is the Product attempt coordinator. Platform owns process
supervision, leases, and hardware facts. Plugins own concrete LLaMA Factory and
dataset-validation implementations behind versioned capabilities. Yield keeps
only the Product adapters and projections; it does not vendor an engine or
claim a full migration of the upstream LLaMA-Factory tree.

`TrainingRuntime` 是 Product 尝试协调器。Platform 负责进程监管、租约与硬件事实。
Plugins 在版本化能力后负责具体 LLaMA Factory 与数据集校验实现。Yield 只保留
Product 适配器与投影，不 vendoring 引擎，也不宣称已完整迁移上游 LLaMA-Factory 树。

## Repository map / 仓库地图

- [`training/core/`](training/core/) — Product runtime, contracts, executors, preflight, and checkpoint publication / Product 运行时、契约、执行器、前置校验与检查点发布。
- [`sdk/python/cyrene_yield_contracts/`](sdk/python/cyrene_yield_contracts/) — Public model composition and lineage contracts / 公开模型组合与血缘契约。
- [`trainer-runtime/`](trainer-runtime/) — Separately locked CUDA environment bootstrap and probe / 独立锁定的 CUDA 环境部署与探测。
- [`docs/`](docs/) — Bilingual API, architecture, lifecycle, and dependency records / 双语 API、架构、生命周期与依赖记录。

## Canonical references / 标准参考

- [Cyrene System Map](https://github.com/DoHorizon-AI/Cyrene-Platform/blob/main/docs/start-here/01-system-map.md) / Cyrene 系统地图
- [Training Flow](https://github.com/DoHorizon-AI/Cyrene-Platform/blob/main/docs/flows/training-end-to-end.md) / 训练端到端流程
- [Where Does My Code Go?](https://github.com/DoHorizon-AI/Cyrene-Platform/blob/main/docs/start-here/03-where-does-my-code-go.md) / 代码归属指南
---

<!-- Chinese Translation / 中文翻译 -->

# Cyrene-Yield 架构

Cyrene-Yield 拥有**模型训练与微调 Product 领域**：训练意图、run/attempt 状态、策略、reconciliation、checkpoint 发布和 Product 交接。它使用与提供方无关的 ArtifactRef，并将通用执行委托给 Platform，将具体引擎委托给 Plugins。

## Runtime 边界

```text
TrainingSpec -> preflight -> tiny dry run -> TrainingRuntime
    -> Product/Platform executor -> Plugins capability
    -> checkpoint verification -> ArtifactRef / TrainingResult
```

TrainingRuntime 是 Product 的 attempt 协调器。Platform 负责进程监管、租约和硬件事实。Plugins 通过版本化能力提供具体的 LLaMA Factory 和数据集校验实现。Yield 只保留 Product 适配器和映射层；它不 vendoring 引擎，也不宣称已完整迁移上游 LLaMA-Factory 代码树。

## 仓库地图

- training/core/：Product runtime、契约、执行器、preflight 和 checkpoint 发布。
- sdk/python/cyrene_yield_contracts/：公开模型组合与 lineage 契约。
- trainer-runtime/：独立锁定的 CUDA 环境引导与探测。
- docs/：双语 API、架构、生命周期和依赖记录。

## 规范参考

- Cyrene System Map：Cyrene 系统地图。
- Training Flow：训练端到端流程。
- Where Does My Code Go?：代码归属指南。
