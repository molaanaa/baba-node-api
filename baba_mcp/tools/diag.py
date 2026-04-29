"""Diagnostic tools — active nodes / tx count / node info / supply."""
from __future__ import annotations
import json
from typing import Any, Mapping
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base
from baba_mcp.tools._helpers import call_gateway


class DiagEmptyInput(_Base):
    pass


async def _active_nodes_impl(client, inp):
    return await call_gateway(client, "/api/Diag/GetActiveNodes", inp)


async def _active_tx_count_impl(client, inp):
    return await call_gateway(client, "/api/Diag/GetActiveTransactionsCount", inp)


_DISPATCH: dict = {
    "diag_get_active_nodes": (DiagEmptyInput, _active_nodes_impl),
    "diag_get_active_transactions_count": (DiagEmptyInput, _active_tx_count_impl),
}

_TOOL_DEFS = [
    Tool(
        name="diag_get_active_nodes",
        description="List trusted/active nodes seen by the local node. Read-only.",
        inputSchema=DiagEmptyInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
    Tool(
        name="diag_get_active_transactions_count",
        description="Number of unconfirmed transactions currently in the mempool. Read-only.",
        inputSchema=DiagEmptyInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
]


def register(server: Server) -> None:
    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return list(_TOOL_DEFS)

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        client = server.gateway  # type: ignore[attr-defined]
        if name not in _DISPATCH:
            raise ValueError(f"Unknown tool: {name}")
        cls, impl = _DISPATCH[name]
        inp = cls.model_validate(arguments)
        res = await impl(client, inp)
        return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
