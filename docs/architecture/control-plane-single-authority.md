# Product Control-Plane Single Authority (YLD-002)

## 1. Context and Audit Findings

In accordance with the **Services Standardization and Decoupling Plan (`YLD-002`)**:
- A dual control plane existed in `Cyrene-Yield`:
  1. The canonical Python V1 Product runtime in `training/core`.
  2. A legacy JVM migration snapshot in `migration/jvm-product-control-plane` (originally moved out of `Cyrene-Platform`).
- **Reachability & Consumer Audit**:
  - Comprehensive inspection of all Cyrene repositories (`Cyrene-Platform`, `Cyrene-Exchange`, `Cyrene-Reactor`, `Cyrene-Catalyst`, `Cyrene-Echo`, `Cyrene-Navigator`, `Cyrene-Plugins-Official`) revealed **zero external consumers** or references to `migration/jvm-product-control-plane`.
  - The Python runtime in `training/core` already provides complete, tested, and actively maintained authorities for `TrainingSession`, attempts, executors, lifecycle events, and REST/gRPC interfaces.

---

## 2. Decommissioning and Closure

1. **Retirement of Dual Control Plane**:
   - The unconsumed `migration/jvm-product-control-plane` snapshot has been permanently decommissioned and removed from `Cyrene-Yield`.
2. **Single Product Authority**:
   - Python `training/core` is the sole canonical Product runtime authority for Cyrene-Yield.
3. **CI Pipeline Streamlining**:
   - Removed the 20-minute `yield_jvm_migration` job and associated Java 25 / Gradle 9.5 download steps from `azure-pipelines.yml`.
   - CI runs cleanly on the canonical Python test suite.
---

<!-- Chinese Translation / 中文翻译 -->

# Product Control-Plane 单一权威（YLD-002）

## 1. 背景与审计发现

根据 **Services 标准化与解耦计划（YLD-002）**：

- Cyrene-Yield 曾存在双控制平面：
  1. training/core 中规范的 Python V1 Product runtime。
  2. migration/jvm-product-control-plane 中的旧 JVM 迁移快照（最初从 Cyrene-Platform 移出）。
- **可达性与消费者审计**：
  - 对所有 Cyrene 仓库（Cyrene-Platform、Cyrene-Exchange、Cyrene-Reactor、Cyrene-Catalyst、Cyrene-Echo、Cyrene-Navigator、Cyrene-Plugins-Official）进行全面检查后，发现没有外部消费者或对 migration/jvm-product-control-plane 的引用。
  - training/core 中的 Python runtime 已提供完整、经过测试且持续维护的 TrainingSession、attempt、executor、生命周期事件以及 REST/gRPC 接口权威实现。

---

## 2. 退役与收尾

1. **退役双控制平面**：
   - 未被消费的 migration/jvm-product-control-plane 快照已永久退役，并从 Cyrene-Yield 移除。
2. **唯一 Product 权威**：
   - Python training/core 是 Cyrene-Yield 唯一规范的 Product runtime 权威。
3. **精简 CI pipeline**：
   - 从 azure-pipelines.yml 中移除了耗时 20 分钟的 yield_jvm_migration job，以及相关 Java 25 / Gradle 9.5 下载步骤。
   - CI 可在规范 Python 测试套件上正常运行。
