# ROCm/WSL trainer preview reference / ROCm/WSL 训练器预览引用

## Exact dependency chain / 精确依赖链

| Owner / 所有者 | Revision / 修订版 |
| --- | --- |
| External trainer / 外部训练器 | `Icy-Lunar/LlamaFactory@1cf21a11e7375cf64e56a7092f9ff3132efc0ad6` |
| Capability adapter / 能力适配器 | `Cyrene-Plugins-Official@6b4e8d9402b12808dc8310d14c59ea5fa0f71bb3`, `cyrene.training.llama-factory` version `0.2.3` |
| Product / 产品 | This dependent PR targets `Cyrene-Yield/develop`; no trainer implementation is copied here. / 本依赖 PR 面向 develop，不复制训练器实现。 |

Dependencies under review: [trainer PR #1](https://github.com/Icy-Lunar/LlamaFactory/pull/1)
and [Plugins PR #165](https://github.com/DoHorizon-AI/Cyrene-Plugins-Official/pull/165).
The pinned commits are public immutable Git identities, but review/merge and hosted
acceptance are not implied by reachability. Keep this Product PR draft until the
upstream gates are satisfied; reconcile the final integrated Plugins revision before merge.

依赖上述训练器与 Plugins PR。锁定提交已公开且 Git 标识精确，但可访问不代表已经评审、
合并或通过 Hosted 验收。本产品 PR 保持草稿，待上游门禁满足后再核对最终集成版本。

## What changed / 改进点

- Training starts before TensorBoard; an optional dashboard failure cannot block the training child.
- Liger GPU probes no longer run in WebUI form callbacks. ROCm/WSL receives single-process preprocessing and conservative DataLoader settings; CUDA/XPU dependency selection is unchanged.
- Persistent session, child and lifecycle logs expose the actual startup stage, heartbeat, bounded early-stage timeout and cancellation state.
- Missing saved configurations and the JSON configuration path used by the Plugin are handled correctly. YAML and JSON both have real tiny-model CPU smoke coverage.

- 先启动训练子进程，再启动 TensorBoard，可选看板失败不再阻塞训练。
- Liger 检测不再阻塞页面回调。仅 ROCm/WSL 使用单进程预处理和保守 DataLoader 设置，CUDA/XPU 依赖选择不变。
- 会话、子进程和生命周期日志显示实际启动阶段、心跳、早期超时及停止状态。
- 修复空配置及 Plugin 使用的 JSON 配置路径读取；YAML、JSON 均有真实小模型 CPU 测试。

## Deployment and evidence / 部署与证据

The [trainer preview ZIP](https://github.com/Icy-Lunar/LlamaFactory/releases/tag/preview-memory-calibration-20261123-1cf21a11)
has SHA-256 `48994ea5e4af5fdbade459c16a644513b6d4ebfabff012daaa717e035035210b`.
This reference update does not install that external trainer automatically. The
operator deploys it separately; Platform still owns devices/process lifetime and
Yield still owns training intent/run state. `trainer-runtime/uv.lock` is unchanged.

上述训练器 ZIP 的摘要同上。更新本产品引用不会自动安装外部训练器，仍需操作者独立部署。
Platform 保持设备与进程生命周期所有权，Yield 保持训练意图和运行状态所有权，独立 CUDA
环境的 `trainer-runtime/uv.lock` 不变。

Trainer focused local tests: **158 passed, 2 deselected**. The two Windows XPU
bitsandbytes/PyTorch Inductor import failures are not counted as passing. Plugin
behavior and TCK tests: **14 passed**. Real ROCm/WSL, CUDA and XPU acceptance for
this trainer revision: **NOT_RUN**. Hosted CI, review and merge are separate gates.
The preview adds closed-loop VRAM calibration, expanded static memory modeling,
Python reuse, and multi-backend deployment hardening; it is not hardware-certified.

训练器本地聚焦测试 158 项通过、2 项未计入；两项 Windows XPU 的
bitsandbytes/PyTorch Inductor 导入失败不标记为通过。Plugin 行为与 TCK 测试 14 项通过。
此训练器版本的 ROCm/WSL、CUDA、XPU 实机验收为 **NOT_RUN**；Hosted CI、评审与合并
分别确认。预览加入闭环显存校准、扩展静态估算、Python 复用和多后端部署加固，
不代表已通过硬件认证。
