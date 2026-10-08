# training/core/tests / training/core/tests

Training-core regression tests.

训练核心回归测试。

## Files / 文件

| Entry | Responsibility / 职责 |
|---|---|
| `training/core/tests/conftest.py` | Python implementation or test module: conftest.py. / Python 实现或测试模块：conftest.py。 |
| `training/core/tests/test_artifact_plane.py` | Python implementation or test module: test_artifact_plane.py. / Python 实现或测试模块：test_artifact_plane.py。 |
| `training/core/tests/test_checkpoint_manager_pbt.py` | Python implementation or test module: test_checkpoint_manager_pbt.py. / Python 实现或测试模块：test_checkpoint_manager_pbt.py。 |
| `training/core/tests/test_control_plane_conformance.py` | Python implementation or test module: test_control_plane_conformance.py. / Python 实现或测试模块：test_control_plane_conformance.py。 |
| `training/core/tests/test_environment_integration.py` | Python implementation or test module: test_environment_integration.py. / Python 实现或测试模块：test_environment_integration.py。 |
| `training/core/tests/test_kernel_legacy_guard.py` | Python implementation or test module: test_kernel_legacy_guard.py. / Python 实现或测试模块：test_kernel_legacy_guard.py。 |
| `training/core/tests/test_kernel_training.py` | Platform Kernel adapter, signed installation, and cleanup evidence. / Platform Kernel 适配器、签名安装与回收证据。 |
| `training/core/tests/test_platform_package_ownership.py` | Python implementation or test module: test_platform_package_ownership.py. / Python 实现或测试模块：test_platform_package_ownership.py。 |
| `training/core/tests/test_training_contract.py` | Python implementation or test module: test_training_contract.py. / Python 实现或测试模块：test_training_contract.py。 |
| `training/core/tests/test_training_control_plane.py` | Python implementation or test module: test_training_control_plane.py. / Python 实现或测试模块：test_training_control_plane.py。 |
| `training/core/tests/test_training_preflight_and_tiny_dry_run.py` | Python implementation or test module: test_training_preflight_and_tiny_dry_run.py. / Python 实现或测试模块：test_training_preflight_and_tiny_dry_run.py。 |
| `training/core/tests/test_training_tck.py` | Python implementation or test module: test_training_tck.py. / Python 实现或测试模块：test_training_tck.py。 |
| `training/core/tests/training_tck_helpers.py` | Python implementation or test module: training_tck_helpers.py. / Python 实现或测试模块：training_tck_helpers.py。 |

## Suggested reading order / 推荐阅读顺序

Start with `training/core/tests/conftest.py` and then follow the package entry point or imports.
Read sibling modules in runtime order; use the parent README for ownership boundaries.
从 `training/core/tests/conftest.py` 开始，再按包入口或导入关系继续阅读。
按运行时顺序阅读同级模块；职责边界请查阅父目录 README。
---

<!-- Chinese Translation / 中文翻译 -->

# training/core/tests

训练核心回归测试。

## 文件

| 条目 | 职责 |
|---|---|
| training/core/tests/conftest.py | Python 实现或测试模块：conftest.py。 |
| training/core/tests/test_artifact_plane.py | Python 实现或测试模块：test_artifact_plane.py。 |
| training/core/tests/test_checkpoint_manager_pbt.py | Python 实现或测试模块：test_checkpoint_manager_pbt.py。 |
| training/core/tests/test_control_plane_conformance.py | Python 实现或测试模块：test_control_plane_conformance.py。 |
| training/core/tests/test_environment_integration.py | Python 实现或测试模块：test_environment_integration.py。 |
| training/core/tests/test_kernel_legacy_guard.py | Python 实现或测试模块：test_kernel_legacy_guard.py。 |
| training/core/tests/test_kernel_training.py | Platform Kernel 适配器、签名安装与清理证据。 |
| training/core/tests/test_platform_package_ownership.py | Python 实现或测试模块：test_platform_package_ownership.py。 |
| training/core/tests/test_training_contract.py | Python 实现或测试模块：test_training_contract.py。 |
| training/core/tests/test_training_control_plane.py | Python 实现或测试模块：test_training_control_plane.py。 |
| training/core/tests/test_training_preflight_and_tiny_dry_run.py | Python 实现或测试模块：test_training_preflight_and_tiny_dry_run.py。 |
| training/core/tests/test_training_tck.py | Python 实现或测试模块：test_training_tck.py。 |
| training/core/tests/training_tck_helpers.py | Python 实现或测试模块：training_tck_helpers.py。 |

## 推荐阅读顺序

先从 training/core/tests/conftest.py 开始，再沿包入口或导入关系继续阅读。
按 runtime 顺序阅读同级模块；职责边界请参见父目录 README。
