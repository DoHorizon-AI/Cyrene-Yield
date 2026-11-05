"""
┌─────────────────────────────────────────────────────────────────────┐
│  📄 kernel_rpc.py                                                   │
│  Module: cy_exec.training.executors.kernel_rpc                     │
│  Role: Client projection of the pinned Platform Protobuf contract. │
│  模块职责：读取平台生成的描述符，调用现有 Kernel 权威；不分配资源。          │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory

CONTRACT = {"contractId": "cyrene.kernel.semantic", "major": 1, "minor": 0}


def context(key: str) -> dict[str, Any]:
    """Keep mutation identity explicit across transport retries. | 保留幂等请求身份。"""
    return {"contract": CONTRACT, "requestId": str(uuid4()), "idempotencyKey": key}


class KernelClient:
    """A local UDS client; Kernel authenticates SO_PEERCRED. | 本地凭据认证客户端。"""

    def __init__(self, socket: Path, descriptor: Path | None = None) -> None:
        data = (descriptor or Path(__file__).with_name("kernel.desc")).read_bytes()
        self.pool = descriptor_pool.DescriptorPool()
        for item in descriptor_pb2.FileDescriptorSet.FromString(data).file:
            self.pool.Add(item)
        # grpc's generated UDS authority is rejected by older tonic/h2 versions.
        # 中文:较旧版本的 tonic/h2 会拒绝 grpc 生成的 UDS authority。
        # 只修正 HTTP/2 authority;节点身份仍由 UDS 凭据及 Kernel NodeRef 决定。
        # 中文:这里只修正 HTTP/2 authority;节点身份仍由 UDS 凭据及 Kernel NodeRef 决定。
        self.channel = grpc.insecure_channel(f"unix://{socket}", options=[("grpc.default_authority", "localhost")])

    def call(self, service: str, method: str, payload: dict[str, Any], *, timeout: float = 15) -> dict[str, Any]:
        """Invoke a canonical unary RPC without introducing another schema. | 调用规范的一元 RPC,不另行引入 schema。"""
        descriptor = self.pool.FindServiceByName(f"cyrene.core.v1.{service}")
        operation = descriptor.methods_by_name[method]
        request_type = message_factory.GetMessageClass(operation.input_type)
        response_type = message_factory.GetMessageClass(operation.output_type)
        request = json_format.ParseDict(payload, request_type())
        response = self.channel.unary_unary(
            f"/{descriptor.full_name}/{method}",
            request_serializer=request_type.SerializeToString,
            response_deserializer=response_type.FromString,
        )(request, timeout=timeout)
        return dict(json_format.MessageToDict(response))

    def authority(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Call the existing Lease/Worker authority. | 调用现有的 Lease/Worker 权威接口。"""
        # The default Kernel stop can spend 30s draining/reaping plus 2s on its
        # Kernel 默认停止流程可能花 30 秒排空/回收,再花 2 秒执行
        # sandbox RPC. Keep the release deadline within the Host client's 45s.
        # 默认清理预算为 32 秒;释放 RPC 须等待物理清理, 且短于 Host 的 45 秒期限。
        timeout = 40 if method == "ReleaseLease" else 15
        return self.call("KernelAuthorityService", method, payload, timeout=timeout)

    def capabilities(self) -> dict[str, Any]:
        """Read current Kernel inventory; online is not serving readiness. | 读取当前 Kernel 清单;在线状态不代表可对外服务的就绪状态。"""
        return self.call("KernelService", "GetKernelCapabilities", {})

    def encode(self, name: str, payload: dict[str, Any]) -> bytes:
        """Encode a canonical message for the Rust placement adapter. | 为 Rust placement adapter 编码规范消息。"""
        kind = message_factory.GetMessageClass(self.pool.FindMessageTypeByName(name))
        return bytes(json_format.ParseDict(payload, kind()).SerializeToString())

    def worker_control(self, outgoing: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        """Connect the worker's actual heartbeat/drain stream. | 连接 Worker 实际使用的 heartbeat/drain 流。"""
        service = self.pool.FindServiceByName("cyrene.core.v1.WorkerControlService")
        operation = service.methods_by_name["Connect"]
        req = message_factory.GetMessageClass(operation.input_type)
        res = message_factory.GetMessageClass(operation.output_type)
        stream = self.channel.stream_stream(
            f"/{service.full_name}/Connect",
            request_serializer=req.SerializeToString,
            response_deserializer=res.FromString,
        )
        for response in stream(json_format.ParseDict(item, req()) for item in outgoing):
            yield dict(json_format.MessageToDict(response))

    def close(self) -> None:
        """Release the client channel, never the Kernel-owned Lease. | 释放客户端 channel;绝不释放由 Kernel 管理的 Lease。"""
        self.channel.close()
