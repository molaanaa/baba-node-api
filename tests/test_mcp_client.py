import pytest, httpx, asyncio
from baba_mcp.client import GatewayClient
from baba_mcp.errors import McpToolError


def make_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    return GatewayClient(
        base_url="http://gw.test",
        transport=transport,
        timeout_ms=5000,
        max_retries=3,
        **kwargs,
    )


def test_post_serializes_json_and_returns_dict():
    seen = {}
    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = req.content
        return httpx.Response(200, json={"balance": "10.0", "success": True})

    c = make_client(handler)
    out = asyncio.run(c.post("/api/Monitor/GetBalance", {"publicKey": "abc"}))
    assert seen["url"] == "http://gw.test/api/Monitor/GetBalance"
    assert b'"publicKey": "abc"' in seen["body"]
    assert out["balance"] == "10.0"


def test_503_retries_then_succeeds():
    calls = {"n": 0}
    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"success": False})
        return httpx.Response(200, json={"success": True})
    c = make_client(handler)
    out = asyncio.run(c.post("/api/x", {}))
    assert out["success"] is True
    assert calls["n"] == 3


def test_503_exhausts_retries_raises_node_unavailable():
    def handler(req):
        return httpx.Response(503, json={"success": False})
    c = make_client(handler)
    with pytest.raises(McpToolError) as ei:
        asyncio.run(c.post("/api/x", {}))
    assert ei.value.code == "node_unavailable"


def test_400_no_retry_raises_invalid_input():
    calls = {"n": 0}
    def handler(req):
        calls["n"] += 1
        return httpx.Response(400, json={"message": "Empty Body"})
    c = make_client(handler)
    with pytest.raises(McpToolError) as ei:
        asyncio.run(c.post("/api/x", {}))
    assert ei.value.code == "invalid_input"
    assert calls["n"] == 1  # niente retry su 400


def test_auth_bearer_header_passed_when_configured():
    seen = {}
    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={})
    c = make_client(handler, auth_token="s3cret")
    asyncio.run(c.post("/api/x", {}))
    assert seen["auth"] == "Bearer s3cret"
