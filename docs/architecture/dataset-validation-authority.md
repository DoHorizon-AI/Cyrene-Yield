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
---

<!-- Chinese Translation / 中文翻译 -->

# 数据集校验权威规范（YLD-002）

## 1. 治理目的

根据 **Services 标准化与解耦计划（YLD-002）**：

1. Yield 为训练准入建立清晰明确的权威边界。
2. 创建或运行训练 attempt 所需的 Product 不变量由 Yield 负责。
3. 数据集版本、准备、拆分、存储与 lineage 权威属于 Catalyst（DatasetVersion）。
4. 可复用的格式解析、schema 校验、有界采样和质量指标属于 Plugins 所有的 tool.dataset.validator.v1 能力。
5. Yield 通过 Plugins 所有的 direct runtime 和 Platform 解析的不透明 connection_ref 消费该能力；缺失或无效的绑定必须 fail closed。

---

## 2. Yield 所有的不变量

Yield 拥有模型训练的直接 Product 前置条件：

- 数据集引用/路径必须存在，且指向为本次 attempt 选定的暂存后非空文件。
- 模型、输出、恢复 checkpoint 和训练参数意图必须彼此一致。
- 返回的 Plugin 结果必须符合类型，并报告有效的暂存输入。
- 端点缺失、传输错误、协议不匹配或结果无效都会阻止该 attempt。

Yield 不解析 JSONL/JSON/CSV/Parquet 行，也不实现 instruction、conversation、ShareGPT、采样、错误上限或质量算法。这些实现位于 Cyrene-Plugins-Official/plugins/tools/dataset-validator。

---

## 3. 与上游及 Plugins 权威的分工

| 关注事项 | 权威方 | 交互模式 |
|---|---|---|
| 数据集版本与管理 | Catalyst | Catalyst 管理 DatasetVersion、数据集元数据、拆分和质量指标，并通过公开 CreateTrainingDraft 契约制品交接给 Yield。 |
| 训练输入准入 | Yield | 启动 attempt 前，Yield 将 Product 所有的请求/路径/参数不变量与有类型的 Plugin 结论结合起来。 |
| 通用数据集校验 | Plugins | tool.dataset.validator.v1 负责解析、schema 识别、有界诊断、样本和质量指标。 |

生产绑定变量为 CYRENE_DATASET_VALIDATOR_CONNECTION_REF。适配器位于 training/core/src/cy_exec/training/validation/dataset_plugin.py；没有本地算法回退。
