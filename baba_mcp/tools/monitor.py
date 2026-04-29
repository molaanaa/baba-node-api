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


class MonitorGetEstimatedFeeInput(_Base):
    transaction_size: int = Field(alias="transactionSize", ge=0)


class MonitorWaitForBlockInput(_Base):
    timeout_ms: int = Field(alias="timeoutMs", ge=0, le=60000, default=30000)
    pool_hash: Optional[str] = Field(
        alias="poolHash", default=None,
        description="Optional base58 hash of last seen block (long-poll cursor)",
    )


class MonitorWaitForSmartTransactionInput(_Base):
    address: str
    timeout_ms: int = Field(alias="timeoutMs", ge=0, le=60000, default=30000)


# ---------- Implementations (testabili in isolamento) ----------

async def _get_balance_impl(client, inp: MonitorGetBalanceInput) -> Mapping[str, Any]:
    return await call_gateway(client, "/api/Monitor/GetBalance", inp)


async def _get_wallet_info_impl(client, inp: MonitorGetWalletInfoInput) -> Mapping[str, Any]:
    return await call_gateway(client, "/api/Monitor/GetWalletInfo", inp)


async def _get_transactions_by_wallet_impl(client, inp: MonitorGetTransactionsByWalletInput) -> Mapping[str, Any]:
    return await call_gateway(client, "/api/Monitor/GetTransactionsByWallet", inp)


async def _get_estimated_fee_impl(client, inp: MonitorGetEstimatedFeeInput) -> Mapping[str, Any]:
    return await call_gateway(client, "/api/Monitor/GetEstimatedFee", inp)


async def _wait_for_block_impl(client, inp: MonitorWaitForBlockInput) -> Mapping[str, Any]:
    return await call_gateway(client, "/api/Monitor/WaitForBlock", inp)


async def _wait_for_smart_transaction_impl(client, inp: MonitorWaitForSmartTransactionInput) -> Mapping[str, Any]:
    return await call_gateway(client, "/api/Monitor/WaitForSmartTransaction", inp)


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
            Tool(
                name="monitor_get_estimated_fee",
                description="Estimate fee for a transaction of given byte size. Read-only.",
                inputSchema=MonitorGetEstimatedFeeInput.model_json_schema(by_alias=True),
                annotations={"readOnlyHint": True},
            ),
            Tool(
                name="monitor_wait_for_block",
                description=(
                    "Long-poll: blocks until a new pool is sealed on the node, or "
                    "timeoutMs elapses. Returns blockHash + `changed` flag. Read-only."
                ),
                inputSchema=MonitorWaitForBlockInput.model_json_schema(by_alias=True),
                annotations={"readOnlyHint": True},
            ),
            Tool(
                name="monitor_wait_for_smart_transaction",
                description=(
                    "Long-poll: blocks until the next smart-contract transaction "
                    "targeting `address` is sealed. Returns transactionId + found. Read-only."
                ),
                inputSchema=MonitorWaitForSmartTransactionInput.model_json_schema(by_alias=True),
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
        if name == "monitor_get_estimated_fee":
            inp = MonitorGetEstimatedFeeInput.model_validate(arguments)
            res = await _get_estimated_fee_impl(client, inp)
            import json
            return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
        if name == "monitor_wait_for_block":
            inp = MonitorWaitForBlockInput.model_validate(arguments)
            res = await _wait_for_block_impl(client, inp)
            import json
            return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
        if name == "monitor_wait_for_smart_transaction":
            inp = MonitorWaitForSmartTransactionInput.model_validate(arguments)
            res = await _wait_for_smart_transaction_impl(client, inp)
            import json
            return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
        raise ValueError(f"Unknown tool: {name}")
