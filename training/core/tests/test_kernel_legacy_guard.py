"""Guardrail: production mapping must not revive origin/main AgentService."""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_kernel_legacy_guard.py
# │ Module: training/core/tests/test_kernel_legacy_guard
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

import re
from pathlib import Path

USAGE = re.compile(
    r"(?:from\s+\S*cy\.llm\S*\s+import|import\s+\S*cy\.llm"
    r"|ExecuteCommandStream\s*\(|class\s+.*AgentService)",
    re.MULTILINE,
)

PRODUCTION_GLOBS = (
    "src/cy_exec/training/executors/*.py",
    "src/cy_exec/training/runtime.py",
    "src/cy_exec/training/contracts/*.py",
)


def test_production_training_code_does_not_reference_legacy_agent_service():
    root = Path(__file__).resolve().parents[1]
    hits = []
    for pattern in PRODUCTION_GLOBS:
        for path in root.glob(pattern):
            text = path.read_text(encoding="utf-8")
            if USAGE.search(text):
                hits.append(str(path.relative_to(root)))
    assert hits == [], f"legacy Kernel contract leaked into production mapping: {hits}"


def test_node_agent_shim_was_removed():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "cy_exec"
        / "training"
        / "executors"
        / "node_agent.py"
    )
    assert not path.exists()
