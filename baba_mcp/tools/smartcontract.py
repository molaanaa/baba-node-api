"""SmartContract tools — compile/pack/deploy/execute/get/methods/state/list."""
from __future__ import annotations
import json
from typing import Any, List, Mapping, Optional
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base
from baba_mcp.tools._helpers import call_gateway


class SmartContractCompileInput(_Base):
    source_code: str = Field(alias="sourceCode", min_length=1)


async def _compile_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Compile", inp)


_DISPATCH: dict = {
    "smartcontract_compile": (SmartContractCompileInput, _compile_impl),
}

_TOOL_DEFS = [
    Tool(
        name="smartcontract_compile",
        description=(
            "Compile Java source for a Credits smart contract. The sourceCode "
            "MUST contain `import com.credits.scapi.v0.SmartContract;` "
            "explicitly — the executor fails silently otherwise. Compile may "
            "take up to ~120s under load. Returns byteCodeObjects (base64) ready "
            "to be passed to smartcontract_pack/deploy. Read-only (no on-chain "
            "side-effect)."
        ),
        inputSchema=SmartContractCompileInput.model_json_schema(by_alias=True),
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
