"""Async HTTP client verso il gateway baba-node-api.

- POST JSON con header opzionale `Authorization: Bearer <MCP_AUTH_TOKEN>`.
- Retry esponenziale (1s/2s/4s) solo su 503 e timeout.
- Tutti gli altri errori HTTP sono tradotti in McpToolError tramite
  baba_mcp.errors.map_http_error.
"""
from __future__ import annotations
import asyncio
import json
import httpx
from typing import Any, Mapping, Optional

from baba_mcp.errors import map_http_error, McpToolError


class GatewayClient:
    def __init__(
        self,
        base_url: str,
        timeout_ms: int = 120_000,
        max_retries: int = 3,
        auth_token: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_ms / 1000.0
        self._max_retries = max_retries
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_s,
            headers=headers,
            transport=transport,
        )

    async def post(self, path: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        last_err: Optional[McpToolError] = None
        payload = json.dumps(dict(body))
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.post(path, content=payload)
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_err = McpToolError(
                    "node_unavailable", f"transport: {e}", {"attempt": attempt + 1}
                )
                await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code == 503:
                try:
                    body_json = resp.json()
                except Exception:
                    body_json = {"success": False}
                last_err = map_http_error(503, body_json)
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise last_err

            if 200 <= resp.status_code < 300:
                return resp.json()

            try:
                body_json = resp.json()
            except Exception:
                body_json = {"message": resp.text or f"HTTP {resp.status_code}"}
            raise map_http_error(resp.status_code, body_json)

        assert last_err is not None
        raise last_err

    async def aclose(self) -> None:
        await self._client.aclose()
