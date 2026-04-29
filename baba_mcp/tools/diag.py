"""Diagnostic tools — active nodes / tx count / node info / supply."""
from __future__ import annotations
from typing import Any, Mapping
from mcp.types import Tool

from baba_mcp.schemas import _Base
from baba_mcp.tools._helpers import call_gateway


class DiagEmptyInput(_Base):
    pass


async def _active_nodes_impl(client, inp):
    return await call_gateway(client, "/api/Diag/GetActiveNodes", inp)


async def _active_tx_count_impl(client, inp):
    return await call_gateway(client, "/api/Diag/GetActiveTransactionsCount", inp)


async def _node_info_impl(client, inp):
    return await call_gateway(client, "/api/Diag/GetNodeInfo", inp)


async def _supply_impl(client, inp):
    return await call_gateway(client, "/api/Diag/GetSupply", inp)


_DISPATCH: dict = {
    "diag_get_active_nodes": (DiagEmptyInput, _active_nodes_impl),
    "diag_get_active_transactions_count": (DiagEmptyInput, _active_tx_count_impl),
    "diag_get_node_info": (DiagEmptyInput, _node_info_impl),
    "diag_get_supply": (DiagEmptyInput, _supply_impl),
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
    Tool(
        name="diag_get_node_info",
        description="Local Credits node version, uptime, top block hash. Read-only.",
        inputSchema=DiagEmptyInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
    Tool(
        name="diag_get_supply",
        description="Total CS supply on the network: initial + mined + currentSupply. Read-only.",
        inputSchema=DiagEmptyInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
]
