# Third-party notices / 第三方声明

This record covers the direct runtime, development, contract, and trainer
environment dependencies declared by the repository manifests. Exact resolved
versions, source revisions, and hashes are authoritative in `uv.lock` and
`trainer-runtime/uv.lock`. This is an inventory, not a legal opinion or a grant
of rights. Transitive dependencies must be included in the release SBOM.

本记录覆盖仓库 manifest 声明的直接运行时、开发、契约与 trainer 环境依赖。精确的
解析版本、源码修订版与摘要以 `uv.lock` 和 `trainer-runtime/uv.lock` 为准。本记录
是清单，不构成法律意见，也不授予任何权利。传递依赖必须纳入 release SBOM。

The historical LLaMA Factory demo datasets formerly stored under
`plugins/llama-factory-training/data` are not dependencies of the clean-root
Product source. They were excluded because their redistribution and provenance
were not approved; the old history is retained only in the private archive.

历史曾位于 `plugins/llama-factory-training/data` 的 LLaMA Factory demo 数据集不是
clean-root Product 源码的依赖。由于其再分发与溯源未获批准，数据已排除；旧历史仅
保留在私有归档中。

## Runtime dependencies / 运行时依赖

| Package | Locked version | Source | License evidence | Use |
|---|---:|---|---|---|
| `pydantic` | `2.13.4` | PyPI | `MIT` | Product/API validation |
| `PyYAML` | `6.0.3` | PyPI | `MIT` | Configuration parsing |
| `psutil` | `7.2.2` | PyPI | `BSD-3-Clause` | Process/resource facts |
| `fastapi` | `0.141.1` | PyPI | `MIT` | HTTP API surface |
| `httpx` | `0.28.1` | PyPI | `BSD-3-Clause` | Handoff client |
| `uvicorn` | `0.52.4` | PyPI | `BSD-3-Clause` | ASGI entrypoint |
| `grpcio` | `1.83.0` | PyPI | `Apache-2.0` | Runtime RPC |
| `protobuf` | `7.36.0` | PyPI | `BSD-3-Clause` | RPC serialization |
| `cryptography` | `50.0.1` | PyPI | `Apache-2.0 OR BSD-3-Clause` | Signing and cryptographic primitives |
| `cyrene-artifacts` | `0.1.0` | Platform Git SHA `c59be6f2bd82489fbe933dadff84fc589e00afd9` | `Apache-2.0` declared by owner manifest | Artifact contract/provider |
| `cyrene-preflight` | `0.1.0` | Platform Git SHA `c59be6f2bd82489fbe933dadff84fc589e00afd9` | `Apache-2.0` declared by owner manifest | Resource-fact/preflight contract |
| `cyrene-plugin-runtime` | `0.2.0` | Plugins Git SHA `c3f75689ebb10b2e07b3816310e768d74ae6cc10` | `UNKNOWN`: owner package has no license field or nearest license file | Direct capability runtime |

## Development and contract dependencies / 开发与契约依赖

| Package | Locked version | License evidence | Use |
|---|---:|---|---|
| `pytest` | `9.1.1` | `MIT` | Unit and contract tests |
| `ruff` | `0.16.5` | `MIT` | Lint and format checks |
| `mypy` | `2.3.1` | `MIT` | Type checks |
| `hypothesis` | `6.165.10` | `MPL-2.0` | Property-based tests |
| `jsonschema` | `4.26.0` | `MIT` | Contract/schema checks |
| `openapi-spec-validator` | `0.9.0` | `Apache-2.0` | OpenAPI validation |
| `grpcio-tools` | `1.83.0` | `Apache-2.0` | Contract tooling |
| `types-PyYAML`, `types-psutil`, `types-grpcio`, `types-protobuf` | locked in `uv.lock` | Verify each wheel notice in release SBOM | Type-only development inputs |
| `cyrene-hf-model-analyzer` | `0.3.0` | `UNKNOWN`: owner package has no license field or nearest license file | Optional model-analysis capability |
| `cyrene-compat-rules` | `0.2.0` | `UNKNOWN`: owner package has no license field or nearest license file | Optional compatibility capability |
| `cyrene-dataset-validator` | `0.2.0` | `UNKNOWN`: owner package has no license field or nearest license file | Optional dataset-validation capability |

