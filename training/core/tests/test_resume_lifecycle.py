"""Focused ProductRun resume invariants for checkpoint-backed retry actions."""

from __future__ import annotations

import pytest

from cy_exec.training.lifecycle import (
    AttemptStatus,
    ExecutionPlan,
    IdempotencyKey,
    JsonFileControlPlaneStore,
    PlanStatus,
    PlanStep,
    ProductControlPlane,
    RetryPolicy,
)


def test_resume_adds_an_attempt_to_a_failed_run_without_mutating_history(tmp_path):
    store = JsonFileControlPlaneStore(tmp_path / "control-plane.json")
    control = ProductControlPlane(store)
    plan = ExecutionPlan.create(
        [PlanStep(step_id="train", capability="capability.train", retry_policy=RetryPolicy(max_attempts=1))]
    )
    run = control.submit(
        plan,
        product_kind="yield.training",
        idempotency_key=IdempotencyKey("resume-test"),
    )
    first = control.start_next_attempt(run.run_id)
    failed = control.observe_attempt(run.run_id, first.attempt_id, AttemptStatus.FAILED, error="worker lost")
    terminal = control.apply_terminal_action(failed.run_id)
    assert terminal.observed_status is PlanStatus.FAILED

    resumed = control.resume_attempt(run.run_id, "train")
    current = control.load(run.run_id)
    assert resumed.number == 2
    assert current.observed_status is PlanStatus.RUNNING
    assert current.attempts[0].status is AttemptStatus.FAILED
    assert current.attempts[-1].status is AttemptStatus.PENDING

    with pytest.raises(ValueError, match="not resumable"):
        control.resume_attempt(run.run_id, "train")
