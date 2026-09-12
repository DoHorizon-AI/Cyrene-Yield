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