The public contract package `cyrene-yield-contracts` is Apache-2.0 under its
package manifest and is covered by the repository [`LICENSE`](LICENSE).

公开契约包 `cyrene-yield-contracts` 由其 package manifest 声明为 Apache-2.0，并受
仓库 [`LICENSE`](LICENSE) 覆盖。

## Trainer runtime and CUDA / Trainer runtime 与 CUDA

`trainer-runtime/uv.lock` separately resolves `torch==2.8.0+cu128`,
`torchaudio==2.8.0+cu128`, `torchvision==0.23.0+cu128`, `triton==3.4.0`,
the NVIDIA CUDA 12 component wheels, `grpcio==1.83.0`, and
`protobuf==7.36.0`. The PyTorch project and each CUDA/NVIDIA component's
upstream license and notice must be captured by the release SBOM. This record
does not assert that NVIDIA redistribution terms, CUDA EULA obligations, or
model/upstream licenses have been reviewed. Real CUDA acceptance is a separate
verification gate and is not implied by a lockfile or local CPU test.

`trainer-runtime/uv.lock` 单独解析 `torch==2.8.0+cu128`、
`torchaudio==2.8.0+cu128`、`torchvision==0.23.0+cu128`、`triton==3.4.0`、NVIDIA
CUDA 12 组件 wheel、`grpcio==1.83.0` 与 `protobuf==7.36.0`。PyTorch 项目以及每个
CUDA/NVIDIA 组件的上游许可证与声明必须由 release SBOM 收录。本记录不声称已经
审查 NVIDIA 再分发条款、CUDA EULA 义务或模型/上游许可证。真实 CUDA 验收是独立
门禁，lockfile 或本地 CPU 测试都不代表该验收通过。

## Upstream-derived capability / 上游衍生能力

Yield does not vendor the LLaMA Factory source. The optional
`training.llama-factory.v1` implementation is owned by Plugins at the pinned
revision above. That Plugin currently declares Apache-2.0 for its extracted
package and records upstream provenance, but the repository is private and
the other pinned Plugin package manifests are not licensed. Preserve the
upstream license, citation, and notices in the Plugin distribution; do not
infer permissions from Yield's Apache-2.0 license.

Yield 不 vendoring LLaMA Factory 源码。可选的 `training.llama-factory.v1` 实现由上方
锁定修订版的 Plugins 所有。该 Plugin 当前为提取包声明 Apache-2.0 并记录上游来源，
但仓库仍为 private，其他锁定 Plugin 包 manifest 尚未声明许可证。Plugin 发行包必须
保留上游许可证、引用信息与声明；不能从 Yield 的 Apache-2.0 许可证推断第三方权限。

## Publication blockers / 公开阻塞项

The Plugins revision is not anonymously reachable, and the unresolved
`UNKNOWN` package licenses above prevent a complete public dependency closure.
Before publication, the owner must publish or replace those immutable
packages, review the trainer/CUDA and upstream notices, refresh both lockfiles,
and attach an SPDX or CycloneDX SBOM whose digest matches the release tag.
See [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md) for the procedure.

Plugins 修订版当前不能匿名访问，上述 `UNKNOWN` 包许可证也使公开依赖闭包不完整。
公开前，owner 必须公开或替换这些不可变包，审查 trainer/CUDA 与上游声明，刷新两份
lockfile，并附上摘要与 release tag 匹配的 SPDX 或 CycloneDX SBOM。流程见
[`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md)。

Source visibility, binary distribution, and hosted CI remain separate release
decisions. This repository's Apache-2.0 license does not grant rights to
Plugins, PyTorch/CUDA/NVIDIA components, models, datasets, or upstream-derived
material.

源码可见性、二进制分发与 Hosted CI 仍是彼此独立的 release 决策。本仓库的
Apache-2.0 许可证不会授予 Plugins、PyTorch/CUDA/NVIDIA 组件、模型、数据集或上游
衍生材料任何权利。
