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
