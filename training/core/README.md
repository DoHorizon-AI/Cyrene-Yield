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
`docs/KERNEL_CANONICAL_BASE.md`. Production `CyreneKernelExecutor` must not
use `cy.llm.AgentService` / `ExecuteCommandStream`.

Per-attempt training configuration stays in Yield and its selected Plugin
contract. KernelAuthority receives only generic resource, lease, operation and
opaque execution identity. `InProcessKernelPort` is TEST ONLY.

每次尝试的训练配置保留在 Yield 及其选定的 Plugin 契约中。KernelAuthority 只接收
通用资源、租约、操作和不透明执行身份；`InProcessKernelPort` 仅供测试使用。
