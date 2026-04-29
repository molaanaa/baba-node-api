"""Tokens tools — balances/transfers/info/holders/transactions."""
from __future__ import annotations
import json
from typing import Any, Mapping, Optional
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base, TokenAddressInput, PaginatedInput
from baba_mcp.tools._helpers import call_gateway


class TokensInfoInput(TokenAddressInput):
    pass

async def _info_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/Info", inp)


class TokensBalancesGetInput(PaginatedInput):
    pass

async def _balances_get_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/BalancesGet", inp)


class TokensTransfersGetInput(_Base):
    token: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=500)

async def _transfers_get_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/TransfersGet", inp)


class TokensHoldersGetInput(_Base):
    token: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=500)
    order: int = Field(default=0, description="0=balance, 1=transfersCount")
    desc: bool = Field(default=True)

async def _holders_get_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/HoldersGet", inp)


class TokensTransactionsGetInput(_Base):
    token: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=500)

async def _transactions_get_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/TransactionsGet", inp)


_DISPATCH: dict = {
    "tokens_info": (TokensInfoInput, _info_impl),
    "tokens_balances_get": (TokensBalancesGetInput, _balances_get_impl),
    "tokens_transfers_get": (TokensTransfersGetInput, _transfers_get_impl),
    "tokens_holders_get": (TokensHoldersGetInput, _holders_get_impl),
    "tokens_transactions_get": (TokensTransactionsGetInput, _transactions_get_impl),
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
    Tool(
        name="tokens_balances_get",
        description="List token balances for a wallet (paginated). Read-only.",
        inputSchema=TokensBalancesGetInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
    Tool(
        name="tokens_transfers_get",
        description="List recent transfers of a specific token. Paginated. Read-only.",
        inputSchema=TokensTransfersGetInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
    Tool(
        name="tokens_holders_get",
        description="List token holders sorted by balance (default) or transfersCount. Paginated. Read-only.",
        inputSchema=TokensHoldersGetInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
    Tool(
        name="tokens_transactions_get",
        description="List on-chain transactions interacting with a specific token contract. Paginated. Read-only.",
        inputSchema=TokensTransactionsGetInput.model_json_schema(by_alias=True),
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
