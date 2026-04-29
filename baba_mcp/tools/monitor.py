"""Monitor tools — wallet inspection + estimated fee + long-poll waits.

Tools:
  monitor_get_balance, monitor_get_wallet_info,
  monitor_get_transactions_by_wallet, monitor_get_estimated_fee,
  monitor_wait_for_block, monitor_wait_for_smart_transaction
"""
from __future__ import annotations
from typing import Any, Mapping, Optional
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base, PublicKeyInput, PaginatedInput
from baba_mcp.tools._helpers import call_gateway


# ---------- Inputs ----------

class MonitorGetBalanceInput(PublicKeyInput):
    pass


class MonitorGetWalletInfoInput(PublicKeyInput):
    pass


class MonitorGetTransactionsByWalletInput(PaginatedInput):
    pass


# ---------- Implementations (testabili in isolamento) ----------

async def _get_balance_impl(client, inp: MonitorGetBalanceInput) -> Mapping[str, Any]:
    return await call_gateway(client, "/api/Monitor/GetBalance", inp)


async def _get_wallet_info_impl(client, inp: MonitorGetWalletInfoInput) -> Mapping[str, Any]:
    return await call_gateway(client, "/api/Monitor/GetWalletInfo", inp)


async def _get_transactions_by_wallet_impl(client, inp: MonitorGetTransactionsByWalletInput) -> Mapping[str, Any]:
    return await call_gateway(client, "/api/Monitor/GetTransactionsByWallet", inp)


# ---------- Registration ----------

def register(server: Server) -> None:
    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name="monitor_get_balance",
                description=(
                    "Read the CS balance + delegation totals of a Credits wallet. "
                    "Read-only. Input: { PublicKey: <base58> }."
                ),
                inputSchema=MonitorGetBalanceInput.model_json_schema(by_alias=True),
                annotations={"readOnlyHint": True},
            ),
            Tool(
                name="monitor_get_wallet_info",
                description=(
                    "Read full wallet data: balance + lastTransactionId + delegations "
                    "(incoming/outgoing totals + donors/recipients lists). Read-only."
                ),
                inputSchema=MonitorGetWalletInfoInput.model_json_schema(by_alias=True),
                annotations={"readOnlyHint": True},
            ),
            Tool(
                name="monitor_get_transactions_by_wallet",
                description=(
                    "Paginated transaction history for a wallet. Returns id, sum, fee, "
                    "from/to, time, status, currency. Default page size 10, max 500. Read-only."
                ),
                inputSchema=MonitorGetTransactionsByWalletInput.model_json_schema(by_alias=True),
                annotations={"readOnlyHint": True},
            ),
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        client = server.gateway  # type: ignore[attr-defined]
        if name == "monitor_get_balance":
            inp = MonitorGetBalanceInput.model_validate(arguments)
            res = await _get_balance_impl(client, inp)
            import json
            return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
        if name == "monitor_get_wallet_info":
            inp = MonitorGetWalletInfoInput.model_validate(arguments)
            res = await _get_wallet_info_impl(client, inp)
            import json
            return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
        if name == "monitor_get_transactions_by_wallet":
            inp = MonitorGetTransactionsByWalletInput.model_validate(arguments)
            res = await _get_transactions_by_wallet_impl(client, inp)
            import json
            return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
        raise ValueError(f"Unknown tool: {name}")
