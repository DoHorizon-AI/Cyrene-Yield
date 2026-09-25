# Training Engine Disposition and Cutover Inventory (YLD-003)

## 1. Governance Context

The user selected a clean pre-public cutover: reusable training implementations
remain only in Cyrene-Plugins-Official. This ledger records local source
disposition; it is not hosted, GPU, merge, or canonical read-back evidence.

---

## 2. Current Disposition

| Surface | Disposition | Current state |
|---|---|---|
| `training/.../engines/native_transformers/` | `REMOVE` | Deleted with its local Transformers/PEFT trainer and CLI. |
| `training/.../engines/llamafactory/` | `SUPPORT` | Product adapter only; invokes `training.llama-factory.v1`. |
| `training/.../reference_preflight.py` | `REMOVE` | Deleted local analyzer/compatibility implementation. |
| `training/.../plugin_preflight.py` | `SUPPORT` | Product mappings to `model.analyzer.v1` and `compatibility.evaluator.v1`. |
| `training/.../validation/dataset_validator.py` | `REMOVE` | Deleted reusable parser/schema/quality implementation. |
| `training/.../validation/dataset_plugin.py` | `SUPPORT` | Product mapping to `tool.dataset.validator.v1`. |

---

## 3. Retained Yield Authority

Yield retains TrainingSpec/Run/Attempt/Result/ModelVersion state, validation of
Product intent, preflight gates, execution-plan reconciliation, retries,
cancellation, checkpoint/Artifact publication, and Product handoffs.

---

## 4. Acceptance Readiness Ledger

- **Current source disposition**: `CLEAN_DIRECT_PLUGIN_CUTOVER_LOCAL_ONLY`.
- **Local checks**: Product and direct-endpoint suites must pass from Yield's locked environment.
- **Not implied**: real LLaMA process/GPU, hosted CI, merge, or canonical acceptance.
---

<!-- Chinese Translation / 中文翻译 -->

# 训练引擎处置与切换清单（YLD-003）

## 1. 治理背景

用户选择在公开前完成 clean cutover：可复用训练实现只保留在 Cyrene-Plugins-Official。本清单记录本地源码处置，不是 hosted、GPU、合并或规范 read-back 证据。

---

## 2. 当前处置

| 接口 | 处置 | 当前状态 |
|---|---|---|
| training/.../engines/native_transformers/ | REMOVE | 连同本地 Transformers/PEFT trainer 和 CLI 一并删除。 |
| training/.../engines/llamafactory/ | SUPPORT | 仅保留 Product 适配器；它调用 training.llama-factory.v1。 |
| training/.../reference_preflight.py | REMOVE | 删除本地 analyzer/compatibility 实现。 |
| training/.../plugin_preflight.py | SUPPORT | Product 到 model.analyzer.v1 和 compatibility.evaluator.v1 的映射。 |
| training/.../validation/dataset_validator.py | REMOVE | 删除可复用的 parser/schema/quality 实现。 |
| training/.../validation/dataset_plugin.py | SUPPORT | Product 到 tool.dataset.validator.v1 的映射。 |

---

## 3. Yield 保留的权威

Yield 保留 TrainingSpec/Run/Attempt/Result/ModelVersion 状态、Product 意图校验、preflight 门禁、execution-plan reconciliation、重试、取消、checkpoint/Artifact 发布和 Product 交接。

---

## 4. 验收准备状态

- **当前源码处置**：CLEAN_DIRECT_PLUGIN_CUTOVER_LOCAL_ONLY。
- **本地检查**：Product 与直连端点测试必须通过 Yield 锁定的环境。
- **不代表**：真实 LLaMA 进程/GPU、hosted CI、合并或规范验收。
