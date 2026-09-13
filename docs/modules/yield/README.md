# Yield module / Yield 模块

## Purpose / 目录用途

This module page is the entry point for the unified training runtime and the optional Plugins-owned LLaMA Factory backend.

本模块页是统一训练运行时与 Plugins 所有的可选 LLaMA Factory 后端的入口。

## Files and responsibilities / 文件与职责

| Path | Responsibility / 职责 |
|---|---|
| [`core/README.md`](core/README.md) | Training contracts, runtime, executors, preflight, and checkpoints / 训练契约、运行时、执行器、前置校验与检查点 |
| [`plugin/README.md`](plugin/README.md) | Plugin connection boundary and extracted LLaMA Factory package / 插件连接边界与提取后的 LLaMA Factory 包 |
| [`../../API.md`](../../API.md) | Product objects and lifecycle contract / 产品对象与生命周期契约 |
| [`../../REPOSITORY-LIFECYCLE.md`](../../REPOSITORY-LIFECYCLE.md) | Ownership, trust, release, and branch model / 归属、信任、发布与分支模型 |
| [`../../../service.json`](../../../service.json) | Service identity and extension points / 服务身份与扩展点 |
| [`../../../training/core/README.md`](../../../training/core/README.md) | Existing core package boundary and kernel notes / 现有核心包边界与内核说明 |
| [Plugins LLaMA Factory README](https://github.com/DoHorizon-AI/Cyrene-Plugins-Official/blob/3afbac4d386eb7a27f6778149187884820c0b7f6/plugins/training/llama-factory/README.md) | Plugin backend usage and product workflow / 插件后端用法与产品工作流 |

## Suggested reading / 推荐阅读

1. `docs/architecture/overview.md` — understand ownership and lifecycle.
2. `core/README.md` — follow the canonical runtime.
3. `plugin/README.md` — understand the integrated backend.
4. `docs/architecture/tool-system.md` — inspect adapter and executor boundaries.
5. `docs/API.md` — verify contract names and statuses.

1. `docs/architecture/overview.md` —— 理解归属与生命周期。
2. `core/README.md` —— 跟踪标准运行时。
3. `plugin/README.md` —— 理解集成后端。
4. `docs/architecture/tool-system.md` —— 查看适配器与执行器边界。
5. `docs/API.md` —— 核对契约名称与状态。
