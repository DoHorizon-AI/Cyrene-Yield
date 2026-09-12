# Dependency and SBOM record / 依赖与 SBOM 记录

This page is the release entry point for Yield's dependency and license
inventory. It records the current manifests and lockfiles and is not a legal
opinion.

本页是 Yield 依赖与许可证清单的发布入口。它记录当前 manifest 与锁文件，不构成
法律意见。

## Authoritative inputs / 权威输入

- Product runtime declarations: [`pyproject.toml`](../pyproject.toml).
- Product resolved graph and hashes: [`uv.lock`](../uv.lock).
- Independent CUDA trainer environment: [`trainer-runtime/pyproject.toml`](../trainer-runtime/pyproject.toml) and [`trainer-runtime/uv.lock`](../trainer-runtime/uv.lock).
- Public contract package: [`sdk/python/cyrene_yield_contracts/pyproject.toml`](../sdk/python/cyrene_yield_contracts/pyproject.toml).
- Repository license grant: [`LICENSE`](../LICENSE).
- Direct dependency summary: [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

The lockfiles are the source of truth for exact resolved versions and hashes.
The Product lock points to Platform `c59be6f2bd82489fbe933dadff84fc589e00afd9`
and Plugins `c3f75689ebb10b2e07b3816310e768d74ae6cc10`; the Plugins repository
is currently private and several owner package manifests do not declare a
license. An anonymous clean-clone build is therefore not yet available.

锁文件是精确解析版本与摘要的事实来源。Product 锁文件指向 Platform
`c59be6f2bd82489fbe933dadff84fc589e00afd9` 和 Plugins
`c3f75689ebb10b2e07b3816310e768d74ae6cc10`；Plugins 当前仍为 private，且多个
owner 包 manifest 没有声明许可证，因此匿名 clean clone 尚不可用。

## Direct package inventory / 直接包清单

| Package family | Source and lock | License status |
|---|---|---|
| Yield Product (`cyrene-yield`) | root `pyproject.toml` + `uv.lock` | Apache-2.0 declared in package metadata and root `LICENSE` |
| Yield contracts (`cyrene-yield-contracts`) | `sdk/python/.../pyproject.toml` | Apache-2.0 declared in package metadata |
| Platform SDKs (`cyrene-artifacts`, `cyrene-preflight`) | Platform pinned Git SHA | Apache-2.0 declared by the owner package metadata |
| Consumed Plugins SDK/capabilities | Plugins pinned Git SHA | `UNKNOWN` for the locked runtime/analyzer/compatibility/validator packages; owner declarations and anonymous reachability are still required |
| CUDA trainer runtime | `trainer-runtime/uv.lock` / PyTorch CUDA index | Requires separate PyTorch, NVIDIA CUDA component, and model/upstream license review |

## SBOM procedure / SBOM 流程

At release time, export each locked graph without resolving new versions and feed
the outputs to the organization's approved SPDX or CycloneDX generator. Attach
the generated JSON to the release and record its digest next to the release tag.
The trainer-runtime graph must be represented separately because it uses the
CUDA-specific PyTorch index and is not part of the Product package dependency
closure.

发布时应在不重新解析版本的前提下分别导出每个锁定依赖图，并交给组织批准的
SPDX 或 CycloneDX 生成器。生成的 JSON 应作为 release 附件，并在 release tag 旁
记录摘要。trainer-runtime 使用 CUDA 专用 PyTorch index，不属于 Product 包依赖闭包，
必须单独纳入 SBOM。

```bash
uv export --project . --locked --format requirements-txt --no-dev > /tmp/cyrene-yield-runtime.txt
uv export --project . --locked --format requirements-txt > /tmp/cyrene-yield-all.txt
uv export --project trainer-runtime --locked --format requirements-txt > /tmp/cyrene-yield-trainer-runtime.txt
```

The generated SBOM must include package URLs, exact versions, source
URLs/revisions, hashes where available, and license expressions. The current
repository does not commit a generated SBOM because the approved generator and
release artifact store are external controls.

生成的 SBOM 必须包含 PURL、精确版本、源 URL/修订版、可用摘要以及许可证表达式。
本仓库不提交生成后的 SBOM，因为批准的生成器与 release 制品存储属于外部控制。

## Publication boundaries / 公开边界

Making the source repository public is separate from distributing the Product
package or the CUDA trainer runtime. Binary distribution requires a release
SBOM, resolved dependency licenses, upstream notices, and a decision for every
non-registry source. Hosted CI is an independent evidence gate for the exact
release commit; local CPU tests do not replace it.

公开源码仓库与分发 Product package 或 CUDA trainer runtime 是不同门禁。二进制分发
必须具备 release SBOM、完整的已解析依赖许可证、上游声明，并为每个非 registry 源
作出明确结论。Hosted CI 是针对精确 release 提交的独立证据门禁；本地 CPU 测试不能
替代 Hosted CI。

The historical LLaMA Factory demo datasets under
`plugins/llama-factory-training/data` are excluded from this clean-root source
payload. Their former history remains only in the private
`Cyrene-Yield-history-archive` and is not approved for public redistribution.

历史 LLaMA Factory demo 数据集（`plugins/llama-factory-training/data`）已排除在本
clean-root 源码内容之外。其旧历史仅保留在私有的
`Cyrene-Yield-history-archive` 中，也未获准公开再分发。

## Publication gates / 公开门禁

Before publication, maintainers must make the Plugins revision and every owner
package anonymously reachable, review the CUDA/NVIDIA and upstream-derived
licenses, refresh the lockfiles, and confirm that the generated SBOM matches
the release SHA. The unresolved records are listed in
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

公开前，维护者必须让 Plugins 修订版及每个 owner 包可匿名访问，审查 CUDA/NVIDIA
与上游衍生内容的许可证，刷新锁文件，并确认生成的 SBOM 与 release SHA 一致。
未解决记录列于 [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。
