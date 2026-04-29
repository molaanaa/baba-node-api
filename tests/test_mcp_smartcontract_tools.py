import asyncio, httpx, pytest
from baba_mcp.client import GatewayClient
from baba_mcp.tools.smartcontract import SmartContractCompileInput, _compile_impl

def make_client(handler):
    return GatewayClient(base_url="http://gw.test",
        transport=httpx.MockTransport(handler), timeout_ms=10_000, max_retries=1)

def test_smartcontract_compile_returns_bytecode():
    def handler(req):
        return httpx.Response(200, json={
            "byteCodeObjects": [{"name": "BasicCounter",
                "byteCode": "yv66vgAAA..."}],
            "tokenStandard": 0, "success": True, "message": None,
        })
    c = make_client(handler)
    code = "import com.credits.scapi.v0.SmartContract;\n public class C extends SmartContract { ... }"
    inp = SmartContractCompileInput(sourceCode=code)
    out = asyncio.run(_compile_impl(c, inp))
    assert out["byteCodeObjects"][0]["name"] == "BasicCounter"


from baba_mcp.tools.smartcontract import SmartContractPackInput, _pack_impl

def test_smartcontract_pack_deploy_payload():
    def handler(req):
        return httpx.Response(200, json={
            "success": True,
            "dataResponse": {
                "transactionPackagedStr": "ScPack58...",
                "transactionInnerId": 7,
                "deployedAddress": "FwdrHR...",
                "recommendedFee": 0.1,
            },
            "message": None,
        })
    c = make_client(handler)
    inp = SmartContractPackInput(
        public_key="A", source_code="...",
        byte_code_objects=[{"name": "BasicCounter", "byteCode": "AAA="}],
        operation="deploy",
    )
    out = asyncio.run(_pack_impl(c, inp))
    assert out["dataResponse"]["transactionInnerId"] == 7


from baba_mcp.tools.smartcontract import SmartContractDeployInput, _deploy_impl

def test_smartcontract_deploy_with_inner_id_override():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={
            "success": True,
            "transactionId": "174580000.1",
            "deployedAddress": "FwdrHR...",
            "actualFee": "0.1", "message": None,
        })
    c = make_client(handler)
    inp = SmartContractDeployInput(
        public_key="A", source_code="...",
        byte_code_objects=[{"name": "C", "byteCode": "AAA="}],
        transaction_signature="Sig58...",
        transaction_inner_id=7,
    )
    out = asyncio.run(_deploy_impl(c, inp))
    assert out["transactionId"] == "174580000.1"
    assert b'"transactionInnerId": 7' in seen["body"]


from baba_mcp.tools.smartcontract import SmartContractExecuteInput, _execute_impl

def test_smartcontract_execute():
    def handler(req):
        return httpx.Response(200, json={
            "success": True, "transactionId": "174580010.1",
            "actualFee": "0.05", "smartContractResult": None, "message": None,
        })
    c = make_client(handler)
    inp = SmartContractExecuteInput(
        public_key="A", receiver_public_key="ContrB58", method="getCounter",
        params=[], transaction_signature="Sig58...", transaction_inner_id=8,
    )
    out = asyncio.run(_execute_impl(c, inp))
    assert out["success"] is True


from baba_mcp.tools.smartcontract import SmartContractGetInput, _get_impl

def test_smartcontract_get_returns_source_and_bytecode():
    def handler(req):
        return httpx.Response(200, json={
            "address": "FwdrHR...", "deployer": "OwnerB58",
            "sourceCode": "public class C ...",
            "byteCodeObjects": [{"name": "C", "byteCode": "AAA="}],
            "transactionsCount": 4, "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_get_impl(c, SmartContractGetInput(address="FwdrHR...")))
    assert out["transactionsCount"] == 4


from baba_mcp.tools.smartcontract import SmartContractMethodsInput, _methods_impl

def test_smartcontract_methods_by_address():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={
            "methods": [{"name": "getCounter", "args": [], "returnType": "long"}],
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_methods_impl(c, SmartContractMethodsInput(address="FwdrHR...")))
    assert len(out["methods"]) == 1
    assert b'"address": "FwdrHR..."' in seen["body"]

def test_smartcontract_methods_by_bytecode():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"methods": [], "success": True, "message": None})
    c = make_client(handler)
    out = asyncio.run(_methods_impl(c, SmartContractMethodsInput(
        byte_code_objects=[{"name": "C", "byteCode": "AAA="}])))
    assert b'"byteCodeObjects"' in seen["body"]
