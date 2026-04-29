import asyncio, httpx
from baba_mcp.client import GatewayClient
from baba_mcp.tools.diag import DiagEmptyInput, _active_nodes_impl

def make_client(handler):
    return GatewayClient(base_url="http://gw.test",
        transport=httpx.MockTransport(handler), timeout_ms=2000, max_retries=1)

def test_diag_get_active_nodes():
    def handler(req):
        return httpx.Response(200, json={
            "nodes": [{"publicKey": "NodeB58", "version": "5.x"}],
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_active_nodes_impl(c, DiagEmptyInput()))
    assert out["nodes"][0]["publicKey"] == "NodeB58"
