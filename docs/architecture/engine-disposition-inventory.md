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
