"""
┌─────────────────────────────────────────────────────────────────────┐
│  Module: cy_exec.training.workspace_auth                             │
│  Role: Authenticate private Workspace service requests.             │
│                                                                     │
│  模块职责：按服务端凭据映射校验 Workspace Product 调用及资源范围。      │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request

MINIMUM_WORKSPACE_TOKEN_BYTES = 32
MAXIMUM_CREDENTIALS = 1024
MAXIMUM_CREDENTIAL_MAP_BYTES = 256 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class WorkspaceScope:
    """Immutable server-side organization and Workspace assignment."""

    organization_id: str
    workspace_id: str


@dataclass(frozen=True, slots=True)
class _Credential:
    token_digest: bytes = field(repr=False)
    scope: WorkspaceScope


class WorkspaceServiceAuthenticator:
    """Resolve private bearer credentials to fixed server-side scopes.

    The operator map stores only SHA-256 digests. A missing map denies private
    routes with 503; an unknown bearer receives 401. No actor or role is read
    from request data.
    """

    def __init__(self, credential_map_json: str | None) -> None:
        self._credentials = self._parse_credential_map(credential_map_json)

    def __repr__(self) -> str:
        return f"WorkspaceServiceAuthenticator(credentials={len(self._credentials)})"

    @staticmethod
    def _parse_credential_map(raw: str | None) -> tuple[_Credential, ...]:
        if raw is None or raw == "":
            return ()
        try:
            encoded = raw.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("YIELD_WORKSPACE_CREDENTIAL_MAP_INVALID") from exc
        if len(encoded) > MAXIMUM_CREDENTIAL_MAP_BYTES:
            raise ValueError("YIELD_WORKSPACE_CREDENTIAL_MAP_INVALID")
        try:
            document: Any = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("YIELD_WORKSPACE_CREDENTIAL_MAP_INVALID") from exc
        if (
            not isinstance(document, dict)
            or set(document) != {"version", "credentials"}
            or type(document.get("version")) is not int
            or document["version"] != 1
            or not isinstance(document.get("credentials"), list)
            or not 1 <= len(document["credentials"]) <= MAXIMUM_CREDENTIALS
        ):
            raise ValueError("YIELD_WORKSPACE_CREDENTIAL_MAP_INVALID")

        credentials: list[_Credential] = []
        seen_digests: set[bytes] = set()
        for item in document["credentials"]:
            if not isinstance(item, dict) or set(item) != {"tokenSha256", "organizationId", "workspaceId"}:
                raise ValueError("YIELD_WORKSPACE_CREDENTIAL_MAP_INVALID")
            digest_text = item["tokenSha256"]
            organization_id = item["organizationId"]
            workspace_id = item["workspaceId"]
            if (
                not isinstance(digest_text, str)
                or not _SHA256_PATTERN.fullmatch(digest_text)
                or not isinstance(organization_id, str)
                or not 1 <= len(organization_id) <= 200
                or organization_id != organization_id.strip()
                or not organization_id.isprintable()
                or not isinstance(workspace_id, str)
                or not 1 <= len(workspace_id) <= 200
                or workspace_id != workspace_id.strip()
                or not workspace_id.isprintable()
            ):
                raise ValueError("YIELD_WORKSPACE_CREDENTIAL_MAP_INVALID")
            digest = bytes.fromhex(digest_text)
            if digest in seen_digests:
                raise ValueError("YIELD_WORKSPACE_CREDENTIAL_MAP_INVALID")
            seen_digests.add(digest)
            credentials.append(
                _Credential(
                    token_digest=digest,
                    scope=WorkspaceScope(
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                    ),
                )
            )
        return tuple(credentials)

    def authorize(self, request: Request) -> WorkspaceScope:
        """Match the bearer against every configured digest in constant time."""
        if not self._credentials:
            raise HTTPException(status_code=503, detail="YIELD_WORKSPACE_AUTH_UNAVAILABLE")

        authorization = request.headers.get("authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else ""
        try:
            token_bytes = token.encode("ascii")
        except UnicodeEncodeError:
            token_bytes = b""
        token_is_valid = len(token_bytes) >= MINIMUM_WORKSPACE_TOKEN_BYTES and all(
            33 <= value <= 126 for value in token_bytes
        )
        candidate = hashlib.sha256(token_bytes if token_is_valid else b"").digest()

        matched_scope: WorkspaceScope | None = None
        for credential in self._credentials:
            matches = secrets.compare_digest(candidate, credential.token_digest)
            if matches:
                matched_scope = credential.scope

        if not token_is_valid or matched_scope is None:
            raise HTTPException(
                status_code=401,
                detail="YIELD_WORKSPACE_UNAUTHORIZED",
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.workspace_scope = matched_scope
        return matched_scope
