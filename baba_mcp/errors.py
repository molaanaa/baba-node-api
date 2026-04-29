"""Mapping fra errori HTTP del gateway e codici di errore MCP strutturati.

Codici esposti agli agenti:
  invalid_input   - 400: schema sbagliato; non ritentare con stesso input
  not_found       - 404: risorsa inesistente; smetti di cercare
  node_unavailable- 503: nodo Credits offline; retry con backoff
  rate_limited    - 429: gateway rate limit superato
  node_error      - 500 con `messageError` dal nodo Credits (es. wrong signature)
  internal        - altri 5xx: errore inatteso del gateway
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass
class McpToolError(Exception):
    code: str
    message: str
    details: Mapping[str, Any]

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def map_http_error(status: int, body: Mapping[str, Any]) -> McpToolError:
    msg = body.get("messageError") or body.get("message") or f"HTTP {status}"
    if status == 400:
        return McpToolError("invalid_input", msg, body)
    if status == 404:
        return McpToolError("not_found", msg, body)
    if status == 429:
        return McpToolError("rate_limited", msg, body)
    if status == 503:
        return McpToolError("node_unavailable", msg, body)
    if status == 500 and body.get("messageError"):
        return McpToolError("node_error", msg, body)
    return McpToolError("internal", msg, body)
