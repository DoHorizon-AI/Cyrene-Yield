# FAQ and troubleshooting / 常见问题与排障

## Which component owns training job status? / 哪个组件负责训练作业状态？

Yield's product runtime coordinates `TrainingRun` and `TrainingAttempt`, while durable control-plane state follows the Platform contract. An engine adapter or WebUI must not silently become a second status authority.

Yield 产品运行时协调 `TrainingRun` 与 `TrainingAttempt`，持久控制平面状态遵循 Platform 契约。引擎适配器或 WebUI 不能静默成为第二个状态权威。

## What is the safe execution path? / 安全执行路径是什么？

Follow `TrainingSpec → preflight → tiny dry run → workload staging → TrainingRuntime → engine adapter → checkpoint verification`. A direct engine call may be useful for development, but it is not the product lifecycle path.

遵循 `TrainingSpec → 前置校验 → 小型试运行 → 工作负载暂存 → TrainingRuntime → 引擎适配器 → 检查点验证`。直接调用引擎可用于开发，但不是产品生命周期路径。

## Why can a configuration pass parsing but fail preflight? / 为什么配置能解析却会在前置校验失败？

Parsing checks shape and types. Preflight also checks model metadata, dataset compatibility, hardware facts, environment, memory estimates, and policy gates.

解析只检查结构与类型；前置校验还会检查模型元数据、数据集兼容性、硬件事实、环境、显存估算与策略门禁。

## Who owns the dataset? / 谁负责数据集？

Catalyst owns ingestion and raw cleaning. Yield consumes a `DatasetRef` and owns training-specific sampling or preprocessing required by its engine contract.

Catalyst 负责数据摄取与原始清洗。Yield 消费 `DatasetRef`，并负责引擎契约要求的训练专属采样或预处理。

## Why is `InProcessKernelPort` restricted? / 为什么限制 `InProcessKernelPort`？

It is a test-only convenience boundary. Production execution must use the canonical Platform worker/operation contract so resource leases, cancellation, and lifecycle evidence remain authoritative.

它是仅供测试的便利边界。生产执行必须使用标准 Platform worker/operation 契约，确保资源租约、取消与生命周期证据保持权威。

## Where should LLaMA Factory changes go? / LLaMA Factory 变更应放在哪里？

Changes specific to the integrated backend belong under `Cyrene-Plugins-Official/plugins/training/llama-factory`. Product lifecycle behavior belongs in `training/core`; do not duplicate `TrainingRuntime` state inside the backend.

集成后端专属变更放在 `Cyrene-Plugins-Official/plugins/training/llama-factory`。产品生命周期行为放在 `training/core`；不要在后端复制 `TrainingRuntime` 状态。

## Why is the full test suite not run for comment-only work? / 为什么注释任务不运行完整测试？

This pass intentionally changes comments and Markdown only. The relevant evidence is a scope audit, whitespace check, and review that no non-comment source lines or configuration files changed; functional tests remain the next step for behavior changes.

本轮有意只改注释与 Markdown。相关证据是范围审计、空白检查，以及确认没有非注释源码行或配置文件变更；行为变更仍需另行运行功能测试。

## What should not be added to Yield? / Yield 不应加入什么？

Do not add raw dataset ownership, model serving, evaluation, generic process supervision, or canonical hardware probing. Those responsibilities belong to Catalyst, Reactor, Echo, Platform Kernel, and Platform Node Agent.

不要在 Yield 中加入原始数据集归属、模型服务、评估、通用进程监管或标准硬件探测；这些职责分别归属于 Catalyst、Reactor、Echo、Platform Kernel 与 Platform Node Agent。
