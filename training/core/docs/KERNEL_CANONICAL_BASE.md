# Kernel canonical base

The immutable generic control-plane input for this Product revision is:

- repository: Cyrene-Platform
- commit: c59be6f2bd82489fbe933dadff84fc589e00afd9

Do not add training payloads, Plugin method schemas, argv or environment fields
to Platform contracts. Yield and the selected Plugin own those values.

Production `KernelTrainingExecutor` talks to `KernelAuthorityService`:

AcquireLease → StartWorker(execution_ref) → CancelOperation / StopWorker

Yield has no in-process or local execution fallback. Missing Platform authority
is reported as `YIELD_EXECUTION_NOT_CONFIGURED`.
---

<!-- Chinese Translation / 中文翻译 -->

# Kernel 规范基线

此 Product 修订版使用的不可变通用控制平面输入为：

- repository：Cyrene-Platform
- commit：c59be6f2bd82489fbe933dadff84fc589e00afd9

不得在 Platform 契约中加入训练 payload、Plugin 方法 schema、argv 或环境字段。这些值由 Yield 和选定的 Plugin 拥有。

生产环境中的 KernelTrainingExecutor 与 KernelAuthorityService 通信：

AcquireLease → StartWorker(execution_ref) → CancelOperation / StopWorker

Yield 没有进程内或本地执行回退。缺少 Platform 权威时会报告 YIELD_EXECUTION_NOT_CONFIGURED。
