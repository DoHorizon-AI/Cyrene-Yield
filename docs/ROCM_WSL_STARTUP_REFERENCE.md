# ROCm/WSL trainer preview reference / ROCm/WSL 训练器预览引用

## Exact dependency chain / 精确依赖链

| Owner / 所有者 | Revision / 修订版 |
| --- | --- |
| External trainer / 外部训练器 | `Icy-Lunar/LlamaFactory@8c392ce83c6410a1679099e1799e02d7d150c3b7` |
| Capability adapter / 能力适配器 | `Cyrene-Plugins-Official@bf10bb5759fe5477438249e56ac5d864734f89cc`, `cyrene.training.llama-factory` version `0.2.2` |
| Product / 产品 | This dependent PR targets `Cyrene-Yield/develop`; no trainer implementation is copied here. / 本依赖 PR 面向 develop，不复制训练器实现。 |

Dependencies under review: [trainer PR #1](https://github.com/Icy-Lunar/LlamaFactory/pull/1)
and [Plugins PR #164](https://github.com/DoHorizon-AI/Cyrene-Plugins-Official/pull/164).
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

The [trainer preview ZIP](https://github.com/Icy-Lunar/LlamaFactory/releases/tag/preview-rocm-wsl-startup-20261105-8c392ce8)
has SHA-256 `003160fd5397a16c63c715e62c85ceae0662ae9a10cac6c23a27399dd9b38983`.
This reference update does not install that external trainer automatically. The
operator deploys it separately; Platform still owns devices/process lifetime and
Yield still owns training intent/run state. `trainer-runtime/uv.lock` is unchanged.

上述训练器 ZIP 的摘要同上。更新本产品引用不会自动安装外部训练器，仍需操作者独立部署。
Platform 保持设备与进程生命周期所有权，Yield 保持训练意图和运行状态所有权，独立 CUDA
环境的 `trainer-runtime/uv.lock` 不变。

Trainer focused local tests: **245 passed, 1 skipped**. Both YAML/JSON tiny CPU runs loaded
weights, trained LoRA, evaluated and saved a checkpoint. Plugin behavior/TCK/package
producer tests: **19 passed**. Real ROCm/WSL, CUDA and XPU acceptance for this trainer
revision: **NOT_RUN**. Hosted CI, review and merge are separate gates. The source
follow-up fixes the stale `EngineName`/`infer_backend` check, license headers and
pytest import path, and prepares local fixtures for legacy integration tests without
weakening the production local-only loader. The complete matrix is rerunning;
do not treat the preview as merge-ready or hardware-certified.

训练器本地专项 245 通过、1 跳过，YAML/JSON 小模型 CPU 均完成权重加载、LoRA、训练、验证与保存。
Plugin 行为/TCK/发布生成器测试 19 通过。此训练器版本的 ROCm/WSL、CUDA、XPU 实机验收为
**NOT_RUN**；Hosted CI、评审与合并分别确认。源码已修复失效的 `EngineName`/`infer_backend`
检查、许可证头与 pytest 导入路径，并让遗留集成测试先准备本地文件，不放宽正式加载限制。
完整矩阵重新运行中，不把预览视为可合并或已经通过硬件认证。
