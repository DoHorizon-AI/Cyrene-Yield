# Dataset Validation Authority Specification (YLD-002)

## 1. Governance Purpose

Under the **Services Standardization and Decoupling Plan (`YLD-002`)**:
1. Yield establishes an unambiguous authority boundary for training admission.
2. Product invariants required to create or run a training attempt remain in Yield.
3. Dataset versioning, preparation, splitting, storage, and lineage authority belong to Catalyst (`DatasetVersion`).
4. Reusable format parsing, schema validation, bounded sampling, and quality metrics belong to the Plugins-owned `tool.dataset.validator.v1` capability.
5. Yield consumes the capability through the Plugins-owned direct runtime and a Platform-resolved opaque `connection_ref`; missing or invalid bindings fail closed.

---

## 2. Invariants Owned by Yield

Yield owns the immediate Product preconditions for model training:

- a dataset reference/path is present and points to the staged, non-empty file selected for the attempt;
- model, output, resume-checkpoint, and training-parameter intent is internally consistent;
- the returned Plugin result is well-typed and reports a valid staged input;
- a missing endpoint, transport error, protocol mismatch, or invalid result blocks the attempt.

Yield does not parse JSONL/JSON/CSV/Parquet rows or implement instruction,
conversation, ShareGPT, sampling, error-cap, or quality algorithms. Those live in
`Cyrene-Plugins-Official/plugins/tools/dataset-validator`.

---

## 3. Separation from Upstream and Plugins Authorities

| Concern | Authority | Interaction Model |
| --- | --- | --- |
| **Dataset Versioning & Management** | **Catalyst** | Catalyst manages `DatasetVersion`, dataset metadata, splits, and quality metrics. It hands off to Yield via public `CreateTrainingDraft` contract artifacts. |
| **Training Input Admission** | **Yield** | Yield combines Product-owned request/path/parameter invariants with the typed Plugin verdict before starting an attempt. |
| **Generic Dataset Validation** | **Plugins** | `tool.dataset.validator.v1` owns parsing, schema recognition, bounded diagnostics, samples, and quality metrics. |

The production binding is `CYRENE_DATASET_VALIDATOR_CONNECTION_REF`. The
adapter is `training/core/src/cy_exec/training/validation/dataset_plugin.py`;
there is no local algorithm fallback.
