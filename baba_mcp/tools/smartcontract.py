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


class SmartContractPackInput(_Base):
    public_key: str = Field(alias="PublicKey")
    operation: str = Field(description='"deploy" or "execute"')
    receiver_public_key: Optional[str] = Field(alias="ReceiverPublicKey", default=None,
        description="Required for execute (target contract address)")
    source_code: Optional[str] = Field(alias="sourceCode", default=None,
        description="Required for deploy")
    byte_code_objects: Optional[List[dict]] = Field(alias="byteCodeObjects", default=None,
        description="Required for deploy: [{name, byteCode(base64)}, ...]")
    method: Optional[str] = Field(default=None, description="Required for execute")
    params: Optional[List[dict]] = Field(default=None,
        description="Variant list for execute method args")
    fee_as_string: str = Field(alias="feeAsString", default="0")
    user_data: str = Field(alias="UserData", default="")

async def _pack_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Pack", inp)


class SmartContractDeployInput(_Base):
    public_key: str = Field(alias="PublicKey")
    source_code: str = Field(alias="sourceCode")
    byte_code_objects: List[dict] = Field(alias="byteCodeObjects")
    transaction_signature: str = Field(alias="TransactionSignature")
    transaction_inner_id: int = Field(alias="transactionInnerId", ge=1,
        description="Must be the same value returned by smartcontract_pack")
    fee_as_string: str = Field(alias="feeAsString", default="0")
    user_data: str = Field(alias="UserData", default="")

async def _deploy_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Deploy", inp)


_DISPATCH: dict = {
    "smartcontract_compile": (SmartContractCompileInput, _compile_impl),
    "smartcontract_pack": (SmartContractPackInput, _pack_impl),
    "smartcontract_deploy": (SmartContractDeployInput, _deploy_impl),
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
    Tool(
        name="smartcontract_pack",
        description=(
            "Build the canonical signing payload for a smart-contract Deploy or "
            "Execute. operation='deploy' requires sourceCode + byteCodeObjects; "
            "operation='execute' requires ReceiverPublicKey (contract addr) + method "
            "+ params (Variant list). The response includes transactionInnerId — you "
            "MUST pass it back unchanged to smartcontract_deploy/execute, otherwise "
            "the rebuilt inner_id may differ and the signature will be rejected. "
            "For deploy, also returns deployedAddress (deterministic). No on-chain "
            "side-effect."
        ),
        inputSchema=SmartContractPackInput.model_json_schema(by_alias=True),
        annotations={"idempotentHint": True},
    ),
    Tool(
        name="smartcontract_deploy",
        description=(
            "Deploy a Java smart contract on Credits. Requires the byteCodeObjects "
            "from smartcontract_compile and the signed payload from smartcontract_pack "
            "(operation='deploy'). transactionInnerId MUST equal the value returned by "
            "smartcontract_pack. Writes to the blockchain — fee ~0.1 CS."
        ),
        inputSchema=SmartContractDeployInput.model_json_schema(by_alias=True),
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
