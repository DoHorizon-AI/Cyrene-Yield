"""TrainingSpec: what the user wants to train.

This is the product-facing intent. It is engine-agnostic. Engine-specific
details belong in extra or in the compiled TrainingLaunchSpec.
"""
# ┌─────────────────────────────────────────────────────────────────────┐
# │ 📄 training/core/src/cy_exec/training/contracts/spec.py
# │ Module: training/core/src/cy_exec/training/contracts/spec
# │ Role: Canonical Yield training runtime — owns training contracts, attempts, executors, engines, checkpoints, and preflight.
# │
# │ 模块职责：Yield 标准训练运行时——负责训练契约、尝试、执行器、引擎、检查点与前置校验。
# └─────────────────────────────────────────────────────────────────────┘


from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .checkpoint import CheckpointSpec
from .distributed import DistributedSpec
from .status import EngineKind
from ..environment import EnvironmentSpec


@dataclass
class DatasetRef:
    path: str
    dataset_dir: Optional[str] = None
    name: Optional[str] = None
    format: str = "auto"
    schema: Optional[str] = None
    settings_path: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatasetRef":
        return cls(**data)


@dataclass
class ModelRef:
    path: str
    name: Optional[str] = None
    trust_remote_code: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelRef":
        return cls(**data)


@dataclass
class LoRASpec:
    enabled: bool = True
    r: int = 64
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    target_modules: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LoRASpec":
        if not data:
            return cls()
        return cls(**data)


@dataclass
class QuantizationSpec:
    use_4bit: bool = True
    bnb_4bit_quant_type: str = "nf4"
    bnb_4bit_compute_dtype: str = "bfloat16"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "QuantizationSpec":
        if not data:
            return cls()
        return cls(**data)


@dataclass
class HyperparamSpec:
    num_train_epochs: float = 3.0
    per_device_batch_size: int = 2
    gradient_accumulation_steps: int = 8
    learning_rate: float = 2e-4
    warmup_ratio: float = 0.03
    max_seq_length: int = 2048
    logging_steps: int = 10
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "HyperparamSpec":
        if not data:
            return cls()
        return cls(**data)


@dataclass
class TrainingSpec:
    """User intent: which model, data, engine, and training shape."""

    engine: EngineKind
    model: ModelRef
    dataset: DatasetRef
    output_dir: str
    environment: Optional[EnvironmentSpec] = None
    job_id: Optional[str] = None
    character_name: str = ""
    finetuning_type: str = "lora"
    stage: str = "sft"
    lora: LoRASpec = field(default_factory=LoRASpec)
    quantization: QuantizationSpec = field(default_factory=QuantizationSpec)
    hyperparams: HyperparamSpec = field(default_factory=HyperparamSpec)
    distributed: DistributedSpec = field(default_factory=DistributedSpec)
    checkpoint: CheckpointSpec = field(default_factory=CheckpointSpec)
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.engine, str):
            self.engine = EngineKind(self.engine)
        if isinstance(self.model, dict):
            self.model = ModelRef.from_dict(self.model)
        if isinstance(self.dataset, dict):
            self.dataset = DatasetRef.from_dict(self.dataset)
        if isinstance(self.environment, dict):
            self.environment = EnvironmentSpec.from_dict(self.environment)
        if isinstance(self.lora, dict):
            self.lora = LoRASpec.from_dict(self.lora)
        if isinstance(self.quantization, dict):
            self.quantization = QuantizationSpec.from_dict(self.quantization)
        if isinstance(self.hyperparams, dict):
            self.hyperparams = HyperparamSpec.from_dict(self.hyperparams)
        if isinstance(self.distributed, dict):
            self.distributed = DistributedSpec.from_dict(self.distributed)
        if isinstance(self.checkpoint, dict):
            self.checkpoint = CheckpointSpec.from_dict(self.checkpoint)
        if not self.checkpoint.output_dir:
            self.checkpoint.output_dir = self.output_dir
        if self.checkpoint.save_steps and not self.hyperparams.extra.get("save_steps"):
            pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine.value,
            "model": self.model.to_dict(),
            "dataset": self.dataset.to_dict(),
            "output_dir": self.output_dir,
            "environment": None if self.environment is None else self.environment.to_dict(),
            "job_id": self.job_id,
            "character_name": self.character_name,
            "finetuning_type": self.finetuning_type,
            "stage": self.stage,
            "lora": self.lora.to_dict(),
            "quantization": self.quantization.to_dict(),
            "hyperparams": self.hyperparams.to_dict(),
            "distributed": self.distributed.to_dict(),
            "checkpoint": self.checkpoint.to_dict(),
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingSpec":
        payload = dict(data)
        return cls(**payload)
