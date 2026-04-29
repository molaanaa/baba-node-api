import asyncio, httpx, pytest
from baba_mcp.client import GatewayClient
from baba_mcp.tools.monitor import (
    MonitorGetWalletInfoInput, _get_wallet_info_impl,
)


def make_client(handler):
    return GatewayClient(
        base_url="http://gw.test",
        transport=httpx.MockTransport(handler),
        timeout_ms=2000, max_retries=1,
    )


def test_get_wallet_info_full_response():
    def handler(req):
        assert str(req.url).endswith("/api/Monitor/GetWalletInfo")
        return httpx.Response(200, json={
            "balance": "100.0",
            "lastTransaction": 42,
            "delegated": {"incoming": 0, "outgoing": 0, "donors": [], "recipients": []},
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_get_wallet_info_impl(c, MonitorGetWalletInfoInput(public_key="x")))
    assert out["balance"] == "100.0"
    assert out["lastTransaction"] == 42
