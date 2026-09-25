# Yield core training / Yield 核心训练

This directory contains Yield's Product training runtime and its hash-verified
contract projections. It owns Product intent, run/attempt state, policy,
preflight, execution coordination, checkpoint publication, and tests. Concrete
training engines and model setup/loop implementations are Plugins-owned and are
not a complete in-tree migration of the upstream LLaMA-Factory tree.

本目录包含 Yield 的 Product 训练运行时与经摘要校验的契约投影。它负责 Product
意图、运行/尝试状态、策略、前置校验、执行协调、检查点发布与测试。具体训练引擎、
模型设置与训练循环由 Plugins 所有；本目录不表示已将上游 LLaMA-Factory 完整迁移
到树内。

The generic Kernel control-plane projection is pinned to Cyrene-Platform
`c59be6f2bd82489fbe933dadff84fc589e00afd9`. See
`docs/KERNEL_CANONICAL_BASE.md`. `KernelTrainingExecutor` is the only retained
execution adapter; missing configuration fails closed.

Per-attempt training configuration stays in Yield and its selected Plugin
contract. KernelAuthority receives only generic resource, lease, operation and
opaque execution identity. Yield contains no local or in-process executor.

每次尝试的训练配置保留在 Yield 及其选定的 Plugin 契约中。KernelAuthority 只接收
通用资源、租约、操作和不透明执行身份；Yield 不包含本地或进程内执行器。
---

<!-- Chinese Translation / 中文翻译 -->

# Yield 核心训练

本目录包含 Yield Product training runtime 及其经摘要验证的契约投影。它拥有 Product 意图、run/attempt 状态、策略、preflight、执行协调、checkpoint 发布和测试。具体训练引擎、模型设置和训练循环归 Plugins 所有；本目录不表示已将上游 LLaMA-Factory 代码树完整迁入仓库。

通用 Kernel 控制平面投影固定到 Cyrene-Platform 的 c59be6f2bd82489fbe933dadff84fc589e00afd9。参见 docs/KERNEL_CANONICAL_BASE.md。KernelTrainingExecutor 是唯一保留的执行适配器；缺少配置时会 fail closed。

每次 attempt 的训练配置保留在 Yield 及所选 Plugin 契约内。KernelAuthority 只接收通用资源、租约、操作和不透明执行身份。Yield 不包含本地或进程内执行器。
