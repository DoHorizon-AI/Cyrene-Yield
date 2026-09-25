"""
┌─────────────────────────────────────────────────────────────────────┐
│  📄 dataset_plugin.py                                              │
│  Module: cy_exec.training.validation.dataset_plugin                │
│  Role: Yield adapter for tool.dataset.validator.v1.                │
│                                                                     │
│  模块职责：Yield 到 Plugins 数据集校验能力的标准直连适配器。               │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

DATASET_VALIDATOR_CAPABILITY = "tool.dataset.validator.v1"
DATASET_VALIDATOR_INTERFACE_VERSION = "1"
DATASET_VALIDATOR_CONNECTION_ENV = "CYRENE_DATASET_VALIDATOR_CONNECTION_REF"


@dataclass(frozen=True, slots=True)
class ValidationError:
    """One owner-reported dataset validation error.

    由数据集所有方报告的一项校验错误。
    """

    row_index: int | None
    field: str | None
    message: str
    value: Any | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Validated Product projection of the capability response.

    对 capability 响应进行验证后的 Product 映射。
    """

    is_valid: bool
    row_count: int
    columns: list[str]
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    detected_format: str | None = None
    detected_schema: str | None = None


class DatasetValidationPort(Protocol):
    """Yield application port for reusable dataset validation.

    用于可复用数据集校验的 Yield 应用端口。
    """

    def validate(
        self,
        path: str,
        format_type: str = "auto",
        sample_size: int = 5,
        schema: str | None = None,
    ) -> ValidationResult:
        """Validate one staged training input through the canonical owner.

        通过规范所有者校验一个暂存后的训练输入。
        """


