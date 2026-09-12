# Yield trainer runtime / Yield 训练运行时

This project locks the CUDA-enabled PyTorch and LLaMA-Factory worker environment
independently from the Yield Product service. Bootstrap installs it under one
explicit runtime home, probes CUDA without allocating a model, validates package
versions, parses the canonical Kernel descriptor, and writes a private
`runtime.json` consumed by Yield.

本项目把 CUDA PyTorch 与 LLaMA-Factory Worker 环境独立锁定。Bootstrap 将环境安装到
显式 runtime home，在不加载模型的情况下探测 CUDA，校验包版本与 Kernel descriptor，
并生成供 Yield 消费的私有 `runtime.json`。

```bash
export CYRENE_TRAINER_RUNTIME_HOME=/var/lib/cyrene/yield-trainer
trainer-runtime/cyrene-trainer-runtime bootstrap
trainer-runtime/cyrene-trainer-runtime status
```

`--allow-no-cuda` exists only for Azure Hosted lock and protocol checks. Its
output is never canonical GPU evidence. RTX 4080 acceptance must omit that flag.

`--allow-no-cuda` 仅用于 Azure Hosted 的 lock 与协议检查，其结果不能作为标准 GPU
证据。RTX 4080 验收不得使用该参数。

| File | Responsibility |
| --- | --- |
| `pyproject.toml`, `uv.lock` | Exact trainer dependency graph / 精确依赖图 |
| `bootstrap.py` | Locked environment materialization / 锁定环境部署 |
| `probe.py` | CUDA, package and protocol validation / CUDA、包与协议校验 |
| `cyrene-trainer-runtime` | Stable operator entrypoint / 固定运维入口 |
