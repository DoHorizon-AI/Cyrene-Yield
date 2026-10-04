"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.product_api                                │
│  Role: Documented HTTP entry points for explicit training handoffs.│
│  模块职责：训练草稿、显式启动、结果导出与 Send to Reactor 接口。          │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import fcntl
import asyncio
import json
import sqlite3
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import grpc
import httpx
from cy_artifacts import ArtifactError, LocalArtifactProvider
from fastapi import Body, Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .control_plane import TrainingControlPlane
from .executors.kernel_training import KernelTrainingConfiguration, KernelTrainingExecutor
from .product_models import (
    CreateTrainingDraft,
    DiagnosticsPage,
    GatewayRouteDraftReceipt,
    HandoffReceipt,
    ImportLlamaFactoryYaml,
    PrepareTrainingDraft,
    PreflightReport,
    ResumeTrainingRun,
    SendTrainingResultToExchange,
    TrainingAttemptResource,
    TrainingDraft,
    TrainingEventsPage,
    TrainingResultResource,
    TrainingRunPage,
    TrainingRunResource,
    WorkspaceTrainingEventsQuery,
)
from .errors import map_yield_error
from .llama_factory_yaml import LlamaFactoryYamlError
from .logging import (
    emit_diagnostic_error,
    parse_w3c_traceparent,
    sanitize_request_id,
)
from .model_registry import (
    DirectPluginModelRegistry,
    ModelRegistryPort,
    ModelRegistryUnavailable,
)
from .product_service import YieldService
from .product_store import ProductStore
from .runtime import TrainingRuntime
from .workspace_auth import WorkspaceScope, WorkspaceServiceAuthenticator
from .workspace_projection import (
    WorkspaceTrainingDraftProjection,
    WorkspaceScopedTrainingRunProjection,
    WorkspaceTrainingAttemptsProjection,
    WorkspaceTrainingEventsPageProjection,
    WorkspaceTrainingRunProjection,
    project_workspace_training_draft,
    project_workspace_run_attempts,
    project_workspace_run_events,
    project_workspace_scoped_training_run,
    project_workspace_training_run,
)


