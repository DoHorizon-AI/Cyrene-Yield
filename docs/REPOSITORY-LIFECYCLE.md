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
`3afbac4d386eb7a27f6778149187884820c0b7f6` is currently private and several
owner package manifests do not declare a license. A public release therefore
requires an anonymously reachable, license-reviewed dependency closure and a
fresh lockfile. The current repository policy records this as
`public_requires_private: true`.

Platform 锁定修订版已公开，但 Plugins 修订版
`3afbac4d386eb7a27f6778149187884820c0b7f6` 当前仍为 private，且多个 owner 包
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
---

<!-- Chinese Translation / 中文翻译 -->

# 仓库生命周期：Cyrene-Yield

本文档自包含地说明 **Cyrene-Yield** 的生命周期、边界和权威归属。

---

## 1. 仓库用途与所有权

**Cyrene-Yield** 分类为 **PUBLIC_PRODUCT**，目标发布可见性为 **public**。此 clean-root 源码内容将在无父 main 根提交处成为规范公开历史。此前的完整历史仅保留在私有的 Cyrene-Yield-history-archive 中，不属于公开源码、依赖或发布输入。在所有者实际修改可见性前，GitHub 上的实时仓库仍为 **private**；本文档的修改不会改变托管可见性。

### 本仓库拥有

- 模型训练 Product 语义与 TrainingRun 状态。
- 将 TrainingSpec 编译为 ExecutionPlan。
- Epoch 历史、指标跟踪与超参数调优。

### 本仓库不拥有

- 通用操作系统进程生命周期或 GPU cgroups。
- 具体训练引擎内部实现。

---

## 2. 分类与发布单元

- **生命周期类别**：PUBLIC_PRODUCT。
- **源码所有者**：Cyrene Training Product 团队。
- **独立构建单元**：是（构建工具：pyproject）。
- **Package / 制品单元**：cyrene-yield。
- **可部署单元**：是。
- **Product 单元**：是。
- **用户分发单元**：是（组件/API package；当前没有发布归档）。
- **多仓库依赖**：是。

---

## 3. 权威来源与交付边界

- **CI 权威来源**：github（GitHub Actions 中自动执行源码与契约检查；Azure 为手动执行）。
- **Release 角色**：COMPONENT_RELEASE。
- **Release 权威来源**：github_releases（尚未配置 release 自动化）。
- **部署权威来源**：dohorizon_azure。
- **分发配置**：training、full。

---

## 4. 公共 / 私有信任边界与访问矩阵

- **公共 / 私有不变量**：目标源码转换严格为 PRIVATE -> PUBLIC；发布后，公开代码不得导入或要求私有代码。
- **社区贡献者**：可完整访问公开源码、本地验证和公开 PR CI。完全不需要私有 token 或 Azure 凭证。
- **公开维护者**：可审查并合并 PR；无需 Azure DevOps 即可发布公开组件制品。
- **内部 / 交付维护者**：Azure DevOps pipeline 仅用于 DoHorizon 内部交付和私有 release 编排。

---

## 5. 在完整 Cyrene 分发中的参与方式

本仓库不会直接向普通终端用户分发独立 release zip 文件。经验证的组件制品会以精确提交和摘要的形式，记录在官方 **Cyrene Distribution ReleaseLock**（BOM）的 training、full 配置中。

---

## 6. 公开准备门禁

锁定的 Platform 修订版已公开，但 Plugins 修订版 3afbac4d386eb7a27f6778149187884820c0b7f6 当前为 private，且多个所有者 package manifest 未声明许可证。因此公开发布必须具备可匿名访问、已完成许可证审查的依赖闭包，并生成新的锁文件。当前仓库策略将此状态记录为 public_requires_private: true。

GitHub 自动检查覆盖干净的 Product core 和契约路径。Azure pipeline 为手动执行，其 GPU 分支需显式启用；NOT_RUN 不代表通过。发布仍需 exact-SHA hosted CI、依赖/SBOM 审查、从 main 创建 release tag，并对规范远程仓库进行 read-back。

plugins/llama-factory-training/data 下历史遗留的 LLaMA Factory 演示数据集被有意排除在此 clean-root 源码内容之外，且未获准公开再分发。源码可见性不授予数据或模型权利；二进制分发还要满足 docs/DEPENDENCIES.md 所述的 release SBOM 和上游许可证门禁。

---

## 7. 验证与治理链接

- **本地验证**：运行 uv sync --locked --extra dev，然后运行 uv run --no-sync ruff check training/core/src training/core/tests sdk/python/cyrene_yield_contracts/src、uv run --no-sync mypy 和 uv run --no-sync pytest training/core/tests/。按 CI 中的方式使用 openapi-spec-validator 验证 OpenAPI 文档。
- **依赖与 SBOM 记录**：参阅 docs/DEPENDENCIES.md 和 THIRD_PARTY_NOTICES.md。
- **规范架构文档**：参阅 Cyrene-Platform/docs/start-here/00-what-is-cyrene.md。
- **Release 拓扑**：参阅 Cyrene-Platform/docs/release/release-topology.md。
- **CI 信任模型**：参阅 Cyrene-Platform/docs/governance/ci-trust-model.md。

---

## 8. 版本与标签策略

- **版本方案**：semver（语义化版本）。
- **版本范围**：repository。
- **标签策略**：repository。
- **规范标签格式**：v{version}。
- **标签不可变性**：已发布标签永久不可变。缺陷发布必须递增补丁版本。

---

## 9. 分支模型与晋级

- **规范分支（main）**：clean-root 默认分支，也是日常开发和 pull request 的基线，必须保持绿色。
- **工作分支**：功能和修复分支应短期存在，并经过审查后合并回 main。
- **Release 源**：正式组件 release 和标签必须严格从 main 创建。

---

## 10. 发布与证据边界

公开源码可见性、二进制分发、hosted CI 和本地验证是彼此独立的门禁。本地 CPU 测试不能证明真实 CUDA 验收；本仓库的 Apache-2.0 授权不会替 Plugins、PyTorch、CUDA、NVIDIA 组件、模型、数据集或上游 LLaMA Factory 材料重新授予许可证。
