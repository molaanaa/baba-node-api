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
