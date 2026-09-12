"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.product_api                                │
│  Role: Documented HTTP entry points for explicit training handoffs.│
│  模块职责：训练草稿、显式启动、结果导出与 Send to Reactor 接口。          │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import fcntl
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import grpc
import httpx
from cy_artifacts import ArtifactError, LocalArtifactProvider
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .control_plane import TrainingControlPlane
from .executors.kernel_training import KernelTrainingConfiguration, KernelTrainingExecutor
from .product_models import (
    CreateTrainingDraft,
    HandoffReceipt,
    PrepareTrainingDraft,
    TrainingAttemptResource,
    TrainingDraft,
    TrainingResultResource,
    TrainingRunResource,
)
from .product_service import YieldService
from .product_store import ProductStore
from .runtime import TrainingRuntime


def create_app(
    *,
    state_directory: Path,
    artifact_root: Path,
    binding_id: str = "llamafactory-sft-lora-v1",
    kernel: KernelTrainingConfiguration | None = None,
    reactor_url: str | None = None,
    reactor_bearer_token: str | None = None,
    control: TrainingControlPlane | None = None,
    http_client: httpx.Client | None = None,
) -> FastAPI:
    """Build the Product independently; live training requires an explicit Kernel binding."""
    state_directory.mkdir(parents=True, exist_ok=True)
    owner = (state_directory / "product.lock").open("a")
    if kernel is not None:
        # Acquire ownership before constructing the lease renewal adapter.
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
    artifacts = LocalArtifactProvider(artifact_root)
    executor = KernelTrainingExecutor(kernel) if kernel is not None else None
    runtime = TrainingRuntime(executor=executor, artifact_provider=artifacts)
    if executor is not None:
        for launch, handle in executor.recover():
            runtime.restore_session(launch, handle)
    execution_available = control is not None or executor is not None
    controller = control or TrainingControlPlane(runtime, state_directory / "runs.json", durable_tiny_attempt=True)
    service = YieldService(
        store=ProductStore(state_directory / "product.sqlite3"),
        control=controller,
        artifacts=artifacts,
        state_directory=state_directory,
        binding_id=binding_id,
        reactor_url=reactor_url,
        reactor_bearer_token=reactor_bearer_token,
        http_client=http_client,
    )
    stopped = threading.Event()
    background_errors: list[str] = []

    def reconcile() -> None:
        while not stopped.wait(0.2):
            try:
                if executor is not None and runtime.hardware_facts is None:
                    runtime.update_hardware_facts(executor.hardware_facts())
                service.advance()
                background_errors.clear()
            except (OSError, ValueError, RuntimeError, grpc.RpcError) as exc:
                background_errors[:] = [type(exc).__name__]

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        worker = threading.Thread(target=reconcile, daemon=True)
        worker.start()
        try:
            yield
        finally:
            stopped.set()
            # Finish the current bounded RPC or Artifact publication before
            # closing its store and allowing another Product writer.
            worker.join()
            if executor is not None:
                executor.close()
            service.store.close()
            owner.close()

    app = FastAPI(title="Cyrene Yield Product API", version="1.0.0", lifespan=lifespan)
    app.state.yield_service = service

    async def failure(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, KeyError):
            status, code = 404, "YIELD_RESOURCE_NOT_FOUND"
        elif isinstance(exc, httpx.HTTPStatusError):
            status, code = 502, "YIELD_HANDOFF_REJECTED"
        elif isinstance(exc, (httpx.HTTPError, grpc.RpcError)):
            status, code = 503, "YIELD_DEPENDENCY_UNAVAILABLE"
        elif isinstance(exc, ArtifactError):
            status, code = 422, "YIELD_ARTIFACT_UNAVAILABLE"
        else:
            code = str(exc).split(":", 1)[0]
            if not code.startswith("YIELD_") or not code.replace("_", "").isalnum():
                code = "YIELD_REQUEST_INVALID"
            status = 409 if any(item in code for item in ("CONFLICT", "STARTED", "PREPARED")) else 422
        return JSONResponse(
            status_code=status,
            media_type="application/problem+json",
            content={
                "type": "https://errors.cyrene.dev/yield/" + code.lower().replace("_", "-"),
                "title": code,
                "status": status,
                "code": code,
                "detail": (
                    "The requested Product action did not complete. "
                    "Check the selected resource or configured dependency."
                ),
                "instance": request.url.path,
                "retryable": status >= 500,
                "traceId": uuid4().hex,
            },
        )

    for kind in (KeyError, ValueError, ArtifactError, httpx.HTTPError, grpc.RpcError, RequestValidationError):
        app.add_exception_handler(kind, failure)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "DEGRADED" if background_errors else "READY",
            "trainingConfigured": execution_available,
            "reconcileErrors": list(background_errors),
        }

    @app.post(
        "/api/v1/training-drafts", response_model=TrainingDraft, status_code=201, response_model_exclude_none=True
    )
    def import_dataset(
        command: CreateTrainingDraft, idempotency_key: str | None = Header(default=None, max_length=200)
    ) -> TrainingDraft:
        return service.create_draft(command, idempotency_key)

    @app.get("/api/v1/training-drafts", response_model=list[TrainingDraft], response_model_exclude_none=True)
    def list_drafts() -> list[TrainingDraft]:
        return service.list_drafts()

    @app.get("/api/v1/training-drafts/{draft_id}", response_model=TrainingDraft, response_model_exclude_none=True)
    def get_draft(draft_id: UUID) -> TrainingDraft:
        return service.get_draft(draft_id)

    @app.patch("/api/v1/training-drafts/{draft_id}", response_model=TrainingDraft, response_model_exclude_none=True)
    def prepare_draft(draft_id: UUID, command: PrepareTrainingDraft) -> TrainingDraft:
        return service.prepare(draft_id, command)

    @app.post(
        "/api/v1/training-drafts/{draft_id}/actions/start",
        response_model=TrainingRunResource,
        status_code=202,
        response_model_exclude_none=True,
    )
    def start_run(draft_id: UUID) -> TrainingRunResource:
        if not execution_available:
            return _unavailable()
        if executor is not None:
            runtime.update_hardware_facts(executor.hardware_facts())
        return service.start(draft_id)

    @app.get("/api/v1/training-runs/{run_id}", response_model=TrainingRunResource, response_model_exclude_none=True)
    def get_run(run_id: UUID) -> TrainingRunResource:
        return service.get_run(run_id)

    @app.get(
        "/api/v1/training-runs/{run_id}/attempts",
        response_model=list[TrainingAttemptResource],
        response_model_exclude_none=True,
    )
    def get_attempts(run_id: UUID) -> list[TrainingAttemptResource]:
        return service.list_attempts(run_id)

    @app.post(
        "/api/v1/training-runs/{run_id}/actions/cancel",
        response_model=TrainingRunResource,
        status_code=202,
        response_model_exclude_none=True,
    )
    def cancel_run(run_id: UUID) -> TrainingRunResource:
        return service.cancel(run_id)

    @app.get(
        "/api/v1/training-results/{result_id}", response_model=TrainingResultResource, response_model_exclude_none=True
    )
    def get_result(result_id: UUID) -> TrainingResultResource:
        return service.get_result(result_id)

    @app.post(
        "/api/v1/training-results/{result_id}/actions/send-to-reactor",
        response_model=HandoffReceipt,
        response_model_exclude_none=True,
    )
    def send_to_reactor(result_id: UUID) -> HandoffReceipt:
        return service.send_to_reactor(result_id)

    return app


def _unavailable() -> Any:
    raise ValueError("YIELD_EXECUTION_NOT_CONFIGURED: connect a Kernel training host before starting")
