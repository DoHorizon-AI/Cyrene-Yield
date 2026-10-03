"""Yield-internal environment policy contracts and deterministic resolver.

Yield 内部的环境策略契约与确定性解析器。
"""

from .contracts import (
    EnvironmentCandidate,
    EnvironmentLock,
    EnvironmentResolution,
    EnvironmentResolutionStatus,
    EnvironmentSpec,
    HardwareRuntimeFacts,
)
from .resolver import EnvironmentResolver, local_environment_candidate

__all__ = [
    "EnvironmentCandidate",
    "EnvironmentLock",
    "EnvironmentResolution",
    "EnvironmentResolutionStatus",
    "EnvironmentResolver",
    "EnvironmentSpec",
    "HardwareRuntimeFacts",
    "local_environment_candidate",
]
