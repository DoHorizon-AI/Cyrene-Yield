"""
Unit tests for Cyrene Yield correlation propagation, error mapping, and logging.

Cyrene Yield 关联信息传播、错误映射与日志的单元测试。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from cy_exec.training.errors import map_yield_error
from cy_exec.training.logging import (
    format_cyrene_log,
    is_sensitive_key,
    parse_w3c_traceparent,
    redact_attributes,
    sanitize_correlation_id,
    sanitize_request_id,
)
from cy_exec.training.product_api import create_app
from cy_exec.training.product_store import ProductStore


def test_w3c_traceparent_parsing():
    valid = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    parsed = parse_w3c_traceparent(valid)
    assert parsed is not None
    trace_id, span_id = parsed
    assert trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert span_id == "00f067aa0ba902b7"

    # All zeros rejection
    # 拒绝全零值。
    assert parse_w3c_traceparent("00-00000000000000000000000000000000-00f067aa0ba902b7-01") is None
    assert parse_w3c_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01") is None
    assert parse_w3c_traceparent("invalid-traceparent") is None


def test_correlation_sanitization():
    dirty = "req-123\r\ninjection: attempt\x00"
    sanitized = sanitize_request_id(dirty)
    assert sanitized == "req-123injection:attempt"
    assert "\r" not in sanitized
    assert "\n" not in sanitized

    long_id = "X" * 300
    assert len(sanitize_request_id(long_id)) == 128


def test_redaction_preserves_token_usage_counters():
    attrs = {
        "api_key": "secret-api-key-12345",
        "token": "sensitive-token-abc",
        "password": "my-password",
        "tokens": 2048,
        "prompt_tokens": 1024,
        "completion_tokens": 1024,
        "token_count": 2048,
        "safe_attr": "training-cluster-1",
    }
    redacted = redact_attributes(attrs)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["token"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["tokens"] == 2048
    assert redacted["prompt_tokens"] == 1024
    assert redacted["completion_tokens"] == 1024
    assert redacted["token_count"] == 2048
    assert redacted["safe_attr"] == "training-cluster-1"


def test_yield_error_mapping():
    mapped = map_yield_error("YIELD_RESOURCE_NOT_FOUND")
    assert mapped["code"] == "PRODUCT.YIELD.RESOURCE_NOT_FOUND"
    assert mapped["recovery_action"] == "user_action_required"

    mapped_dep = map_yield_error("YIELD_DEPENDENCY_UNAVAILABLE")
    assert mapped_dep["code"] == "PRODUCT.YIELD.DEPENDENCY_UNAVAILABLE"
    assert mapped_dep["recovery_action"] == "query_state_first"

    mapped_unknown = map_yield_error("CUSTOM_FOO_BAR")
    assert mapped_unknown["code"] == "PRODUCT.YIELD.CUSTOM_FOO_BAR"
    assert mapped_unknown["recovery_action"] == "query_state_first"


def test_structured_log_formatting():
    log_line = format_cyrene_log(
        "INFO",
        "product.yield.test_event",
        "Test yield message",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        span_id="00f067aa0ba902b7",
        attributes={"run_id": "run-456", "token": "sensitive"},
    )
    record = json.loads(log_line)
    assert record["schema_version"] == 1
    assert record["level"] == "INFO"
    assert record["service.name"] == "cyrene-yield"
    assert record["event.name"] == "product.yield.test_event"
    assert record["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert record["span_id"] == "00f067aa0ba902b7"
    assert record["attributes"]["run_id"] == "run-456"
    assert record["attributes"]["token"] == "[REDACTED]"


def test_api_traceparent_and_error_handling():
    with TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "state"
        artifact_dir = Path(tmp) / "artifacts"
        app = create_app(state_directory=state_dir, artifact_root=artifact_dir)
        with TestClient(app) as client:
            traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
            req_id = "req-yield-test-999"

            # Request non-existent draft to trigger 404 failure ProblemDetails
            # 请求不存在的 draft,以触发 404 失败 ProblemDetails。
            res = client.get(
                "/api/v1/training-drafts/00000000-0000-0000-0000-000000000001",
                headers={"traceparent": traceparent, "x-request-id": req_id},
            )

            assert res.status_code == 404
            assert "traceparent" in res.headers
            assert "4bf92f3577b34da6a3ce929d0e0e4736" in res.headers["traceparent"]
            assert res.headers["x-request-id"] == req_id

            problem = res.json()
            assert problem["code"] == "YIELD_RESOURCE_NOT_FOUND"
            assert problem.get("requestId") == req_id or problem.get("request_id") == req_id
            assert problem.get("traceId") == "4bf92f3577b34da6a3ce929d0e0e4736"
            assert problem.get("recoveryAction") == "user_action_required"


def test_startup_purge_failure_emits_structured_diagnostic(monkeypatch, capsys, tmp_path: Path) -> None:
    """A failed background retention cleanup has its own traceable boundary log."""

    def fail_purge(_store: ProductStore) -> int:
        raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr(ProductStore, "purge_expired_diagnostics", fail_purge)
    app = create_app(state_directory=tmp_path / "state", artifact_root=tmp_path / "artifacts")
    with TestClient(app):
        pass

    records = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")]
    purge_errors = [
        record for record in records if record.get("event.name") == "product.yield.diagnostics_purge_failed"
    ]
    assert len(purge_errors) == 1
    error = purge_errors[0]
    assert error["attributes"]["error.code"] == "YIELD_DIAGNOSTICS_PURGE_FAILED"
    assert error["attributes"]["phase"] == "startup"
    assert error["attributes"]["cause_kind"] == "OperationalError"
    assert len(error["trace_id"]) == 32
    assert "private database path" not in error["message"]