def create_app(
    *,
    state_directory: Path,
    artifact_root: Path,
    binding_id: str = "llamafactory-sft-lora-v1",
    kernel: KernelTrainingConfiguration | None = None,
    workspace_credential_map_json: str | None = None,
    reactor_url: str | None = None,
    reactor_bearer_token: str | None = None,
    exchange_url: str | None = None,
    exchange_bearer_token: str | None = None,
    exchange_endpoint_id: str | None = None,
    exchange_target_binding_id: str | None = None,
    model_registry_connection_ref: str | None = None,
    model_registry: ModelRegistryPort | None = None,
    control: TrainingControlPlane | None = None,
    http_client: httpx.Client | None = None,
) -> FastAPI:
    """Build the Product independently; live training requires an explicit Kernel binding.

    独立构建 Product;实时训练需要显式配置 Kernel 绑定。
    """
    workspace_auth = WorkspaceServiceAuthenticator(workspace_credential_map_json)
    state_directory.mkdir(parents=True, exist_ok=True)
    owner = (state_directory / "product.lock").open("a")
    if kernel is not None:
        # Acquire ownership before constructing the lease renewal adapter.
        # 在构建租约续期适配器前先取得所有权。
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
    artifacts = LocalArtifactProvider(artifact_root)
    executor = KernelTrainingExecutor(kernel) if kernel is not None else None
    runtime = TrainingRuntime(executor=executor, artifact_provider=artifacts)
    if executor is not None:
        for launch, handle in executor.recover():
            runtime.restore_session(launch, handle)
    execution_available = control is not None or executor is not None
    controller = control or TrainingControlPlane(runtime, state_directory / "runs.json", durable_tiny_attempt=True)
    if model_registry is not None and model_registry_connection_ref is not None:
        raise ValueError("YIELD_MODEL_REGISTRY_CONFLICT: configure one registry adapter")
    registry = model_registry
    if registry is None and model_registry_connection_ref is not None:
        registry = DirectPluginModelRegistry.from_connection_ref(model_registry_connection_ref)
    service = YieldService(
        store=ProductStore(state_directory / "product.sqlite3"),
        control=controller,
        artifacts=artifacts,
        state_directory=state_directory,
        binding_id=binding_id,
        reactor_url=reactor_url,
        reactor_bearer_token=reactor_bearer_token,
        exchange_url=exchange_url,
        exchange_bearer_token=exchange_bearer_token,
        exchange_endpoint_id=exchange_endpoint_id,
        exchange_target_binding_id=exchange_target_binding_id,
        model_registry=registry,
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
        try:
            service.store.purge_expired_diagnostics()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            emit_diagnostic_error(
                "product.yield.diagnostics_purge_failed",
                "YIELD_DIAGNOSTICS_PURGE_FAILED",
                "Failed to purge expired diagnostics during startup",
                trace_id=uuid4().hex,
                attributes={"cause_kind": type(exc).__name__, "phase": "startup"},
            )

        async def _periodic_purge() -> None:
            while True:
                try:
                    await asyncio.sleep(24 * 3600)
                    service.store.purge_expired_diagnostics()
                except asyncio.CancelledError:
                    break
                except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
                    emit_diagnostic_error(
                        "product.yield.diagnostics_purge_failed",
                        "YIELD_DIAGNOSTICS_PURGE_FAILED",
                        "Failed to purge expired diagnostics in background maintenance",
                        trace_id=uuid4().hex,
                        attributes={"cause_kind": type(exc).__name__, "phase": "periodic"},
                    )

        purge_task = asyncio.create_task(_periodic_purge())
        worker = threading.Thread(target=reconcile, daemon=True)
        worker.start()
        try:
            yield
        finally:
            purge_task.cancel()
            stopped.set()
            # Finish the current bounded RPC or Artifact publication before
            # 在关闭其 store 并允许另一个 Product writer 进入前,
            # closing its store and allowing another Product writer.
            # 先完成当前有界 RPC 或 Artifact 发布。
            worker.join()
            if executor is not None:
                executor.close()
            service.store.close()
            owner.close()

    app = FastAPI(title="Cyrene Yield Product API", version="1.0.0", lifespan=lifespan)
    app.state.yield_service = service

    @app.middleware("http")
    async def propagate_trace(request: Request, call_next: Any) -> Response:
        parsed_trace = parse_w3c_traceparent(request.headers.get("traceparent"))
        trace_id = parsed_trace[0] if parsed_trace else uuid4().hex
        parent_span_id = parsed_trace[1] if parsed_trace else "0000000000000001"
        request_id = sanitize_request_id(request.headers.get("x-request-id")) or uuid4().hex

        request.state.trace_id = trace_id
        request.state.span_id = parent_span_id
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["traceparent"] = f"00-{trace_id}-0000000000000001-01"
        response.headers["x-request-id"] = request_id
        return response

    async def failure(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, KeyError):
            status, code = 404, "YIELD_RESOURCE_NOT_FOUND"
        elif isinstance(exc, httpx.HTTPStatusError):
            status, code = 502, "YIELD_HANDOFF_REJECTED"
        elif isinstance(exc, LlamaFactoryYamlError):
            status, code = 400, exc.code
        elif isinstance(exc, (httpx.HTTPError, grpc.RpcError)):
            status, code = 503, "YIELD_DEPENDENCY_UNAVAILABLE"
        elif isinstance(exc, ModelRegistryUnavailable):
            status, code = 503, "YIELD_MODEL_REGISTRY_UNAVAILABLE"
        elif isinstance(exc, ArtifactError):
            status, code = 422, "YIELD_ARTIFACT_UNAVAILABLE"
        else:
            code = str(exc).split(":", 1)[0]
            if not code.startswith("YIELD_") or not code.replace("_", "").isalnum():
                code = "YIELD_REQUEST_INVALID"
            status = 409 if any(item in code for item in ("CONFLICT", "STARTED", "PREPARED")) else 422

        mapped = map_yield_error(code)
        canonical_code = mapped["code"]
        recovery_action = mapped.get("recovery_action")

        trace_id = getattr(request.state, "trace_id", None) or uuid4().hex
        span_id = getattr(request.state, "span_id", None)
        request_id = getattr(request.state, "request_id", None)
        if code == "YIELD_EXECUTION_NOT_CONFIGURED":
            detail = (
                "Training execution is not configured. Run `cyrene service-prepare yield` to prepare the "
                "trainer runtime and Kernel configuration."
            )
        elif code == "YIELD_TRAINER_RUNTIME_UNAVAILABLE":
            detail = (
                "The trainer runtime is unavailable. Run `cyrene service-prepare yield`, then retry after "
                "the trainer is reported ready."
            )
        else:
            detail = (
                "The requested Product action did not complete. Check the selected resource or configured dependency."
            )

        emit_diagnostic_error(
            "product.yield.error",
            canonical_code,
            str(exc),
            trace_id=trace_id,
            span_id=span_id,
            attributes={
                "request_id": request_id,
                "cause_kind": mapped.get("cause_kind"),
                "status": status,
                "path": request.url.path,
                "legacy_code": code,
            },
        )

        return JSONResponse(
            status_code=status,
            media_type="application/problem+json",
            content={
                "type": "https://errors.cyrene.dev/yield/" + code.lower().replace("_", "-"),
                "title": code,
                "status": status,
                "code": code,
                "detail": detail,
                "instance": request.url.path,
                "retryable": status >= 500,
                "traceId": trace_id,
                "requestId": request_id,
                "recoveryAction": recovery_action,
            },
        )

    for kind in (
        KeyError,
        ValueError,
        ArtifactError,
        LlamaFactoryYamlError,
        httpx.HTTPError,
        grpc.RpcError,
        ModelRegistryUnavailable,
        RequestValidationError,
    ):
        app.add_exception_handler(kind, failure)

    @app.get("/health")
    @app.get("/healthz")
    @app.get("/")
    def health() -> dict[str, Any]:
        execution_block_reasons: list[str] = []
        execution_detail = None
        if not execution_available:
            execution_block_reasons.append("TRAINING_NOT_CONFIGURED")
            execution_detail = (
                "Run `cyrene service-prepare yield` to prepare the trainer runtime and Kernel configuration."
            )
        elif executor is None:
            execution_block_reasons.append("KERNEL_CAPABILITIES_UNAVAILABLE")
        else:
            trainer_runtime_available = executor.trainer_runtime_available()
            try:
                readiness = executor.execution_readiness(trainer_runtime_available=trainer_runtime_available)
            except Exception:
                execution_block_reasons.append("KERNEL_CAPABILITIES_UNAVAILABLE")
                execution_detail = "Kernel capability facts are unavailable."
                if not trainer_runtime_available:
                    execution_block_reasons.append("TRAINER_RUNTIME_UNAVAILABLE")
            else:
                execution_block_reasons.extend(
                    readiness.block_reasons(minimum_memory_bytes=executor.configuration.minimum_memory_bytes)
                )
                if not trainer_runtime_available:
                    execution_detail = "Trainer runtime is unavailable; run `cyrene service-prepare yield`."

        api_ready = not background_errors
        execution_ready = not execution_block_reasons

        response: dict[str, Any] = {
            "status": "READY" if api_ready else "DEGRADED",
            "apiReady": api_ready,
            "executionReady": execution_ready,
            "executionBlockReasons": execution_block_reasons,
            "trainingConfigured": execution_available,
            "modelRegistryConfigured": registry is not None,
            "reconcileErrors": list(background_errors),
        }
        if execution_detail:
            response["executionDetail"] = execution_detail
        return response

    @app.post(
        "/api/v1/training-drafts", response_model=TrainingDraft, status_code=201, response_model_exclude_none=True
    )
    def import_dataset(
        command: CreateTrainingDraft, idempotency_key: str | None = Header(default=None, max_length=200)
    ) -> TrainingDraft:
        return service.create_draft(command, idempotency_key)

    @app.post(
        "/internal/workspace/v1/training-drafts",
        response_model=TrainingDraft,
        status_code=201,
        response_model_exclude_none=True,
        include_in_schema=False,
    )
    def workspace_import_dataset(
        command: CreateTrainingDraft,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
        scope: WorkspaceScope = Depends(workspace_auth.authorize),
    ) -> TrainingDraft:
        return service.create_draft(command, idempotency_key, workspace_scope=scope)

    @app.get("/api/v1/training-drafts", response_model=list[TrainingDraft], response_model_exclude_none=True)
    def list_drafts() -> list[TrainingDraft]:
        return service.list_drafts()

    @app.post(
        "/api/v1/training-drafts/actions/import-llama-factory",
        response_model=TrainingDraft,
        status_code=201,
        response_model_exclude_none=True,
    )
    def import_llama_factory(
        command: ImportLlamaFactoryYaml,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
    ) -> TrainingDraft:
        return service.import_llama_factory_yaml(command, idempotency_key)

    @app.post(
        "/internal/workspace/v1/training-drafts/actions/import-llama-factory",
        response_model=TrainingDraft,
        status_code=201,
        response_model_exclude_none=True,
        include_in_schema=False,
    )
    def workspace_import_llama_factory(
        command: ImportLlamaFactoryYaml,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
        scope: WorkspaceScope = Depends(workspace_auth.authorize),
    ) -> TrainingDraft:
        return service.import_llama_factory_yaml(command, idempotency_key, workspace_scope=scope)

    @app.get("/api/v1/training-drafts/{draft_id}", response_model=TrainingDraft, response_model_exclude_none=True)
    def get_draft(draft_id: UUID) -> TrainingDraft:
        return get_draft_resource(draft_id)

    @app.get(
        "/internal/workspace/v1/training-drafts/{draft_id}",
        response_model=WorkspaceTrainingDraftProjection,
        response_model_exclude_none=True,
        include_in_schema=False,
    )
    def workspace_get_draft(
        draft_id: UUID,
        scope: WorkspaceScope = Depends(workspace_auth.authorize),
    ) -> WorkspaceTrainingDraftProjection:
        return project_workspace_training_draft(service.get_draft_for_workspace(draft_id, scope))

    def get_draft_resource(draft_id: UUID) -> TrainingDraft:
        """Resolve a draft through the same Product service for both route surfaces."""
        return service.get_draft(draft_id)

    @app.get("/api/v1/training-drafts/{draft_id}/exports/llama-factory.yaml")
    def export_llama_factory(draft_id: UUID) -> Response:
        return _yaml_response(service.export_llama_factory_yaml(draft_id), f"training-draft-{draft_id}.yaml")

    @app.patch("/api/v1/training-drafts/{draft_id}", response_model=TrainingDraft, response_model_exclude_none=True)
    def prepare_draft(draft_id: UUID, command: PrepareTrainingDraft) -> TrainingDraft:
        return service.prepare(draft_id, command)

    @app.patch(
        "/internal/workspace/v1/training-drafts/{draft_id}",
        response_model=TrainingDraft,
        response_model_exclude_none=True,
        include_in_schema=False,
    )
    def workspace_prepare_draft(
        draft_id: UUID,
        command: PrepareTrainingDraft,
        scope: WorkspaceScope = Depends(workspace_auth.authorize),
    ) -> TrainingDraft:
        return service.prepare(draft_id, command, workspace_scope=scope)

    @app.post(
        "/api/v1/training-drafts/{draft_id}/actions/start",
        response_model=TrainingRunResource,
        status_code=202,
        response_model_exclude_none=True,
    )
    def start_run(draft_id: UUID) -> TrainingRunResource:
        return start_run_resource(draft_id)

    @app.post(
        "/internal/workspace/v1/training-drafts/{draft_id}/actions/start",
        response_model=WorkspaceTrainingRunProjection,
        status_code=202,
        response_model_exclude_none=True,
        include_in_schema=False,
    )
    def workspace_start_run(
        draft_id: UUID,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
        scope: WorkspaceScope = Depends(workspace_auth.authorize),
    ) -> WorkspaceTrainingRunProjection:
        # Yield's stable ProductDraft idempotency key ensures one run per draft;
        # Authority additionally deduplicates the caller's optional request key.
        _ = idempotency_key
        return project_workspace_training_run(start_run_resource(draft_id, scope))

    @app.get(
        "/internal/workspace/v1/training-runs/{run_id}",
        response_model=WorkspaceScopedTrainingRunProjection,
        response_model_exclude_none=True,
        include_in_schema=False,
    )
    def workspace_get_run(
        run_id: UUID,
        scope: WorkspaceScope = Depends(workspace_auth.authorize),
    ) -> WorkspaceScopedTrainingRunProjection:
        """Read only a run owned by the credential's exact Workspace scope.

        只读取当前服务凭据固定 Workspace 所拥有的任务。
        """

        run = service.get_run(run_id, workspace_scope=scope)
        return project_workspace_scoped_training_run(run, scope)

    @app.post(
        "/internal/workspace/v1/training-runs/{run_id}/events/query",
        response_model=WorkspaceTrainingEventsPageProjection,
        response_model_exclude_none=True,
        include_in_schema=False,
    )
    def workspace_list_run_events(
        run_id: UUID,
        command: WorkspaceTrainingEventsQuery = Body(...),
        scope: WorkspaceScope = Depends(workspace_auth.authorize),
    ) -> WorkspaceTrainingEventsPageProjection:
        """Read one bounded durable event page for an exact scoped run.

        读取指定任务的有界持久事件页，并由 POST JSON 适配 Authority unary 调用。
        """

        page = service.events(
            run_id,
            after_sequence=command.after_sequence,
            limit=command.limit,
            workspace_scope=scope,
        )
        return project_workspace_run_events(page, run_id=run_id, scope=scope)

    @app.get(
        "/internal/workspace/v1/training-runs/{run_id}/attempts",
        response_model=WorkspaceTrainingAttemptsProjection,
        response_model_exclude_none=True,
        include_in_schema=False,
    )
    def workspace_list_run_attempts(
        run_id: UUID,
        scope: WorkspaceScope = Depends(workspace_auth.authorize),
    ) -> WorkspaceTrainingAttemptsProjection:
        """Read sanitized attempt summaries for one exact scoped run.

        只读取精确 Workspace 任务的脱敏阶段摘要。
        """

        attempts = service.list_attempts(run_id, workspace_scope=scope)
        return project_workspace_run_attempts(attempts, run_id=run_id, scope=scope)

    def start_run_resource(
        draft_id: UUID,
        scope: WorkspaceScope | None = None,
    ) -> TrainingRunResource:
        """Start the same Product operation regardless of the authenticated route."""
        if scope is not None:
            # Resolve scope before checking execution configuration so a private
            # caller cannot probe another Workspace's draft through this action.
            draft = service.get_draft_for_workspace(draft_id, scope)
        if not execution_available:
            return _unavailable()
        if scope is None:
            draft = service.get_draft(draft_id)
        # Preserve start idempotency and the draft-not-prepared error. Readiness
        # applies only to a new ProductRun acceptance; retries return its existing
        # run without making current Kernel availability part of run lookup.
        if draft.training_run is not None or draft.configuration is None:
            return service.start(draft_id, workspace_scope=scope)
        if executor is not None:
            trainer_runtime_available = executor.trainer_runtime_available(force=True)
            if not trainer_runtime_available:
                raise ValueError(
                    "YIELD_TRAINER_RUNTIME_UNAVAILABLE: Yield trainer manifest and locked runtime must be available"
                )
            try:
                readiness = executor.execution_readiness(trainer_runtime_available=trainer_runtime_available)
            except Exception as exc:
                raise ValueError(
                    "YIELD_KERNEL_CAPABILITIES_UNAVAILABLE: Kernel capability facts are unavailable"
                ) from exc
            blockers = readiness.block_reasons(minimum_memory_bytes=executor.configuration.minimum_memory_bytes)
            if blockers:
                reason = blockers[0]
                descriptions = {
                    "SYSTEM_ADAPTER_UNAVAILABLE": "Kernel must advertise adapter.linux-system.cgroup-v2",
                    "GPU_UNAVAILABLE": "Kernel must report an NVIDIA GPU with sufficient allocatable memory",
                    "GPU_ISOLATION_UNAVAILABLE": (
                        "Kernel must report sandbox.device-bpf-capable for the required hard GPU isolation"
                    ),
                    "TRAINER_RUNTIME_UNAVAILABLE": (
                        "Yield trainer manifest and locked LLaMA-Factory runtime must be available"
                    ),
                }
                reason = "TRAINER_RUNTIME_UNAVAILABLE" if "TRAINER_RUNTIME_UNAVAILABLE" in blockers else blockers[0]
                raise ValueError(f"YIELD_{reason}: {descriptions[reason]}")
            # These are live host prerequisites only. A passing snapshot does
            # not admit the selected lease binding; Kernel's binding-aware
            # StartWorker preflight and target-cgroup attach remain authoritative.
            # 这些只是实时主机前提。快照通过不代表所选租约绑定获准；Kernel 的绑定感知
            # StartWorker 准入及目标 cgroup 挂载仍是最终权威。
            # Share the checked live snapshot with runtime preflight; do not issue
            # a second capability read that could observe a different inventory.
            runtime.update_hardware_facts(readiness.hardware_facts)
        return service.start(draft_id, workspace_scope=scope)

    @app.get("/api/v1/training-runs/{run_id}", response_model=TrainingRunResource, response_model_exclude_none=True)
    def get_run(run_id: UUID, request: Request) -> TrainingRunResource:
        return service.get_run(
            run_id,
            trace_id=request.state.trace_id,
            span_id=request.state.span_id,
        )

    @app.get("/api/v1/training-runs", response_model=TrainingRunPage, response_model_exclude_none=True)
    def list_runs(
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        workspace_id: str | None = Query(default=None, max_length=200),
    ) -> TrainingRunPage:
        return service.list_runs(limit=limit, offset=offset, workspace_id=workspace_id)

    @app.post(
        "/api/v1/training-runs/{run_id}/actions/preflight",
        response_model=PreflightReport,
        response_model_exclude_none=True,
    )
    def preflight_run(run_id: UUID) -> PreflightReport:
        return service.preflight(run_id)

    @app.get(
        "/api/v1/training-runs/{run_id}/events",
        response_model=TrainingEventsPage,
        response_model_exclude_none=True,
    )
    def get_events(
        run_id: UUID,
        after_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=5000, ge=1, le=20_000),
    ) -> TrainingEventsPage:
        return service.events(run_id, after_sequence=after_sequence, limit=limit)

    @app.get("/api/v1/training-runs/{run_id}/events/stream")
    async def stream_events(
        run_id: UUID,
        request: Request,
        after_sequence: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        cursor = _event_cursor(after_sequence, last_event_id)
        # Validate before headers are sent; the generator cannot map a later
        # private-scope failure to the normal Product 404 response.
        service.require_legacy_run_visibility(run_id)

        async def body():
            nonlocal cursor
            while True:
                if await request.is_disconnected():
                    return
                page = service.events(run_id, after_sequence=cursor)
                for event in page.events:
                    cursor = event.sequence
                    yield _sse_event(event.kind, event.sequence, event.model_dump(mode="json", by_alias=True))
                # A terminal run can still have more than one durable event page.
                # 中文：已结束任务的持久事件也可能超过一页，读空后才发送结束帧。
                if page.terminal and not page.events:
                    yield _sse_event("done", cursor, {"state": page.state, "sequence": cursor})
                    return
                if page.terminal:
                    continue
                await asyncio.sleep(0.2)

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    @app.get(
        "/api/v1/training-runs/{run_id}/diagnostics",
        response_model=DiagnosticsPage,
        response_model_exclude_none=True,
    )
    def get_diagnostics(
        run_id: UUID,
        after_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> DiagnosticsPage:
        return service.diagnostics(run_id, after_sequence=after_sequence, limit=limit)

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

    @app.post(
        "/api/v1/training-runs/{run_id}/actions/resume",
        response_model=TrainingRunResource,
        status_code=202,
        response_model_exclude_none=True,
    )
    def resume_run(
        run_id: UUID,
        command: ResumeTrainingRun,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
    ) -> TrainingRunResource:
        return service.resume(run_id, command, idempotency_key)

    @app.get(
        "/api/v1/training-results/{result_id}", response_model=TrainingResultResource, response_model_exclude_none=True
    )
    def get_result(result_id: UUID) -> TrainingResultResource:
        return service.get_result(result_id)

    @app.get("/api/v1/training-results/{result_id}/exports/llama-factory.yaml")
    def export_result_llama_factory(result_id: UUID) -> Response:
        return _yaml_response(service.export_result_llama_factory_yaml(result_id), f"training-result-{result_id}.yaml")

    @app.post(
        "/api/v1/training-results/{result_id}/actions/send-to-exchange",
        response_model=GatewayRouteDraftReceipt,
        status_code=201,
        response_model_exclude_none=True,
    )
    def send_to_exchange(
        result_id: UUID,
        command: SendTrainingResultToExchange,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
    ) -> GatewayRouteDraftReceipt:
        return service.send_to_exchange(result_id, command, idempotency_key)

    @app.post(
        "/api/v1/training-results/{result_id}/actions/send-to-reactor",
        response_model=HandoffReceipt,
        response_model_exclude_none=True,
    )
    def send_to_reactor(result_id: UUID) -> HandoffReceipt:
        return service.send_to_reactor(result_id)

    return app


def _unavailable() -> Any:
    raise ValueError(
        "YIELD_EXECUTION_NOT_CONFIGURED: run `cyrene service-prepare yield` and configure a Kernel training host"
    )


def _yaml_response(document: str, filename: str) -> Response:
    return Response(
        content=document,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _event_cursor(after_sequence: int, last_event_id: str | None) -> int:
    if not last_event_id:
        return after_sequence
    try:
        cursor = int(last_event_id)
    except ValueError as exc:
        raise ValueError("YIELD_EVENT_SEQUENCE_INVALID: Last-Event-ID must be an integer") from exc
    if cursor < 0:
        raise ValueError("YIELD_EVENT_SEQUENCE_INVALID: Last-Event-ID must be non-negative")
    return max(after_sequence, cursor)


def _sse_event(name: str, sequence: int, payload: dict[str, Any]) -> str:
    return f"id: {sequence}\nevent: {name}\ndata: {json.dumps(payload, separators=(',', ':'), ensure_ascii=True)}\n\n"
