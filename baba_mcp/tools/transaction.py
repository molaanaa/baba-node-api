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


class TransactionPackInput(TransferIntent):
    pass


async def _pack_impl(client, inp):
    return await call_gateway(client, "/api/Transaction/Pack", inp)


class TransactionExecuteInput(TransferIntent):
    transaction_signature: str = Field(alias="TransactionSignature", min_length=1)


async def _execute_impl(client, inp):
    return await call_gateway(client, "/api/Transaction/Execute", inp)


_DISPATCH: dict = {
    "transaction_get_info": (TransactionGetInfoInput, _get_info_impl),
    "transaction_pack": (TransactionPackInput, _pack_impl),
    "transaction_execute": (TransactionExecuteInput, _execute_impl),
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
    Tool(
        name="transaction_pack",
        description=(
            "Build the canonical signing payload for a CS transfer. "
            "Returns base58 `transactionPackagedStr` ready to be signed client-side "
            "(ed25519). The payload encodes inner_id, source, target, amount, fee, "
            "currency, userFields. Pass feeAsString=\"0\" to use the recommendedFee. "
            "No on-chain side-effect."
        ),
        inputSchema=TransactionPackInput.model_json_schema(by_alias=True),
        annotations={"idempotentHint": True},
    ),
    Tool(
        name="transaction_execute",
        description=(
            "Submit a signed CS transfer to the Credits node. Requires "
            "TransactionSignature (base58 ed25519 signature of the packagedStr "
            "produced by transaction_pack). The same PublicKey/ReceiverPublicKey/"
            "amountAsString/feeAsString/UserData passed to transaction_pack must be "
            "passed here unchanged, otherwise the inner_id rebuilt server-side will "
            "not match and the node will reject with 'Transaction has wrong "
            "signature.'. Writes to the blockchain — costs fee."
        ),
        inputSchema=TransactionExecuteInput.model_json_schema(by_alias=True),
        annotations={"destructiveHint": True},
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
