"""Tokens tools — balances/transfers/info/holders/transactions."""
from __future__ import annotations
import json
from typing import Any, Mapping, Optional
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base, TokenAddressInput
from baba_mcp.tools._helpers import call_gateway


class TokensInfoInput(TokenAddressInput):
    pass

async def _info_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/Info", inp)


_DISPATCH: dict = {
    "tokens_info": (TokensInfoInput, _info_impl),
}

_TOOL_DEFS = [
    Tool(
        name="tokens_info",
        description=(
            "Read metadata of a Credits token (name/code/decimals/totalSupply/owner). "
            "Read-only."
        ),
        inputSchema=TokensInfoInput.model_json_schema(by_alias=True),
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
