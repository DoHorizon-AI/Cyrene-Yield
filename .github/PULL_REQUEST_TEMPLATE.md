## Description
<!-- Provide a brief, clear summary of what this change accomplishes. -->

## Verification
- [ ] Local quick verification passed (`python tooling/ci/verify.py`)
- [ ] Relevant unit and SDK tests passed
- [ ] Dependency lock changes are intentional (`uv.lock` / `Cargo.lock`)
- [ ] Documentation links and indexes validated (`tooling/docs/validate_docs.py`)

## Architecture Impact
Does this change modify or impact any of the following?

- [ ] Public contract or protobuf schema (`contracts/`)
- [ ] Kernel semantics or OS sandboxing (`kernel/`)
- [ ] Product ownership or desired/observed state machine
- [ ] Capability interface definition (`Capability`)
- [ ] Persistence schema or artifact immutability
- [ ] Wire protocol or inter-process communication
- [ ] Public/Private dependency boundary (must remain strictly `PRIVATE -> PUBLIC`)

*If you checked any of the above, link the relevant ADR or explain why no ADR is required:*

---

## Compatibility & Migration
- [ ] Backward-compatible change
- [ ] Documentation updated (`docs/`)
---

<!-- Chinese Translation / 中文翻译 -->

## 变更说明
<!-- 请简要、清晰地概述此变更完成了什么。 -->

## 验证
- [ ] 本地快速验证通过（python tooling/ci/verify.py）
- [ ] 相关单元测试与 SDK 测试通过
- [ ] 依赖锁文件变更符合预期（uv.lock / Cargo.lock）
- [ ] 文档链接与索引已验证（tooling/docs/validate_docs.py）

## 架构影响
此变更是否修改或影响以下任一内容？

- [ ] 公开契约或 protobuf schema（contracts/）
- [ ] Kernel 语义或 OS sandbox（kernel/）
- [ ] Product 所有权或期望/观测状态机
- [ ] Capability 接口定义（Capability）
- [ ] 持久化 schema 或制品不可变性
- [ ] Wire 协议或进程间通信
- [ ] 公开/私有依赖边界（必须始终严格保持 PRIVATE -> PUBLIC）

*如果勾选以上任何一项，请链接相关 ADR，或说明为何不需要 ADR：*

---

## 兼容性与迁移
- [ ] 向后兼容的变更
- [ ] 已更新文档（docs/）
