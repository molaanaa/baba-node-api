import asyncio, httpx, pytest
from baba_mcp.client import GatewayClient
from baba_mcp.tools.monitor import (
    MonitorGetWalletInfoInput, _get_wallet_info_impl,
)
from baba_mcp.tools.monitor import (
    MonitorGetTransactionsByWalletInput, _get_transactions_by_wallet_impl,
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


def test_get_transactions_by_wallet_passes_pagination():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"message": None, "success": True, "transactions": []})
    c = make_client(handler)
    inp = MonitorGetTransactionsByWalletInput(public_key="x", offset=10, limit=20)
    out = asyncio.run(_get_transactions_by_wallet_impl(c, inp))
    assert b'"offset": 10' in seen["body"]
    assert b'"limit": 20' in seen["body"]
    assert out["success"] is True


from baba_mcp.tools.monitor import MonitorGetEstimatedFeeInput, _get_estimated_fee_impl

def test_get_estimated_fee():
    def handler(req):
        return httpx.Response(200, json={"fee": 0.00874, "success": True, "message": ""})
    c = make_client(handler)
    out = asyncio.run(_get_estimated_fee_impl(c, MonitorGetEstimatedFeeInput(transactionSize=9)))
    assert out["fee"] == 0.00874


from baba_mcp.tools.monitor import MonitorWaitForBlockInput, _wait_for_block_impl

def test_wait_for_block_returns_hash_and_changed_flag():
    def handler(req):
        return httpx.Response(200, json={
            "blockHash": "PoolHashB58...",
            "changed": True,
            "success": True,
        })
    c = make_client(handler)
    out = asyncio.run(_wait_for_block_impl(c, MonitorWaitForBlockInput(timeoutMs=30000)))
    assert out["changed"] is True
    assert "blockHash" in out
