# Architecture documentation / 架构文档

This directory explains Yield's training lifecycle, execution seams, and protocol boundaries.

本目录说明 Yield 的训练生命周期、执行接缝与协议边界。

| File | Responsibility / 职责 |
|---|---|
| [`overview.md`](overview.md) | Training state flow and authority boundaries / 训练状态流与权威边界 |
| [`tool-system.md`](tool-system.md) | Engine, executor, preflight, and checkpoint responsibilities / 引擎、执行器、前置校验与检查点职责 |
| [`mcp-integration.md`](mcp-integration.md) | Thin protocol adapter boundary / 薄协议适配边界 |

## Suggested reading order / 推荐阅读顺序

Read `overview.md`, then `tool-system.md`; consult `mcp-integration.md` for protocol work.

先阅读 `overview.md`，再阅读 `tool-system.md`；涉及协议时查阅 `mcp-integration.md`。
