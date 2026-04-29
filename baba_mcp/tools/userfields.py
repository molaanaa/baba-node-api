"""UserFields v1 codec tools."""
from __future__ import annotations
import json
from typing import Any, Mapping, Optional
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base
from baba_mcp.tools._helpers import call_gateway


class UserFieldsEncodeInput(_Base):
    content_hash_algo: str = Field(alias="contentHashAlgo", default="sha-256")
    content_hash: str = Field(alias="contentHash", min_length=1)
    content_cid: Optional[str] = Field(alias="contentCid", default=None)
    mime: Optional[str] = None
    size_bytes: Optional[int] = Field(alias="sizeBytes", default=None, ge=0)


async def _encode_impl(client, inp):
    return await call_gateway(client, "/api/UserFields/Encode", inp)


class UserFieldsDecodeInput(_Base):
    user_data: str = Field(alias="userData", min_length=1)


async def _decode_impl(client, inp):
    return await call_gateway(client, "/api/UserFields/Decode", inp)


_DISPATCH: dict = {
    "userfields_encode": (UserFieldsEncodeInput, _encode_impl),
    "userfields_decode": (UserFieldsDecodeInput, _decode_impl),
}

_TOOL_DEFS = [
    Tool(
        name="userfields_encode",
        description=(
            "Encode userFields v1 payload (hash + CID + mime + sizeBytes) into a "
            "base58 blob ready to be passed as `UserData` to transaction_pack. "
            "Pure function: no on-chain side-effect."
        ),
        inputSchema=UserFieldsEncodeInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True, "idempotentHint": True},
    ),
    Tool(
        name="userfields_decode",
        description=(
            "Decode a userFields v1 base58 blob (as stored in a tx's UserData) into "
            "structured fields. Pure function. Read-only."
        ),
        inputSchema=UserFieldsDecodeInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True, "idempotentHint": True},
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
