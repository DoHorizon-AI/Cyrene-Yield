# Repository Lifecycle: Cyrene-Yield

This document provides self-contained lifecycle, boundary, and authority specifications for **Cyrene-Yield**.

---

## 1. Repository Purpose & Ownership
**Cyrene-Yield** is classified as **`PUBLIC_PRODUCT`** with a desired publication
visibility of **`public`**. This clean-root source payload becomes the canonical
public history at the parentless `main` root commit. The former complete history
is retained only in the private `Cyrene-Yield-history-archive`; it is not a
public source, dependency, or release input. The live GitHub repository remains
**private** until the owner performs the visibility change; this documentation
change does not change hosting visibility.

**Cyrene-Yield** 分类为 **`PUBLIC_PRODUCT`**，目标公开可见性为 **public**。本
clean-root 源码内容将在无父 `main` 根提交处成为公开规范历史。原完整历史仅保留在
私有的 `Cyrene-Yield-history-archive` 中，不属于公开源码、依赖或 release 输入。在
owner 实际切换前，GitHub 上的仓库仍为 **private**；本文档不会改变托管可见性。

### What This Repository OWNS:
- Model training product semantics & TrainingRun state
- TrainingSpec compilation to ExecutionPlan
- Epoch history, metric tracking & hyperparameter tuning

### What This Repository DOES NOT OWN:
- Generic OS process lifecycles or GPU cgroups
- Concrete training engine internals

---

## 2. Classification & Release Units
- **Lifecycle Class**: `PUBLIC_PRODUCT`
- **Source Owner**: Cyrene Training Product Team
- **Independent Build Unit**: `Yes` (Build tools: pyproject)
- **Package / Artifact Units**: cyrene-yield
- **Deployable Unit**: `Yes`
- **Product Unit**: `Yes`
- **User Distribution Unit**: `Yes (component/API package; no release archive currently)`
- **Multi-Repository Dependency**: `Yes`

---

## 3. Authorities & Delivery Boundaries
- **CI Authority**: `github` (automatic source and contract checks in GitHub Actions; Azure is manual)
- **Release Role**: `COMPONENT_RELEASE`
- **Release Authority**: `github_releases` (release automation is not configured)
- **Deployment Authority**: `dohorizon_azure`
- **Distribution Profiles**: `training`, `full`

---

## 4. Public / Private Trust Boundary & Access Matrix
- **Public / Private Invariant**: The target source transition is strictly `PRIVATE -> PUBLIC`; after publication, public code must not import or require private code.
- **Community Contributor**: Full access to public source, local verification, and public PR CI. Requires **zero** private tokens or Azure credentials.
- **Public Maintainer**: Review and merge PRs; releases public component artifacts without needing Azure DevOps.
- **Internal / Delivery Maintainer**: Azure DevOps pipelines are reserved for internal DoHorizon delivery and private release orchestration.

---

## 5. Participation in a Complete Cyrene Distribution
This repository does **not** distribute standalone release zip files directly to general end users. Instead, its verified component artifacts are referenced by exact commit and digest in the official **Cyrene Distribution ReleaseLock** (BOM) under the `training`, `full` profile(s).

---

## 6. Public-readiness gates / 公开准备门禁

The pinned Platform revision is public, but the Plugins revision
`c3f75689ebb10b2e07b3816310e768d74ae6cc10` is currently private and several
owner package manifests do not declare a license. A public release therefore
requires an anonymously reachable, license-reviewed dependency closure and a
fresh lockfile. The current repository policy records this as
`public_requires_private: true`.

Platform 锁定修订版已公开，但 Plugins 修订版
`c3f75689ebb10b2e07b3816310e768d74ae6cc10` 当前仍为 private，且多个 owner 包
manifest 未声明许可证。因此公开发布前必须取得可匿名访问且完成许可证审查的依赖
闭包，并刷新锁文件。当前 repository policy 以
`public_requires_private: true` 记录该事实。

