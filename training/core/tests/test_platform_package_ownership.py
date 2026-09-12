# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_platform_package_ownership.py
# │ Module: training/core/tests/test_platform_package_ownership
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘

from __future__ import annotations

import ast
from pathlib import Path

import cy_artifacts
import cyrene_preflight
from cy_exec.training import environment
from cyrene_yield_contracts import ModelVersion
from cy_exec.training.preflight_contracts import ModelAnalyzer, VramEstimate
from cy_exec.training.plugin_preflight import DirectPluginCompatibilityEvaluator, DirectPluginModelAnalyzer


def test_yield_owns_model_and_environment_policy_over_platform_primitives():
    assert hasattr(cy_artifacts, "LocalArtifactProvider")
    assert hasattr(environment, "EnvironmentResolver")
    assert hasattr(cyrene_preflight, "HardwareFacts")
    assert ModelVersion.__module__ == "cyrene_yield_contracts.model_version"
    assert ModelAnalyzer.__module__ == "cy_exec.training.preflight_contracts"
    assert VramEstimate.__module__ == "cy_exec.training.preflight_contracts"
    assert VramEstimate(lower_bytes=1, upper_bytes=2)
    assert DirectPluginModelAnalyzer.__module__ == "cy_exec.training.plugin_preflight"
    assert DirectPluginCompatibilityEvaluator.__module__ == "cy_exec.training.plugin_preflight"


def test_yield_has_no_production_preflight_capability_implementation():
    production = Path(__file__).resolve().parents[1] / "src" / "cy_exec" / "training"

    assert not (production / "reference_preflight.py").exists()
    adapter = (production / "plugin_preflight.py").read_text(encoding="utf-8")
    assert "DirectPluginClient" in adapter
    assert "model.analyzer.v1" in adapter
    assert "compatibility.evaluator.v1" in adapter


def test_platform_primitive_packages_do_not_import_yield():
    forbidden = {"cy_exec", "cyrene_yield", "training"}
    for module in (cy_artifacts, cyrene_preflight):
        source_root = Path(module.__file__).resolve().parent
        for source in source_root.glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            assert not any(item.split(".", 1)[0] in forbidden for item in imports)


def test_yield_no_longer_depends_on_platform_environment_or_model_contracts():
    repository_root = Path(__file__).resolve().parents[3]
    project = (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    service = (repository_root / "service.json").read_text(encoding="utf-8")
    production = (repository_root / "training" / "core" / "src").rglob("*.py")

    assert "cyrene-environment" not in project
    assert '"training.engine.v1"' not in service
    for source in production:
        text = source.read_text(encoding="utf-8")
        assert "from cy_environment" not in text
        assert "import cy_environment" not in text
        assert "from cy_artifacts.contracts import ModelVersion" not in text
