"""SmartContract tools — compile/pack/deploy/execute/get/methods/state/list."""
from __future__ import annotations
from typing import Any, List, Mapping, Optional
from pydantic import Field, model_validator
from mcp.types import Tool

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


class SmartContractExecuteInput(_Base):
    public_key: str = Field(alias="PublicKey")
    receiver_public_key: str = Field(alias="ReceiverPublicKey",
        description="Contract address (base58)")
    method: str
    params: List[dict] = Field(default_factory=list,
        description="Variant list of arguments")
    transaction_signature: str = Field(alias="TransactionSignature")
    transaction_inner_id: int = Field(alias="transactionInnerId", ge=1)
    fee_as_string: str = Field(alias="feeAsString", default="0")
    user_data: str = Field(alias="UserData", default="")

async def _execute_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Execute", inp)


class SmartContractGetInput(_Base):
    address: str

async def _get_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Get", inp)


class SmartContractMethodsInput(_Base):
    address: Optional[str] = None
    byte_code_objects: Optional[List[dict]] = Field(alias="byteCodeObjects", default=None)

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.address is None) == (self.byte_code_objects is None):
            raise ValueError("Provide exactly one of: address, byteCodeObjects")
        return self

async def _methods_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Methods", inp)


class SmartContractStateInput(_Base):
    address: str

async def _state_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/State", inp)


class SmartContractListByWalletInput(_Base):
    deployer: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=500)

async def _list_by_wallet_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/ListByWallet", inp)


_DISPATCH: dict = {
    "smartcontract_compile": (SmartContractCompileInput, _compile_impl),
    "smartcontract_pack": (SmartContractPackInput, _pack_impl),
    "smartcontract_deploy": (SmartContractDeployInput, _deploy_impl),
    "smartcontract_execute": (SmartContractExecuteInput, _execute_impl),
    "smartcontract_get": (SmartContractGetInput, _get_impl),
    "smartcontract_methods": (SmartContractMethodsInput, _methods_impl),
    "smartcontract_state": (SmartContractStateInput, _state_impl),
    "smartcontract_list_by_wallet": (SmartContractListByWalletInput, _list_by_wallet_impl),
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
    Tool(
        name="smartcontract_execute",
        description=(
            "Call a method on a deployed Credits smart contract. Requires signed "
            "payload from smartcontract_pack (operation='execute'). transactionInnerId "
            "must equal the pack response. Writes to the blockchain."
        ),
        inputSchema=SmartContractExecuteInput.model_json_schema(by_alias=True),
        annotations={"destructiveHint": True},
    ),
    Tool(
        name="smartcontract_get",
        description="Read deployed smart contract: deployer, sourceCode, byteCodeObjects, transactionsCount. Read-only.",
        inputSchema=SmartContractGetInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
    Tool(
        name="smartcontract_methods",
        description=(
            "List the public methods of a smart contract. Provide either `address` "
            "(deployed contract) or `byteCodeObjects` (pre-deploy inspection). Read-only."
        ),
        inputSchema=SmartContractMethodsInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
    Tool(
        name="smartcontract_state",
        description="Read the current public state (instance fields) of a deployed smart contract. Read-only.",
        inputSchema=SmartContractStateInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
    Tool(
        name="smartcontract_list_by_wallet",
        description="List smart contracts deployed by a wallet (paginated). Read-only.",
        inputSchema=SmartContractListByWalletInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
]
