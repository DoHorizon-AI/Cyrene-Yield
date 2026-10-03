# Engine Isolation and LLaMA Seam Specification (YLD-001)

## 1. Context and Governance Purpose

Under the **Services Standardization and Decoupling Plan (`YLD-001`)**:
1. Yield consumes the versioned `training.llama-factory.v1` capability seam.
2. Yield fails closed when the external Plugin endpoint or runtime SDK is absent.
3. The former in-tree `native_transformers` engine has been deleted; there is no compatibility profile or local fallback.
4. Concrete LLaMA Factory source and its guided WebUI/CLI live only in `Cyrene-Plugins-Official`.

---

## 2. LLaMA Seam Freeze (`training.llama-factory.v1`)

The LLaMA Factory engine adapter communicates through the Direct Plugin RPC boundary:
- **Capability ID**: `training.llama-factory.v1`
- **Interface Version**: `1`
- **Wire Methods**:
  - `inspect`: Retrieves engine availability, version, supported strategies, and finetune types.
  - `compile`: Translates a canonical `TrainingSpec` into a `TrainingLaunchSpec`.
  - `parse_event`: Parses raw training log lines into typed `TrainingEvent` stream objects.
- **Connection Resolution**:
  - Endpoint resolved via `CYRENE_LLAMA_FACTORY_CONNECTION_REF`.
  - Runtime SDK resolved via `cyrene_plugin_runtime.DirectPluginClient`.
- **Fail-Closed Semantics**:
  - If `CYRENE_LLAMA_FACTORY_CONNECTION_REF` is unset or empty, calls to resolve the connection fail closed with `RuntimeError("YIELD_PLUGIN_UNAVAILABLE: ...")`.
  - If `cyrene_plugin_runtime` is missing, calls fail closed with `RuntimeError("YIELD_PLUGIN_RUNTIME_MISSING: ...")`.
  - Yield does NOT fabricate mock launches or silently fall back to unvalidated execution.

---

## 3. In-Tree Engine Disposition

`training/core/src/cy_exec/training/engines/native_transformers` is removed.
`get_engine()` exposes only the Product adapter for the Plugins-owned LLaMA
Factory capability. CI rejects reintroduction of `torch`, `transformers`,
`peft`, or `llamafactory` imports in Yield Product source.
---

<!-- Chinese Translation / 中文翻译 -->

# 引擎隔离与 LLaMA 接缝规范（YLD-001）

## 1. 背景与治理目的

根据 **Services 标准化与解耦计划（YLD-001）**：

1. Yield 消费版本化的 training.llama-factory.v1 能力接缝。
2. 如果外部 Plugin 端点或 runtime SDK 缺失，Yield 必须 fail closed。
3. 原仓库内的 native_transformers 引擎已删除；没有兼容配置或本地回退。
4. 具体 LLaMA Factory 源码及其引导式 WebUI/CLI 只位于 Cyrene-Plugins-Official。

---

## 2. LLaMA 接缝冻结（training.llama-factory.v1）

LLaMA Factory 引擎适配器通过 Direct Plugin RPC 边界通信：

- **能力 ID**：training.llama-factory.v1
- **接口版本**：1
- **Wire 方法**：
  - inspect：获取引擎可用性、版本、支持的策略与微调类型。
  - compile：将规范 TrainingSpec 转换为 TrainingLaunchSpec。
  - parse_event：把原始训练日志行解析为有类型的 TrainingEvent 流对象。
- **连接解析**：
  - 通过 CYRENE_LLAMA_FACTORY_CONNECTION_REF 解析端点。
  - 通过 cyrene_plugin_runtime.DirectPluginClient 解析 runtime SDK。
- **Fail-Closed 语义**：
  - 若 CYRENE_LLAMA_FACTORY_CONNECTION_REF 未设置或为空，解析连接的调用会 fail closed，并抛出 RuntimeError("YIELD_PLUGIN_UNAVAILABLE: ...")。
  - 若缺少 cyrene_plugin_runtime，调用会 fail closed，并抛出 RuntimeError("YIELD_PLUGIN_RUNTIME_MISSING: ...")。
  - Yield 不会伪造 mock launch，也不会静默回退到未经校验的执行路径。

---

## 3. 仓库内引擎处置

training/core/src/cy_exec/training/engines/native_transformers 已删除。get_engine() 只公开 Plugins 所有的 LLaMA Factory 能力之 Product 适配器。CI 会拒绝在 Yield Product 源码中重新引入 torch、transformers、peft 或 llamafactory 导入。
