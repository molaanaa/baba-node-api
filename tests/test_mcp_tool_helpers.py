import asyncio, httpx
from pydantic import BaseModel, ConfigDict, Field
from baba_mcp.client import GatewayClient
from baba_mcp.tools._helpers import call_gateway


class _In(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    public_key: str = Field(alias="PublicKey")


def make_client(handler):
    return GatewayClient(
        base_url="http://gw.test",
        transport=httpx.MockTransport(handler),
        timeout_ms=2000,
        max_retries=1,
    )


def test_call_gateway_serializes_with_aliases():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"ok": True})
    client = make_client(handler)
    inp = _In(public_key="abc")
    out = asyncio.run(call_gateway(client, "/api/X", inp))
    assert out == {"ok": True}
    assert b'"PublicKey": "abc"' in seen["body"]
