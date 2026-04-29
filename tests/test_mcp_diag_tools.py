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


from baba_mcp.tools.diag import _active_tx_count_impl

def test_diag_active_tx_count():
    def handler(req):
        return httpx.Response(200, json={"count": 17, "success": True, "message": None})
    c = make_client(handler)
    out = asyncio.run(_active_tx_count_impl(c, DiagEmptyInput()))
    assert out["count"] == 17


from baba_mcp.tools.diag import _node_info_impl

def test_diag_node_info():
    def handler(req):
        return httpx.Response(200, json={
            "nodeVersion": "5.x", "uptimeMs": 12345678,
            "blockchainTopHash": "Hash58...", "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_node_info_impl(c, DiagEmptyInput()))
    assert out["nodeVersion"] == "5.x"


from baba_mcp.tools.diag import _supply_impl

def test_diag_supply():
    def handler(req):
        return httpx.Response(200, json={
            "initial": "250000000.0", "mined": "1234567.0",
            "currentSupply": "251234567.0", "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_supply_impl(c, DiagEmptyInput()))
    assert out["currentSupply"].startswith("251")
