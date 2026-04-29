import asyncio, httpx, pytest
from baba_mcp.client import GatewayClient
from baba_mcp.errors import McpToolError
from baba_mcp.tools.monitor import _get_balance_impl, MonitorGetBalanceInput


def make_client(handler):
    return GatewayClient(
        base_url="http://gw.test",
        transport=httpx.MockTransport(handler),
        timeout_ms=2000,
        max_retries=1,
    )


def test_get_balance_happy_path():
    seen = {}
    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = req.content
        return httpx.Response(200, json={
            "balance": "1.234", "tokens": [], "delegatedOut": 0, "delegatedIn": 0,
            "success": True, "message": "Tokens not supported",
        })
    c = make_client(handler)
    inp = MonitorGetBalanceInput(public_key="WalletAaa")
    out = asyncio.run(_get_balance_impl(c, inp))
    assert seen["url"] == "http://gw.test/api/Monitor/GetBalance"
    assert b'"PublicKey": "WalletAaa"' in seen["body"]
    assert out["balance"] == "1.234"
    assert out["success"] is True


def test_get_balance_503_propagates():
    def handler(req):
        return httpx.Response(503, json={"success": False})
    c = make_client(handler)
    with pytest.raises(McpToolError) as ei:
        asyncio.run(_get_balance_impl(c, MonitorGetBalanceInput(public_key="x")))
    assert ei.value.code == "node_unavailable"
