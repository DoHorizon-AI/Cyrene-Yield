# Contributing to Cyrene-Yield / 参与 Cyrene-Yield 贡献

Thank you for contributing to the Yield Product. Read [`LICENSE`](LICENSE),
[`SECURITY.md`](SECURITY.md), and the dependency/SBOM record in
[`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md) before opening a change.

感谢参与 Yield Product。提交修改前，请阅读 [`LICENSE`](LICENSE)、
[`SECURITY.md`](SECURITY.md) 以及 [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md)
中的依赖与 SBOM 记录。

Please also follow the [Cyrene Contribution Workflow](https://github.com/DoHorizon-AI/Cyrene-Platform/blob/main/docs/governance/contribution-workflow.md).

同时请遵循 [Cyrene Contribution Workflow](https://github.com/DoHorizon-AI/Cyrene-Platform/blob/main/docs/governance/contribution-workflow.md)。

## Scope / 范围

Yield owns TrainingSpec, TrainingRun/Attempt state, training policy,
reconciliation, checkpoint publication, and Product handoffs. Concrete LLaMA
Factory, dataset-validation, model-analysis, and compatibility implementations
are Plugins-owned. The checked-in `trainer-runtime` is a separately locked
CUDA environment bootstrap/probe, not a claim that a GPU training workload has
been accepted.

Yield 负责 TrainingSpec、TrainingRun/Attempt 状态、训练策略、协调、检查点发布与
Product 交接。具体 LLaMA Factory、数据集校验、模型分析与兼容性实现由 Plugins
所有。仓库内的 `trainer-runtime` 是独立锁定的 CUDA 环境部署/探测工具，不表示 GPU
训练工作负载已经完成验收。

## Local setup and checks / 本地设置与检查

```bash
uv sync --locked --extra dev
uv run ruff check training/core/src training/core/tests sdk/python/cyrene_yield_contracts/src
uv run ruff format --check training/core/tests/conftest.py scripts/project_artifact_ref_schema.py scripts/generate_kernel_descriptor.py contracts/product/v1/tests/test_contract.py
uv run mypy
uv run pytest -q training/core/tests contracts/product/v1/tests
uv lock --project trainer-runtime --check
python -m py_compile trainer-runtime/bootstrap.py trainer-runtime/probe.py
```

The full upstream LLaMA-Factory test suite and real CUDA/GPU lifecycle are not
part of the CPU-only Product check. Report them as `NOT_RUN` unless an exact
runtime and hosted acceptance run produced evidence.

完整的上游 LLaMA-Factory 测试套件以及真实 CUDA/GPU 生命周期不属于仅 CPU 的
Product 检查。除非精确运行时与 Hosted 验收产生证据，否则必须标记为 `NOT_RUN`。

## Change and review rules / 修改与评审规则

- Keep Product state and policy in Yield; do not add a second engine or dataset authority.
- Keep `uv.lock` and `trainer-runtime/uv.lock` synchronized with dependency changes.
- Update [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and the SBOM entry for every dependency or upstream snapshot change.
- New or substantially changed files under `docs/` must include English and Chinese text.
- Never commit credentials, model weights, datasets, runtime homes, generated artifacts, or machine-specific absolute paths.
- Open focused pull requests against `main` and distinguish local, hosted, real-GPU, merged, and unrun evidence. The clean-root `main` is the development base; the private history archive is not.

- Product 状态与策略必须留在 Yield；不得新增第二套引擎或数据集权威。
- 依赖变更必须同步 `uv.lock` 与 `trainer-runtime/uv.lock`。
- 每次依赖或上游快照变化都要更新 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)
  与 SBOM 入口。
- `docs/` 下新增或大幅修改的文件必须同时包含英文和中文。
- 不得提交凭证、模型权重、数据集、runtime home、生成制品或机器相关绝对路径。
- 向 `main` 提交聚焦 PR，并区分本地、Hosted、真实 GPU、合并与未运行证据。clean-root
  `main` 是开发基线；私有历史归档不是开发基线。
