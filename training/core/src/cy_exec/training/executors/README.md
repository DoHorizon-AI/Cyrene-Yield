# training/core/src/cy_exec/training/executors / training/core/src/cy_exec/training/executors

The single Product adapter to Platform-owned Kernel execution authority.

Product 到 Platform 所有 Kernel 执行权威的唯一适配器。

## Files / 文件

| Entry | Responsibility / 职责 |
|---|---|
| `training/core/src/cy_exec/training/executors/__init__.py` | Package initializer and public import boundary. / 包初始化与公开导入边界。 |
| `training/core/src/cy_exec/training/executors/base.py` | Product execution port, receipt projection, and stable control failure. / Product 执行端口、回执投影与稳定控制失败。 |
| `training/core/src/cy_exec/training/executors/kernel_training.py` | Adapter to the pinned Platform Kernel contract. / 固定 Platform Kernel 契约的适配器。 |
| `training/core/src/cy_exec/training/executors/kernel_rpc.py` | Dynamic client projection of the pinned Platform descriptor. / 固定 Platform 描述符的动态客户端投影。 |
| `training/core/src/cy_exec/training/executors/training_worker.py` | Signed worker payload entered only by Platform supervision. / 仅由 Platform 监管启动的签名 Worker 载荷。 |
| `training/core/src/cy_exec/training/executors/kernel.desc` | Generated Platform protocol descriptor. / 生成的 Platform 协议描述符。 |
| `training/core/src/cy_exec/training/executors/kernel-descriptor.json` | Descriptor provenance and digest. / 描述符来源与摘要。 |

## Suggested reading order / 推荐阅读顺序

Read `base.py`, then `kernel_training.py`, and finally the signed worker payload.
先阅读 `base.py`，再阅读 `kernel_training.py`，最后查看签名 Worker 载荷。
