# Plugin dependencies

The optional training-focused LLaMA Factory backend is resolved from the Plugins
repository at:

- `Cyrene-Plugins-Official/plugins/training/llama-factory/`

It is derived from an upstream snapshot whose provenance and license must be
reviewed in the Plugin repository. This is a partial capability extraction, not
a claim that the full upstream tree has been migrated or relicensed. Yield
connects through the standard
`training.llama-factory.v1` DirectPluginRuntime capability; it does not vendor
the backend or own its dependencies.

The former LLaMA Factory demo datasets under
`plugins/llama-factory-training/data` are deliberately absent from this
clean-root repository. They remain only in the private history archive and are
not approved for public redistribution.

Yield consumes the DirectPluginRuntime client SDK and its test-only preflight
owner packages directly from the immutable Plugins revision
`3afbac4d386eb7a27f6778149187884820c0b7f6`. No Plugin SDK or capability
implementation is vendored in this repository. Production receives opaque
`connection_ref` values and never imports the implementation packages.

The extraction scope and follow-up work are documented in the Plugin's
`CYRENE_IMPROVEMENTS.md` and `README.md`. Because the pinned owner repository is
currently private and the referenced package manifests do not declare a
license, this dependency is a public-clone/release blocker until the owner
publishes a reviewed immutable distribution.

提取范围和后续工作记录在 Plugin 的 `CYRENE_IMPROVEMENTS.md` 与 `README.md` 中。
由于锁定的 owner 仓库当前为 private，且相关包 manifest 没有声明许可证，该依赖
在 owner 发布经过审查的不可变发行包前属于公开 clone/release 阻塞项。

clean-root 仓库有意不包含原 LLaMA Factory demo 数据集；这些数据仅保留在私有历史
归档中，未获准公开再分发。
---

<!-- Chinese Translation / 中文翻译 -->

# Plugin 依赖

可选的、面向训练的 LLaMA Factory 后端从 Plugins 仓库的以下路径解析：

- Cyrene-Plugins-Official/plugins/training/llama-factory/

该后端源自一个上游快照，其来源信息和许可证必须在 Plugin 仓库中审查。这是部分能力提取，不代表已迁移或重新许可整个上游代码树。Yield 通过标准 training.llama-factory.v1 DirectPluginRuntime 能力连接；它不 vendoring 后端，也不拥有其依赖。

原 LLaMA Factory 演示数据集位于 plugins/llama-factory-training/data，现有意从此 clean-root 仓库中移除。它们仅保留在私有历史归档中，未获准公开再分发。

Yield 直接使用不可变 Plugins 修订版 3afbac4d386eb7a27f6778149187884820c0b7f6 中的 DirectPluginRuntime 客户端 SDK 及仅供测试使用的 preflight owner packages。本仓库未 vendoring 任何 Plugin SDK 或能力实现。生产环境接收不透明的 connection_ref 值，且绝不导入实现 package。

提取范围和后续工作记录在 Plugin 的 CYRENE_IMPROVEMENTS.md 与 README.md 中。由于锁定的 owner 仓库当前为 private，相关 package manifest 也未声明许可证，在 owner 发布经过审查的不可变分发版本前，此依赖会阻塞公开 clone/release。

clean-root 仓库有意不包含原 LLaMA Factory 演示数据集；这些数据仅留在私有历史归档中，未获准公开再分发。
