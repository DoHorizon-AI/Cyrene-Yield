"""Yield adapter for the Plugins-owned LLaMA Factory capability."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from ...checkpoint import CheckpointManager
from ...contracts import (
    EngineInspect,
    EngineKind,
    EngineValidation,
    TrainingEvent,
    TrainingEventKind,
    TrainingLaunchSpec,
    TrainingResult,
    TrainingSpec,
    TrainingStatus,
    require_engine_kind,
)
from ...validation import validate_training_spec

LOGGER = logging.getLogger("cy_exec.training.engines.llamafactory")
CAPABILITY_ID = "training.llama-factory.v1"
INTERFACE_VERSION = "1"


class LlamaFactoryPluginConnection:
    """Small Product-side connector for one resolved DirectPlugin endpoint."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_environment(cls) -> "LlamaFactoryPluginConnection":
        connection_ref = os.environ.get("CYRENE_LLAMA_FACTORY_CONNECTION_REF", "").strip()
        if not connection_ref:
            raise RuntimeError(
                "YIELD_PLUGIN_UNAVAILABLE: set CYRENE_LLAMA_FACTORY_CONNECTION_REF "
                "to the resolved training.llama-factory.v1 endpoint"
            )
        try:
            from cyrene_plugin_runtime import DirectPluginClient
        except ImportError as exc:
            raise RuntimeError(
                "YIELD_PLUGIN_RUNTIME_MISSING: install the Plugins direct runtime SDK"
            ) from exc
        return cls(DirectPluginClient.for_local_connection_ref(connection_ref))

    def invoke(self, method: str, request: dict[str, Any]) -> dict[str, Any]:
        """Invoke one typed JSON method and decode only capability-owned bytes."""
        request_type_url = f"type.cyrene.io/{CAPABILITY_ID}.{method}.request"
        response = self._client.invoke(
            capability=CAPABILITY_ID,
            interface_version=INTERFACE_VERSION,
            method=method,
            request=self._payload(request_type_url, request),
        )
        return json.loads(response.value.decode("utf-8"))

    @staticmethod
    def _payload(type_url: str, request: dict[str, Any]) -> Any:
        from cyrene_plugin_runtime import DirectPayload

        return DirectPayload(type_url=type_url, value=json.dumps(request).encode("utf-8"))


class LlamaFactoryEngineAdapter:
    """Adapt Yield contracts to the Plugins-owned LLaMA Factory endpoint."""

    kind = EngineKind.LLAMA_FACTORY

    def __init__(self, connection: LlamaFactoryPluginConnection | Any | None = None) -> None:
        self._connection = connection

    def _resolved_connection(self) -> Any:
        if self._connection is None:
            self._connection = LlamaFactoryPluginConnection.from_environment()
        return self._connection

    def inspect(self) -> EngineInspect:
        notes = [
            "Plugins-owned LLaMA Factory implementation via DirectPluginRuntime.",
            "Yield owns Product lifecycle and attempt state.",
        ]
        try:
            result = self._resolved_connection().invoke("inspect", {})
        except RuntimeError as exc:
            notes.append(str(exc))
            return EngineInspect(
                engine=self.kind,
                available=False,
                supported_strategies=[],
                supported_finetune_types=[],
                notes=notes,
            )
        from ...contracts.status import DistributedStrategy

        return EngineInspect(
            engine=self.kind,
            available=bool(result.get("available")),
            version=result.get("version"),
            supported_strategies=[
                DistributedStrategy(value)
                for value in result.get("supported_strategies", [])
                if value in {item.value for item in DistributedStrategy}
            ],
            supported_finetune_types=list(result.get("supported_finetune_types", [])),
            notes=notes + list(result.get("notes", [])),
        )

    def validate(self, spec: TrainingSpec) -> EngineValidation:
        require_engine_kind(spec, self.kind)
        return validate_training_spec(spec)

    def compile(self, spec: TrainingSpec) -> TrainingLaunchSpec:
        require_engine_kind(spec, self.kind)
        validation = self.validate(spec)
        if not validation.ok:
            messages = "; ".join(issue.message for issue in validation.issues)
            raise ValueError(f"LLaMA-Factory spec is invalid: {messages}")
        result = self._resolved_connection().invoke("compile", {"spec": spec.to_dict()})
        launch = result.get("launch")
        if not isinstance(launch, dict):
            raise ValueError("YIELD_PLUGIN_PROTOCOL_INVALID: compile response has no launch")
        return TrainingLaunchSpec(**launch)

    def parse_event(self, line: str) -> TrainingEvent | None:
        text = line.strip()
        if not text:
            return None
        try:
            result = self._resolved_connection().invoke("parse_event", {"line": text})
        except RuntimeError:
            return TrainingEvent(kind=TrainingEventKind.LOG, message=text, raw=text)
        if not result:
            return None
        kind = TrainingEventKind(result.get("kind", "log"))
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        return TrainingEvent(
            kind=kind,
            message=str(result.get("message") or text),
            step=_as_int(payload.get("current_steps") or payload.get("step") or result.get("step")),
            loss=_as_float(payload.get("loss") or result.get("loss")),
            learning_rate=_as_float(payload.get("learning_rate") or result.get("learning_rate")),
            raw=str(result.get("raw") or text),
            payload=payload,
        )

    def collect_result(
        self,
        spec: TrainingSpec,
        launch: TrainingLaunchSpec,
        exit_code: int | None,
        status: TrainingStatus,
    ) -> TrainingResult:
        manager = CheckpointManager(spec.output_dir, save_total_limit=spec.checkpoint.save_total_limit)
        digest, size, path = manager.collect_digest(spec.output_dir)
        if not digest:
            digest, size, path = manager.collect_digest()
        message = "training finished"
        if status == TrainingStatus.CANCELLED:
            message = "training cancelled"
        elif status == TrainingStatus.LOST:
            message = "training process could not be confirmed stopped"
        elif status == TrainingStatus.FAILED:
            message = f"training failed with exit code {exit_code}"
        return TrainingResult(
            status=status,
            output_dir=spec.output_dir,
            checkpoint_path=path,
            checkpoint_digest=digest,
            checkpoint_size_bytes=size,
            exit_code=exit_code,
            message=message,
        )


def _as_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
