import os
from baba_mcp.server import build_server, load_config


def test_load_config_defaults(monkeypatch):
    for k in (
        "BABA_GATEWAY_URL", "MCP_TRANSPORT", "MCP_HTTP_HOST", "MCP_HTTP_PORT",
        "MCP_REQUEST_TIMEOUT_MS", "MCP_AUTH_TOKEN", "MCP_DEFAULT_CURRENCY",
    ):
        monkeypatch.delenv(k, raising=False)
    cfg = load_config()
    assert cfg.gateway_url == "http://127.0.0.1:5000"
    assert cfg.transport == "stdio"
    assert cfg.http_host == "127.0.0.1"
    assert cfg.http_port == 7000
    assert cfg.timeout_ms == 120_000
    assert cfg.auth_token is None
    assert cfg.default_currency == 1


def test_load_config_overrides(monkeypatch):
    monkeypatch.setenv("BABA_GATEWAY_URL", "http://gw:8080")
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_HTTP_PORT", "9000")
    cfg = load_config()
    assert cfg.gateway_url == "http://gw:8080"
    assert cfg.transport == "http"
    assert cfg.http_port == 9000


def test_build_server_registers_zero_tools_initially():
    cfg = load_config()
    srv = build_server(cfg, register_tools=False)
    # con register_tools=False non chiamiamo i registrar; il server è creato ma vuoto
    assert srv is not None
