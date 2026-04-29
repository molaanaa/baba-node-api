"""Helpers comuni per la registrazione dei tools MCP."""
from __future__ import annotations
from typing import Any, Mapping
from pydantic import BaseModel
from baba_mcp.client import GatewayClient


async def call_gateway(
    client: GatewayClient, path: str, payload: BaseModel
) -> Mapping[str, Any]:
    """Serializza un input Pydantic con i nomi alias (PascalCase per il gateway)
    e fa POST. Tutti gli errori HTTP sono già tradotti in McpToolError dal client.
    """
    body = payload.model_dump(by_alias=True, exclude_none=True)
    return await client.post(path, body)
