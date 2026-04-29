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

from baba_mcp.tools.transaction import TransactionPackInput, _pack_impl

def test_pack_returns_packaged_str():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={
            "success": True,
            "dataResponse": {
                "transactionPackagedStr": "Pack58...", "recommendedFee": 0.00874,
                "actualSum": 0, "publicKey": None, "smartContractResult": None,
            },
            "actualFee": 0, "actualSum": 0, "amount": 0, "blockId": 0,
            "extraFee": None, "flowResult": None, "listItem": [],
            "listTransactionInfo": None, "message": None,
            "transactionId": None, "transactionInfo": None, "transactionInnerId": None,
        })
    c = make_client(handler)
    inp = TransactionPackInput(
        public_key="A", receiver_public_key="B",
        amount_as_string="0.001", fee_as_string="0",
    )
    out = asyncio.run(_pack_impl(c, inp))
    assert out["dataResponse"]["transactionPackagedStr"] == "Pack58..."
    assert b'"PublicKey": "A"' in seen["body"]
    assert b'"ReceiverPublicKey": "B"' in seen["body"]

from baba_mcp.tools.transaction import TransactionExecuteInput, _execute_impl

def test_execute_requires_signature():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        TransactionExecuteInput(public_key="A", receiver_public_key="B")  # no sig

def test_execute_happy_path():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={
            "amount": "0.001", "dataResponse": {"actualSum": 0, "publicKey": None,
                "recommendedFee": 0.00874, "smartContractResult": None,
                "transactionPackagedStr": None},
            "actualSum": "0.001", "actualFee": "0.00874", "extraFee": None,
            "flowResult": None, "listItem": [], "listTransactionInfo": None,
            "message": None, "messageError": None, "success": True,
            "transactionId": "174575023.1", "transactionInfo": None,
            "transactionInnerId": 13, "blockId": 0,
        })
    c = make_client(handler)
    inp = TransactionExecuteInput(
        public_key="A", receiver_public_key="B",
        amount_as_string="0.001", fee_as_string="0",
        transaction_signature="Sig58...",
    )
    out = asyncio.run(_execute_impl(c, inp))
    assert out["success"] is True
    assert out["transactionId"] == "174575023.1"
    assert b'"TransactionSignature": "Sig58..."' in seen["body"]
