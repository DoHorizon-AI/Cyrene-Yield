"""Verify Yield exposes only the Plugins-owned training engine seam.

验证 Yield 只暴露 Plugins 所有的训练引擎接缝。
"""

from __future__ import annotations

import sys

import pytest

from cy_exec.training.contracts import EngineKind
from cy_exec.training.engines import available_engines, get_engine
from cy_exec.training.engines.llamafactory.adapter import (
    LlamaFactoryEngineAdapter,
    LlamaFactoryPluginConnection,
)
from training_tck_helpers import make_spec


def test_only_plugins_owned_engine_is_registered():
    assert set(available_engines()) == {"llamafactory"}
    assert isinstance(get_engine(EngineKind.LLAMA_FACTORY), LlamaFactoryEngineAdapter)


def test_removed_in_tree_engine_is_not_a_public_contract_value():
    with pytest.raises(ValueError):
        EngineKind("native_transformers")


def test_llama_seam_fails_closed_when_connection_is_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("CYRENE_LLAMA_FACTORY_CONNECTION_REF", raising=False)

    with pytest.raises(RuntimeError, match="YIELD_PLUGIN_UNAVAILABLE"):
        LlamaFactoryPluginConnection.from_environment()

    adapter = LlamaFactoryEngineAdapter(connection=None)
    spec = make_spec(tmp_path, EngineKind.LLAMA_FACTORY)

    with pytest.raises(RuntimeError, match="YIELD_PLUGIN_UNAVAILABLE"):
        adapter.compile(spec)

    inspect_info = adapter.inspect()
    assert inspect_info.available is False
    assert any("YIELD_PLUGIN_UNAVAILABLE" in note for note in inspect_info.notes)


def test_llama_seam_fails_closed_when_runtime_is_missing(monkeypatch):
    monkeypatch.setenv("CYRENE_LLAMA_FACTORY_CONNECTION_REF", "127.0.0.1:9999")
    monkeypatch.setitem(sys.modules, "cyrene_plugin_runtime", None)

    with pytest.raises(RuntimeError, match="YIELD_PLUGIN_RUNTIME_MISSING"):
        LlamaFactoryPluginConnection.from_environment()
