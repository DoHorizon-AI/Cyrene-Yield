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
---

<!-- Chinese Translation / 中文翻译 -->

# Yield 训练运行时

本项目将启用 CUDA 的 PyTorch 与 LLaMA-Factory worker 环境独立锁定，不与 Yield Product service 共用环境。Bootstrap 将环境安装到一个明确的 runtime home，在不分配模型的情况下探测 CUDA，验证 package 版本，解析规范 Kernel descriptor，并写出供 Yield 使用的私有 runtime.json。

```bash
export CYRENE_TRAINER_RUNTIME_HOME=/var/lib/cyrene/yield-trainer
trainer-runtime/cyrene-trainer-runtime bootstrap
trainer-runtime/cyrene-trainer-runtime status
```

--allow-no-cuda 只用于 Azure Hosted lock 与协议检查。其输出绝不能作为规范 GPU 证据。RTX 4080 验收必须省略此参数。

| 文件 | 职责 |
|---|---|
| pyproject.toml、uv.lock | 精确的 trainer 依赖图 |
| bootstrap.py | 部署锁定环境 |
| probe.py | CUDA、package 与协议校验 |
| cyrene-trainer-runtime | 稳定的运维入口 |
