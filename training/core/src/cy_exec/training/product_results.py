"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.product_results                            │
│  Role: Publish verified single-LoRA results through Artifact Plane. │
│  模块职责：验证训练产物，引用平台制品与模型版本契约；不拥有制品存储。       │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import shutil
import struct
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cy_artifacts import ArtifactKind, ArtifactProvider, ArtifactRef
from cyrene_yield_contracts import MODEL_VERSION_SCHEMA_VERSION, ModelVersion, YieldArtifactKind

ADAPTER_MEMBERS = ("adapter_config.json", "adapter_model.safetensors")


def publish_adapter(
    provider: ArtifactProvider,
    output: Path,
    *,
    base_source: Mapping[str, str],
    staged_base: str,
) -> ArtifactRef:
    """Publish only the PEFT config and weights, never the trainer workspace.

    The trainer resolved the immutable base into a private directory. Replace
    that transport location with its selected immutable upstream identity in
    the exported PEFT configuration; all PEFT tuning facts remain untouched.
    中文：只发布 PEFT 配置和权重，不发布 trainer workspace。trainer 将不可变基座解析到私有目录后，在导出的 PEFT 配置中用所选的不可变上游身份替换该传输路径；所有 PEFT 调参事实保持不变。
    """
    for name in ADAPTER_MEMBERS:
        path = output / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"YIELD_ADAPTER_INCOMPLETE: missing regular {name}")
    config_path = output / ADAPTER_MEMBERS[0]
    if config_path.stat().st_size > 1024 * 1024:
        raise ValueError("YIELD_ADAPTER_CONFIG_INVALID: configuration is too large")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("peft_type") != "LORA":
        raise ValueError("YIELD_ADAPTER_UNSUPPORTED: PEFT LORA is required")
    if config.get("task_type") != "CAUSAL_LM":
        raise ValueError("YIELD_ADAPTER_UNSUPPORTED: text causal LM is required")
    if config.get("base_model_name_or_path") not in {staged_base, base_source["repository"]}:
        raise ValueError("YIELD_ADAPTER_BASE_MISMATCH: trainer reported another base")
    if config.get("revision") not in {None, base_source["revision"]}:
        raise ValueError("YIELD_ADAPTER_BASE_MISMATCH: trainer reported another revision")
    _verify_weights(output / ADAPTER_MEMBERS[1])
    config["base_model_name_or_path"] = base_source["repository"]
    config["revision"] = base_source["revision"]
    with tempfile.TemporaryDirectory(prefix="yield-adapter-") as temporary:
        stage = Path(temporary)
        (stage / ADAPTER_MEMBERS[0]).write_text(
            json.dumps(config, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        shutil.copyfile(output / ADAPTER_MEMBERS[1], stage / ADAPTER_MEMBERS[1])
        return provider.publish_portable_directory(stage, kind=ArtifactKind(YieldArtifactKind.MODEL))


def compose_result(
    *,
    run_ref: str,
    dataset_ref: str,
    base_model: Mapping[str, Any],
    adapter: ArtifactRef,
    dataset_artifacts: list[ArtifactRef],
    tokenizer: Mapping[str, Any],
    chat_template: Mapping[str, Any],
) -> ModelVersion:
    """Create the Yield-owned model descriptor using opaque Product lineage refs.

    使用不透明 Product lineage 引用创建 Yield 所有的模型描述符。
    """
    return ModelVersion.create(
        {
            "schemaVersion": MODEL_VERSION_SCHEMA_VERSION,
            "composition": "BASE_PLUS_LORA",
            "baseModel": dict(base_model),
            "adapterArtifact": adapter.to_dict(),
            "tokenizer": dict(tokenizer),
            "chatTemplate": dict(chat_template),
            "lineage": {
                "trainingRun": run_ref,
                "datasetVersion": dataset_ref,
                "inputArtifacts": [item.to_dict() for item in dataset_artifacts],
            },
        }
    )


def _verify_weights(path: Path) -> None:
    """Reject truncated or empty safetensors before publishing a successful result.

    在发布成功结果前拒绝截断或为空的 safetensors。
    """
    with path.open("rb") as stream:
        prefix = stream.read(8)
        if len(prefix) != 8:
            raise ValueError("YIELD_ADAPTER_WEIGHTS_INVALID: missing safetensors header")
        length = struct.unpack("<Q", prefix)[0]
        if length > 16 * 1024 * 1024 or length < 2:
            raise ValueError("YIELD_ADAPTER_WEIGHTS_INVALID: invalid header length")
        header = json.loads(stream.read(length))
    if not isinstance(header, dict):
        raise ValueError("YIELD_ADAPTER_WEIGHTS_INVALID: header must be an object")
    payload_size = path.stat().st_size - 8 - length
    ranges = []
    for name, tensor in header.items():
        if name == "__metadata__":
            continue
        offsets = tensor.get("data_offsets") if isinstance(tensor, dict) else None
        if (
            not isinstance(offsets, list)
            or len(offsets) != 2
            or any(type(value) is not int for value in offsets)
            or not 0 <= offsets[0] < offsets[1] <= payload_size
        ):
            raise ValueError("YIELD_ADAPTER_WEIGHTS_INVALID: inconsistent tensor range")
        ranges.append(tuple(offsets))
    ranges.sort()
    if (
        not ranges
        or ranges[0][0] != 0
        or ranges[-1][1] != payload_size
        or any(left[1] != right[0] for left, right in zip(ranges, ranges[1:]))
    ):
        raise ValueError("YIELD_ADAPTER_WEIGHTS_INVALID: incomplete tensor payload")
