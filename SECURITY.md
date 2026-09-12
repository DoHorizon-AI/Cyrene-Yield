# Security policy / 安全政策

## Reporting a vulnerability / 报告漏洞

Please report suspected vulnerabilities privately through a GitHub Security
Advisory after this repository is made public, or through the DoHorizon security
contact provided by the repository maintainers. Do not open a public issue with
an unpatched vulnerability, credentials, tenant data, model weights, or a full
exploit.

仓库公开后，请通过 GitHub Security Advisory 私下报告疑似漏洞，或通过仓库
维护者提供的 DoHorizon 安全联系方式报告。不要在公开 Issue 中披露未修复漏洞、
凭证、租户数据、模型权重或完整利用代码。

Include the affected commit or package version, deployment mode, operating
system, a minimal reproduction, and the expected and observed behavior. Redact
all secrets and personal data before sending the report.

报告请包含受影响的提交或包版本、部署模式、操作系统、最小复现步骤、预期行为
与实际行为。发送前请删除所有秘密和个人数据。

## Supported versions / 支持版本

This project is pre-1.0. Security fixes are developed on the default `main`
branch and are best-effort for released tags. There is no promise of a security
support window until a release policy is published.

本项目尚未达到 1.0。安全修复以默认 `main` 分支为主，并尽力回溯到已发布标签。
在正式发布支持政策前，不承诺固定的安全支持周期。

## Scope and limits / 范围与限制

Yield owns training intent, run/attempt state, policy, reconciliation,
checkpoint publication, and Product handoffs. Platform owns generic process
supervision, resource leases, and hardware facts; Plugins own concrete engine
and dataset implementations. The local process and trainer-runtime helpers do
not provide hostile-code containment or a complete multi-tenant boundary.

Yield 负责训练意图、运行/尝试状态、策略、协调、检查点发布与 Product 交接。
Platform 负责通用进程监管、资源租约与硬件事实；Plugins 负责具体引擎与数据集实现。
本地进程与 trainer-runtime 辅助工具不提供恶意代码隔离或完整多租户边界。

CUDA, PyTorch, NVIDIA runtime components, model weights, datasets, and upstream
LLaMA-Factory material have separate provenance and license obligations. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) before redistribution.

CUDA、PyTorch、NVIDIA runtime 组件、模型权重、数据集与上游 LLaMA-Factory 材料有
独立的溯源和许可证义务。再分发前请阅读 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
