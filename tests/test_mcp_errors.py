import pytest
from baba_mcp.errors import map_http_error, McpToolError

def test_400_maps_to_invalid_input():
    err = map_http_error(400, {"message": "Empty Body"})
    assert isinstance(err, McpToolError)
    assert err.code == "invalid_input"
    assert "Empty Body" in err.message

def test_404_maps_to_not_found():
    err = map_http_error(404, {"message": "Transaction not found", "found": False})
    assert err.code == "not_found"

def test_503_maps_to_node_unavailable():
    err = map_http_error(503, {"success": False})
    assert err.code == "node_unavailable"

def test_429_maps_to_rate_limited():
    err = map_http_error(429, {"message": "Too Many Requests"})
    assert err.code == "rate_limited"

def test_500_with_message_error_maps_to_node_error():
    err = map_http_error(500, {"messageError": "Transaction has wrong signature."})
    assert err.code == "node_error"
    assert "wrong signature" in err.message

def test_500_generic_maps_to_internal():
    err = map_http_error(500, {"message": "boom"})
    assert err.code == "internal"

def test_details_carries_original_body():
    body = {"message": "x", "extra": 42}
    err = map_http_error(400, body)
    assert err.details == body
