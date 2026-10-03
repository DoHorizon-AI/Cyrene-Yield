# Yield Documentation

Yield 文档索引 / Documentation index for Yield.

## Repository scope / 仓库范围

Yield owns training intent, run/attempt/result state, policy, reconciliation, checkpoint publication, and Product handoffs. Concrete training engines and reusable dataset validation are Plugins-owned capabilities reached through fail-closed direct adapters.

Yield 负责训练意图、运行/尝试/结果状态、策略、协调、检查点发布与 Product 交接。具体训练引擎与可复用数据集校验由 Plugins 能力实现，并通过故障关闭的直连适配器调用。

This documentation describes the clean-root source payload. The former complete
history and excluded LLaMA Factory demo datasets are retained only in the
private `Cyrene-Yield-history-archive`; they are not public release inputs.

本文档说明 clean-root 源码内容。原完整历史与排除的 LLaMA Factory demo 数据集仅
保留在私有的 `Cyrene-Yield-history-archive` 中，不属于公开 release 输入。

## Reading map / 阅读地图

| Path | Responsibility / 职责 |
|---|---|
| [`architecture/overview.md`](architecture/overview.md) | Training lifecycle, runtime topology, and authority boundaries / 训练生命周期、运行时拓扑与权威边界 |
| [`architecture/tool-system.md`](architecture/tool-system.md) | Engine seams, executors, preflight, and checkpoint flow / 引擎接缝、执行器、前置校验与检查点流程 |
| [`architecture/mcp-integration.md`](architecture/mcp-integration.md) | Protocol-adapter boundary for training operations / 训练操作的协议适配边界 |
| [`modules/yield/README.md`](modules/yield/README.md) | Core and plugin module map / 核心与插件模块地图 |
| [`glossary.md`](glossary.md) | Bilingual training vocabulary / 双语训练术语 |
| [`faq.md`](faq.md) | Common questions and troubleshooting / 常见问题与排障指南 |
| [`API.md`](API.md) | Product/API contract and state model / 产品 API 契约与状态模型 |
| [`REPOSITORY-LIFECYCLE.md`](REPOSITORY-LIFECYCLE.md) | Repository governance and release boundaries / 仓库治理与发布边界 |
| [`DEPENDENCIES.md`](DEPENDENCIES.md) | Dependency license record and SBOM procedure / 依赖许可证记录与 SBOM 流程 |
| [`logging-and-errors.md`](logging-and-errors.md) | Cross-repository logging, error codes, and diagnostics specification / 跨仓日志、错误码与诊断规范 (草案 v0.1) |

## Suggested order / 推荐顺序

1. Read [`architecture/overview.md`](architecture/overview.md) for ownership and lifecycle.
2. Read [`architecture/tool-system.md`](architecture/tool-system.md) for runtime seams.
3. Read [`modules/yield/README.md`](modules/yield/README.md), then its core/plugin guides.
4. Use [`API.md`](API.md), [`glossary.md`](glossary.md), and [`faq.md`](faq.md) as references.

1. 先阅读 [`architecture/overview.md`](architecture/overview.md)，理解职责与生命周期。
2. 再阅读 [`architecture/tool-system.md`](architecture/tool-system.md)，理解运行时接缝。
3. 阅读 [`modules/yield/README.md`](modules/yield/README.md)，再阅读核心/插件指南。
4. 按需查阅 [`API.md`](API.md)、[`glossary.md`](glossary.md) 与 [`faq.md`](faq.md)。

## Change boundary / 变更边界

Architecture changes must preserve this owner split and the repository's independent build gates.

架构变更必须保持上述权威分工与仓库独立构建门禁。
---

<!-- Chinese Translation / 中文翻译 -->

# Yield 文档

Yield 文档索引。

## 仓库范围

Yield 负责训练意图、run/attempt/result 状态、策略、reconciliation、checkpoint 发布和 Product 交接。具体训练引擎和可复用的数据集校验是由 Plugins 所有的能力，通过 fail-closed 直连适配器调用。

本文档说明 clean-root 源码内容。此前完整历史和排除的 LLaMA Factory 演示数据集仅保留在私有 Cyrene-Yield-history-archive 中，不属于公开 release 输入。

## 阅读地图

| 路径 | 职责 |
|---|---|
| architecture/overview.md | 训练生命周期、runtime 拓扑与权威边界 |
| architecture/tool-system.md | 引擎接缝、执行器、preflight 与 checkpoint 流程 |
| architecture/mcp-integration.md | 训练操作的协议适配边界 |
| modules/yield/README.md | Core 与 Plugin 模块地图 |
| glossary.md | 双语训练术语 |
| faq.md | 常见问题与排障指南 |
| API.md | Product/API 契约与状态模型 |
| REPOSITORY-LIFECYCLE.md | 仓库治理与发布边界 |
| DEPENDENCIES.md | 依赖许可证记录与 SBOM 流程 |
| logging-and-errors.md | 跨仓日志、错误码与诊断规范（草案 v0.1） |

## 推荐阅读顺序

1. 阅读 architecture/overview.md，了解职责与生命周期。
2. 阅读 architecture/tool-system.md，了解 runtime 接缝。
3. 阅读 modules/yield/README.md，然后阅读 core 和 plugin 指南。
4. 将 API.md、glossary.md 和 faq.md 用作参考。

## 变更边界

架构变更必须保持上述 owner 分工和仓库独立构建门禁。
