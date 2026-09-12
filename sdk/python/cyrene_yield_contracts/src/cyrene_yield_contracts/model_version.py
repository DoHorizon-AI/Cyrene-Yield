"""Yield-owned immutable ModelVersion contract.

Artifact bytes and ArtifactRef identity remain in the Platform Artifact Plane.
Yield owns model composition, lineage, and content-derived ModelVersion identity.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from cy_artifacts import canonical_json_bytes

from .artifact_kind import YieldArtifactKind

MODEL_VERSION_SCHEMA_VERSION = "1"
MODEL_VERSION_URI_PREFIX = "model-version://sha256/"
ARTIFACT_URI_PREFIX = "artifact://sha256/"
SHA256_PREFIX = "sha256:"
JCS_SAFE_INTEGER_MAX = 9_007_199_254_740_991
_MODEL_VERSION_ID_PATTERN = re.compile(r"^model-version://sha256/[0-9a-f]{64}$")
_RESOURCE_URI_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _validate_lowercase_digest(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(SHA256_PREFIX)
        or len(value) != len(SHA256_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[len(SHA256_PREFIX) :])
    ):
        raise ValueError(f"digest must be lowercase sha256:<hex>: {value!r}")
    return value


def _artifact_uri_for_digest(digest: str) -> str:
    normalized = _validate_lowercase_digest(digest)
    return ARTIFACT_URI_PREFIX + normalized[len(SHA256_PREFIX) :]


def _safe_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0 or value > JCS_SAFE_INTEGER_MAX:
        raise ValueError(f"{field_name} must fit the JCS safe integer range")
    return value

def _as_json_object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise ValueError(f"{field_name} object keys must be strings")
    return result


def _expect_json_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    field_name: str,
) -> None:
    keys = set(value)
    unknown = keys - required - optional
    missing = required - keys
    if unknown:
        raise ValueError(f"{field_name} has unknown fields: {sorted(unknown)!r}")
    if missing:
        raise ValueError(f"{field_name} is missing fields: {sorted(missing)!r}")


def _reject_floats(value: Any, *, path: str = "$") -> None:
    """Reject values that cannot be represented without JCS number drift.

    ModelVersion V1 intentionally carries only strings, booleans, integers,
    arrays, objects, and null.  This keeps the Python canonical serializer
    byte-compatible with the JCS value subset used by the platform manifests.
    """

    if isinstance(value, float):
        raise ValueError(f"{path} must not contain floating-point numbers")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _reject_floats(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_floats(child, path=f"{path}[{index}]")


def _validate_resource_uri(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or not _RESOURCE_URI_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a non-empty opaque URI")
    if any(ord(character) < 32 or 0x7F <= ord(character) <= 0x9F for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _normalize_artifact_ref(
    value: Any,
    *,
    field_name: str,
    require_portable_model: bool = False,
) -> dict[str, Any]:
    data = _as_json_object(value, field_name)
    _expect_json_keys(
        data,
        required={"uri", "digest", "size_bytes", "kind"},
        optional={"manifest_digest"},
        field_name=field_name,
    )

    uri = data["uri"]
    digest = data["digest"]
    if not isinstance(uri, str) or not isinstance(digest, str):
        raise ValueError(f"{field_name}.uri and .digest must be strings")
    _validate_lowercase_digest(digest)
    if uri != _artifact_uri_for_digest(digest):
        raise ValueError(f"{field_name}.uri must match its digest")

    size_bytes = _safe_integer(data["size_bytes"], f"{field_name}.size_bytes")
    kind_value = data["kind"]
    if not isinstance(kind_value, str):
        raise ValueError(f"{field_name}.kind must be a string")
    try:
        kind = YieldArtifactKind(kind_value)
    except ValueError as exc:
        raise ValueError(f"{field_name}.kind is not a supported ArtifactKind") from exc

    has_manifest_digest = "manifest_digest" in data
    manifest_digest = data.get("manifest_digest")
    if has_manifest_digest:
        if not isinstance(manifest_digest, str) or not manifest_digest:
            raise ValueError(f"{field_name}.manifest_digest must be a non-empty string")
        _validate_lowercase_digest(manifest_digest)

    if require_portable_model:
        if kind is not YieldArtifactKind.MODEL:
            raise ValueError(f"{field_name} must use kind 'model'")
        if manifest_digest != digest:
            raise ValueError(f"{field_name} must reference a portable directory with manifest_digest equal to digest")

    normalized: dict[str, Any] = {
        "uri": uri,
        "digest": digest,
        "size_bytes": size_bytes,
        "kind": kind.value,
    }
    if has_manifest_digest:
        normalized["manifest_digest"] = manifest_digest
    return normalized


def _normalize_override(value: Any, *, field_name: str) -> dict[str, Any]:
    data = _as_json_object(value, field_name)
    _expect_json_keys(
        data,
        required={"mode"},
        optional={"artifact"},
        field_name=field_name,
    )
    mode = data["mode"]
    if mode == "INHERIT":
        if "artifact" in data:
            raise ValueError(f"{field_name}.artifact is forbidden when mode is INHERIT")
        return {"mode": mode}
    if mode == "OVERRIDE":
        if "artifact" not in data:
            raise ValueError(f"{field_name}.artifact is required when mode is OVERRIDE")
        return {
            "mode": mode,
            "artifact": _normalize_artifact_ref(data["artifact"], field_name=f"{field_name}.artifact"),
        }
    raise ValueError(f"{field_name}.mode must be INHERIT or OVERRIDE")


def _normalize_lineage(value: Any) -> dict[str, Any]:
    data = _as_json_object(value, "lineage")
    _expect_json_keys(
        data,
        required=set(),
        optional={"trainingRun", "datasetVersion", "inputArtifacts", "derivedFromModelVersion"},
        field_name="lineage",
    )
    normalized: dict[str, Any] = {}
    if "trainingRun" in data:
        normalized["trainingRun"] = _validate_resource_uri(data["trainingRun"], "lineage.trainingRun")
    if "datasetVersion" in data:
        normalized["datasetVersion"] = _validate_resource_uri(data["datasetVersion"], "lineage.datasetVersion")
    if "inputArtifacts" in data:
        input_artifacts = data["inputArtifacts"]
        if not isinstance(input_artifacts, list):
            raise ValueError("lineage.inputArtifacts must be an array")
        normalized["inputArtifacts"] = [
            _normalize_artifact_ref(item, field_name=f"lineage.inputArtifacts[{index}]")
            for index, item in enumerate(input_artifacts)
        ]
    if "derivedFromModelVersion" in data:
        derived = data["derivedFromModelVersion"]
        if not isinstance(derived, str) or not _MODEL_VERSION_ID_PATTERN.fullmatch(derived):
            raise ValueError("lineage.derivedFromModelVersion must be a model-version://sha256/<hex> URI")
        normalized["derivedFromModelVersion"] = derived
    return normalized


def _normalize_base_model(value: Any) -> dict[str, Any]:
    data = _as_json_object(value, "baseModel")
    _expect_json_keys(
        data,
        required={"artifact", "source"},
        optional=set(),
        field_name="baseModel",
    )
    source = _as_json_object(data["source"], "baseModel.source")
    _expect_json_keys(
        source,
        required={"repository", "revision"},
        optional=set(),
        field_name="baseModel.source",
    )
    repository = source["repository"]
    revision = source["revision"]
    if not isinstance(repository, str) or not _REPOSITORY_PATTERN.fullmatch(repository):
        raise ValueError("baseModel.source.repository must use the owner/repo form")
    if not isinstance(revision, str) or not _REVISION_PATTERN.fullmatch(revision):
        raise ValueError("baseModel.source.revision must be a lowercase 40-hex revision")
    return {
        "artifact": _normalize_artifact_ref(
            data["artifact"], field_name="baseModel.artifact", require_portable_model=True
        ),
        "source": {"repository": repository, "revision": revision},
    }


def _normalize_model_version_payload(
    payload: Any,
    *,
    require_id: bool,
) -> dict[str, Any]:
    _reject_floats(payload)
    data = _as_json_object(payload, "model version")
    common_required = {"schemaVersion", "composition", "tokenizer", "chatTemplate", "lineage"}
    common_optional = {"id"}
    composition = data.get("composition")
    if composition == "FULL_MODEL":
        _expect_json_keys(
            data,
            required=common_required | {"fullModelArtifact"} | ({"id"} if require_id else set()),
            optional=common_optional if not require_id else set(),
            field_name="model version",
        )
    elif composition == "BASE_PLUS_LORA":
        _expect_json_keys(
            data,
            required=common_required | {"baseModel", "adapterArtifact"} | ({"id"} if require_id else set()),
            optional=common_optional if not require_id else set(),
            field_name="model version",
        )
    else:
        raise ValueError("model version composition must be FULL_MODEL or BASE_PLUS_LORA")

    schema_version = data["schemaVersion"]
    if schema_version != MODEL_VERSION_SCHEMA_VERSION:
        raise ValueError(f"model version schemaVersion must be {MODEL_VERSION_SCHEMA_VERSION!r}")
    if not isinstance(composition, str):
        raise ValueError("model version composition must be a string")

    normalized: dict[str, Any] = {
        "schemaVersion": schema_version,
        "composition": composition,
    }
    if require_id:
        model_id = data["id"]
        if not isinstance(model_id, str) or not _MODEL_VERSION_ID_PATTERN.fullmatch(model_id):
            raise ValueError("model version id must be a model-version://sha256/<hex> URI")
        normalized["id"] = model_id

    if composition == "FULL_MODEL":
        normalized["fullModelArtifact"] = _normalize_artifact_ref(
            data["fullModelArtifact"],
            field_name="fullModelArtifact",
            require_portable_model=True,
        )
    else:
        normalized["baseModel"] = _normalize_base_model(data["baseModel"])
        normalized["adapterArtifact"] = _normalize_artifact_ref(
            data["adapterArtifact"],
            field_name="adapterArtifact",
            require_portable_model=True,
        )
        if normalized["baseModel"]["artifact"]["digest"] == normalized["adapterArtifact"]["digest"]:
            raise ValueError("baseModel.artifact and adapterArtifact must be different artifacts")

    normalized["tokenizer"] = _normalize_override(data["tokenizer"], field_name="tokenizer")
    normalized["chatTemplate"] = _normalize_override(data["chatTemplate"], field_name="chatTemplate")
    normalized["lineage"] = _normalize_lineage(data["lineage"])
    return normalized


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(child) for child in value]
    return value


def _model_version_id(identity_payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(identity_payload)).hexdigest()
    return MODEL_VERSION_URI_PREFIX + digest


@dataclass(frozen=True, slots=True, init=False)
class ModelVersion:
    """Immutable canonical model composition consumed by Product contracts.

    This helper owns only the content-addressed descriptor.  TrainingRun is
    owned by Yield and DatasetVersion is owned by Catalyst; both appear here
    only as opaque lineage references.  LoRA rank, alpha, and target modules
    remain in the adapter payload and are intentionally absent from this
    descriptor.
    """

    _payload: Mapping[str, Any] = field(repr=False, compare=False)
    _id: str = field(repr=False)

    def __new__(cls, *_args: Any, **_kwargs: Any) -> "ModelVersion":
        raise TypeError("ModelVersion instances must be created with create() or from_dict()")

    @classmethod
    def _from_normalized(cls, payload: Mapping[str, Any]) -> "ModelVersion":
        """Build an instance after create/from_dict have completed validation."""

        model_id = payload["id"]
        instance = object.__new__(cls)
        object.__setattr__(instance, "_payload", _freeze_json(dict(payload)))
        object.__setattr__(instance, "_id", model_id)
        return instance

    @classmethod
    def create(cls, payload_without_id: Mapping[str, Any]) -> "ModelVersion":
        data = _as_json_object(payload_without_id, "model version")
        if "id" in data:
            raise ValueError("ModelVersion.create expects the id field to be omitted")
        normalized = _normalize_model_version_payload(data, require_id=False)
        model_id = _model_version_id(normalized)
        complete = dict(normalized)
        complete["id"] = model_id
        return cls._from_normalized(complete)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ModelVersion":
        normalized = _normalize_model_version_payload(payload, require_id=True)
        model_id = normalized["id"]
        identity_payload = {key: value for key, value in normalized.items() if key != "id"}
        expected_id = _model_version_id(identity_payload)
        if model_id != expected_id:
            raise ValueError(f"model version id does not match its immutable content: expected {expected_id}")
        return cls._from_normalized(normalized)

    @property
    def id(self) -> str:
        return self._id

    @property
    def composition(self) -> str:
        return self._payload["composition"]

    def identity_payload(self) -> dict[str, Any]:
        """Return the canonical hash preimage without the computed id."""

        return {key: _thaw_json(value) for key, value in self._payload.items() if key != "id"}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible copy of the immutable value."""

        return _thaw_json(self._payload)