Automatic GitHub checks cover the clean Product core and contract paths. The
Azure pipeline is manual and its GPU branch is opt-in; `NOT_RUN` is not a pass.
Publication still needs exact-SHA hosted CI, dependency/SBOM review, release
tagging from `main`, and canonical remote read-back.

GitHub 自动检查覆盖干净 Product core 与契约路径。Azure pipeline 为手动执行，GPU
分支需要显式启用；`NOT_RUN` 不是通过。公开发布仍需 exact-SHA hosted CI、依赖与
SBOM 审查、从 `main` 创建 release tag 以及 canonical remote read-back。

The historical LLaMA Factory demo datasets under
`plugins/llama-factory-training/data` are intentionally excluded from this
clean-root source payload and are not approved for public redistribution.
Source visibility does not grant data or model rights; binary distribution adds
the release SBOM and upstream-license gates described in
[`docs/DEPENDENCIES.md`](DEPENDENCIES.md).

历史 LLaMA Factory demo 数据集（`plugins/llama-factory-training/data`）已明确排除在
本 clean-root 源码内容之外，也未获准公开再分发。源码可见性不会授予数据或模型权利；
二进制分发还需要 [`docs/DEPENDENCIES.md`](DEPENDENCIES.md) 中说明的 release SBOM
与上游许可证门禁。

## 7. Verification & Governance Links
- **Local Verification**: `uv sync --locked --extra dev`, then `uv run --no-sync ruff check training/core/src training/core/tests sdk/python/cyrene_yield_contracts/src`, `uv run --no-sync mypy`, and `uv run --no-sync pytest training/core/tests/`. Validate the OpenAPI document with `openapi-spec-validator` as shown in CI.
- **Dependency and SBOM Record**: See [`docs/DEPENDENCIES.md`](DEPENDENCIES.md) and [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).
- **Canonical Architecture Docs**: See [`Cyrene-Platform/docs/start-here/00-what-is-cyrene.md`](https://github.com/DoHorizon-AI/Cyrene-Platform/blob/main/docs/start-here/00-what-is-cyrene.md)
- **Release Topology**: See [`Cyrene-Platform/docs/release/release-topology.md`](https://github.com/DoHorizon-AI/Cyrene-Platform/blob/main/docs/release/release-topology.md)
- **CI Trust Model**: See [`Cyrene-Platform/docs/governance/ci-trust-model.md`](https://github.com/DoHorizon-AI/Cyrene-Platform/blob/main/docs/governance/ci-trust-model.md)

## 8. Versioning & Tag Strategy
- **Versioning Scheme**: `semver` (SemVer)
- **Version Scope**: `repository`
- **Tag Strategy**: `repository`
- **Canonical Tag Pattern**: `v{version}`
- **Tag Immutability**: Published tags are permanent and immutable. Defective releases require patch increments.

## 9. Branch Model & Promotion
- **Canonical Branch (`main`)**: The clean-root default branch and the base for daily development and pull requests. It must remain green.
- **Working branches**: Feature and fix branches are short-lived and merge back to `main` through review.
- **Release Source**: Official component releases and tags are created strictly from `main`.

## 10. Publication and evidence boundaries / 公开与证据边界

Public source visibility, binary distribution, hosted CI, and local verification
are separate gates. A local CPU test does not prove real CUDA acceptance; a
source repository's Apache-2.0 grant does not relicense Plugins, PyTorch, CUDA,
NVIDIA components, models, datasets, or upstream LLaMA Factory material.

公开源码可见性、二进制分发、Hosted CI 与本地验证是彼此独立的门禁。本地 CPU 测试
不代表真实 CUDA 验收；本仓库的 Apache-2.0 授权不会替 Plugins、PyTorch、CUDA、NVIDIA
组件、模型、数据集或上游 LLaMA Factory 材料重新授予许可证。
