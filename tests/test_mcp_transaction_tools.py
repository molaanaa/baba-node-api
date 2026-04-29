import asyncio, httpx, pytest
from baba_mcp.client import GatewayClient
from baba_mcp.errors import McpToolError
from baba_mcp.tools.transaction import (
    TransactionGetInfoInput, _get_info_impl,
)

def make_client(handler):
    return GatewayClient(
        base_url="http://gw.test",
        transport=httpx.MockTransport(handler),
        timeout_ms=2000, max_retries=1,
    )

def test_get_info_happy_path():
    def handler(req):
        return httpx.Response(200, json={
            "id": "174575023.1", "fromAccount": "A", "toAccount": "B",
            "time": "2026-04-27T12:00:00.000Z", "value": "0.001", "val": 0.001,
            "fee": "0.00874", "currency": "CS", "innerId": 12,
            "index": 0, "status": "Success", "transactionType": 0,
            "transactionTypeDefinition": "TT_Normal",
            "blockNum": "174575023", "found": True,
            "userData": "", "signature": "Sig58...", "extraFee": [],
            "bundle": None, "success": True, "message": None,
        })
    c = make_client(handler)
    inp = TransactionGetInfoInput(transactionId="174575023.1")
    out = asyncio.run(_get_info_impl(c, inp))
    assert out["found"] is True
    assert out["transactionTypeDefinition"] == "TT_Normal"

def test_get_info_invalid_id_raises_invalid_input():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        TransactionGetInfoInput(transactionId="not-a-tx-id")
