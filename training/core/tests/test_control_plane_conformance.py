# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/tests/test_control_plane_conformance.py
# │ 中文:文件:training/core/tests/test_control_plane_conformance.py
# │ Module: training/core/tests/test_control_plane_conformance
# │ 模块:training/core/tests/test_control_plane_conformance
# │ Role: Yield core test module — verifies the unified training runtime and its contracts.
# │ 职责:Yield 核心测试模块,验证统一训练 runtime 与契约。
# │
# │ 模块职责：Yield 核心测试模块——验证统一训练运行时及其契约。
# └─────────────────────────────────────────────────────────────────────┘

import json
from pathlib import Path

from cy_exec.training.lifecycle import Attempt, ExecutionPlan, Generation, IdempotencyKey, PlanStep

FIXTURE = (
    Path(__file__).resolve().parents[3] / "contracts" / "product" / "v1" / "training-control-plane-conformance.json"
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def test_yield_control_plane_fixture_matches_python_canonical_serialization():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    step = PlanStep.from_dict(fixture["plan"]["steps"][0])
    plan = ExecutionPlan.create(
        [step],
        contract_version=fixture["contract_version"],
        metadata=fixture["plan"]["metadata"],
        provenance=fixture["plan"]["provenance"],
    )
    assert _canonical(plan.identity_dict()) == fixture["expected"]["plan_identity_canonical"]

    attempt = Attempt.from_dict(fixture["attempt"])
    assert _canonical(attempt.to_dict()) == fixture["expected"]["attempt_canonical"]


def test_yield_control_plane_fixture_preserves_identity_generation_and_idempotency():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert str(Attempt.from_dict(fixture["attempt"]).attempt_id) == "run-conformance:1"
    assert Generation(fixture["run_identity"]["generation"]) == Generation(7)
    assert IdempotencyKey(fixture["run_identity"]["idempotency_key"]) == IdempotencyKey("conformance:fixed")