class DirectPluginDatasetValidator:
    """Invoke ``tool.dataset.validator.v1`` through one resolved endpoint.

    通过一个已解析端点调用 tool.dataset.validator.v1。
    """

    def __init__(self, client: Any, *, deadline_seconds: float = 30.0) -> None:
        self._client = client
        self._deadline_seconds = deadline_seconds

    @classmethod
    def from_environment(cls) -> DirectPluginDatasetValidator:
        """Create a validator from Platform-resolved connection configuration.

        根据 Platform 解析的连接配置创建 validator。
        """

        connection_ref = os.environ.get(DATASET_VALIDATOR_CONNECTION_ENV, "").strip()
        if not connection_ref:
            raise DatasetValidationUnavailable(
                f"set {DATASET_VALIDATOR_CONNECTION_ENV} to the resolved Plugin connection_ref"
            )
        try:
            from cyrene_plugin_runtime import DirectPluginClient

            client = DirectPluginClient.for_local_connection_ref(connection_ref)
        except ImportError as exc:
            raise DatasetValidationUnavailable(
                "cyrene-plugin-runtime is not installed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DatasetValidationUnavailable(f"connection_ref is invalid: {exc}") from exc
        return cls(client)

    def validate(
        self,
        path: str,
        format_type: str = "auto",
        sample_size: int = 5,
        schema: str | None = None,
    ) -> ValidationResult:
        """Invoke and validate the typed owner response.

        调用并校验有类型的所有者响应。
        """

        request = {
            "file_path": path,
            "format": format_type,
            "sample_size": sample_size,
            "schema": schema,
        }
        try:
            from cyrene_plugin_runtime import DirectPayload, DirectPluginError

            response = self._client.invoke(
                capability=DATASET_VALIDATOR_CAPABILITY,
                interface_version=DATASET_VALIDATOR_INTERFACE_VERSION,
                method="validate",
                request=DirectPayload(
                    type_url=(
                        "type.cyrene.io/tool.dataset.validator.v1.validate.request"
                    ),
                    value=json.dumps(
                        request, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8"),
                ),
                deadline_seconds=self._deadline_seconds,
            )
        except ImportError as exc:
            raise DatasetValidationUnavailable(
                "cyrene-plugin-runtime is not installed"
            ) from exc
        except DirectPluginError as exc:
            raise DatasetValidationUnavailable(f"direct invocation failed: {exc}") from exc
        if response.type_url != (
            "type.cyrene.io/tool.dataset.validator.v1.validate.response"
        ):
            raise DatasetValidationUnavailable("Plugin returned an unexpected response type")
        try:
            payload = json.loads(response.value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DatasetValidationUnavailable("Plugin returned invalid UTF-8 JSON") from exc
        return _result(payload)


class DatasetValidationUnavailable(RuntimeError):
    """The required reusable dataset validation capability is unavailable.

    所需的可复用数据集校验能力不可用。
    """


class UnavailableDatasetValidator:
    """Fail-closed adapter used when no resolved endpoint is configured.

    未配置已解析端点时使用的 fail-closed 适配器。
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def validate(
        self,
        path: str,
        format_type: str = "auto",
        sample_size: int = 5,
        schema: str | None = None,
    ) -> ValidationResult:
        del path, format_type, sample_size
        return ValidationResult(
            is_valid=False,
            row_count=0,
            columns=[],
            errors=[
                ValidationError(
                    row_index=None,
                    field="dataset.path",
                    message=f"Dataset validator unavailable: {self._reason}",
                )
            ],
            detected_schema=schema,
        )


def dataset_validator_from_environment() -> DatasetValidationPort:
    """Resolve the direct adapter or a stable fail-closed projection.

    解析直连适配器，或返回稳定的 fail-closed 映射。
    """

    try:
        return DirectPluginDatasetValidator.from_environment()
    except DatasetValidationUnavailable as exc:
        return UnavailableDatasetValidator(str(exc))


def _result(value: Any) -> ValidationResult:
    if not isinstance(value, dict):
        raise DatasetValidationUnavailable("Plugin response must be an object")
    errors_value = value.get("errors")
    if not isinstance(errors_value, list):
        raise DatasetValidationUnavailable("Plugin response errors must be an array")
    errors: list[ValidationError] = []
    for index, item in enumerate(errors_value):
        if not isinstance(item, dict) or not isinstance(item.get("message"), str):
            raise DatasetValidationUnavailable(
                f"Plugin response errors[{index}] is invalid"
            )
        errors.append(
            ValidationError(
                row_index=_optional_integer(item.get("row_index"), f"errors[{index}].row_index"),
                field=_optional_text(item.get("field"), f"errors[{index}].field"),
                message=item["message"],
                value=item.get("value"),
            )
        )
    return ValidationResult(
        is_valid=_boolean(value.get("valid"), "valid"),
        row_count=_integer(value.get("row_count"), "row_count"),
        columns=_text_list(value.get("columns"), "columns"),
        errors=errors,
        warnings=_text_list(value.get("warnings"), "warnings"),
        sample_rows=_mapping_list(value.get("sample_rows"), "sample_rows"),
        detected_format=_optional_text(value.get("detected_format"), "detected_format"),
        detected_schema=_optional_text(value.get("detected_schema"), "detected_schema"),
    )


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise DatasetValidationUnavailable(f"Plugin response {field} must be boolean")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DatasetValidationUnavailable(
            f"Plugin response {field} must be a non-negative integer"
        )
    return value


def _optional_integer(value: Any, field: str) -> int | None:
    return None if value is None else _integer(value, field)


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DatasetValidationUnavailable(f"Plugin response {field} must be text or null")
    return value


def _text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DatasetValidationUnavailable(f"Plugin response {field} must be a text array")
    return value


def _mapping_list(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DatasetValidationUnavailable(f"Plugin response {field} must be an object array")
    return value


__all__ = [
    "DATASET_VALIDATOR_CAPABILITY",
    "DATASET_VALIDATOR_CONNECTION_ENV",
    "DATASET_VALIDATOR_INTERFACE_VERSION",
    "DatasetValidationPort",
    "DatasetValidationUnavailable",
    "DirectPluginDatasetValidator",
    "UnavailableDatasetValidator",
    "ValidationError",
    "ValidationResult",
    "dataset_validator_from_environment",
]
