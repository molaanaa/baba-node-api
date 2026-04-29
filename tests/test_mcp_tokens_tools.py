import asyncio, httpx, pytest
from baba_mcp.client import GatewayClient
from baba_mcp.tools.tokens import TokensInfoInput, _info_impl

def make_client(handler):
    return GatewayClient(base_url="http://gw.test",
        transport=httpx.MockTransport(handler), timeout_ms=2000, max_retries=1)

def test_tokens_info():
    def handler(req):
        return httpx.Response(200, json={
            "name": "TestTok", "code": "TST", "decimals": 18,
            "totalSupply": "1000000", "owner": "OwnerB58",
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_info_impl(c, TokensInfoInput(token="TokB58")))
    assert out["code"] == "TST"


from baba_mcp.tools.tokens import TokensBalancesGetInput, _balances_get_impl

def test_tokens_balances_get_includes_pagination():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={
            "balances": [{"token": "TokB58", "code": "TST", "balance": "10.0"}],
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_balances_get_impl(c, TokensBalancesGetInput(public_key="W", offset=0, limit=50)))
    assert b'"limit": 50' in seen["body"]
    assert out["balances"][0]["code"] == "TST"


from baba_mcp.tools.tokens import TokensTransfersGetInput, _transfers_get_impl

def test_tokens_transfers_get():
    def handler(req):
        return httpx.Response(200, json={"transfers": [], "success": True, "message": None})
    c = make_client(handler)
    inp = TokensTransfersGetInput(token="TokB58", offset=0, limit=10)
    out = asyncio.run(_transfers_get_impl(c, inp))
    assert out["success"] is True
