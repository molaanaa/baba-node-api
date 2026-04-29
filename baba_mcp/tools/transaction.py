"""Transaction tools — info / pack / execute / result."""
from __future__ import annotations
import json
from typing import Any, Mapping
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base, TransactionIdInput, TransferIntent
from baba_mcp.tools._helpers import call_gateway


class TransactionGetInfoInput(TransactionIdInput):
    pass


async def _get_info_impl(client, inp):
    return await call_gateway(client, "/api/Transaction/GetTransactionInfo", inp)


_DISPATCH: dict = {
    "transaction_get_info": (TransactionGetInfoInput, _get_info_impl),
}

_TOOL_DEFS = [
    Tool(
        name="transaction_get_info",
        description=(
            "Fetch full info of a single transaction by id (`<poolSeq>.<index1>`). "
            "Returns from/to, sum, fee, status, transactionType, userData, signature. "
            "Read-only."
        ),
        inputSchema=TransactionGetInfoInput.model_json_schema(by_alias=True),
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
