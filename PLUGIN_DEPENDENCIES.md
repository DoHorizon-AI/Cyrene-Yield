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
