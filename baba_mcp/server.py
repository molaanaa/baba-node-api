"""Entrypoint del server MCP baba-credits.

Avvio:
  python -m baba_mcp.server                 # stdio (default)
  MCP_TRANSPORT=http python -m baba_mcp.server  # HTTP+SSE
"""
from __future__ import annotations
import os
import sys
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server

from baba_mcp.client import GatewayClient


@dataclass
class Config:
    gateway_url: str
    transport: str            # "stdio" | "http"
    http_host: str
    http_port: int
    timeout_ms: int
    auth_token: Optional[str]
    default_currency: int
    log_level: str
    whitelist_ips: list[str]
    max_concurrent: int


def load_config() -> Config:
    return Config(
        gateway_url=os.getenv("BABA_GATEWAY_URL", "http://127.0.0.1:5000"),
        transport=os.getenv("MCP_TRANSPORT", "stdio"),
        http_host=os.getenv("MCP_HTTP_HOST", "127.0.0.1"),
        http_port=int(os.getenv("MCP_HTTP_PORT", "7000")),
        timeout_ms=int(os.getenv("MCP_REQUEST_TIMEOUT_MS", "120000")),
        auth_token=os.getenv("MCP_AUTH_TOKEN") or None,
        default_currency=int(os.getenv("MCP_DEFAULT_CURRENCY", "1")),
        log_level=os.getenv("MCP_LOG_LEVEL", "info"),
        whitelist_ips=[ip.strip() for ip in os.getenv("MCP_WHITELIST_IPS", "127.0.0.1").split(",") if ip.strip()],
        max_concurrent=int(os.getenv("MCP_MAX_CONCURRENT_CALLS", "10")),
    )


def build_server(cfg: Config, register_tools: bool = True) -> Server:
    server = Server("baba-credits")
    server.gateway = GatewayClient(  # type: ignore[attr-defined]
        base_url=cfg.gateway_url,
        timeout_ms=cfg.timeout_ms,
        auth_token=cfg.auth_token,
    )
    server.cfg = cfg  # type: ignore[attr-defined]

    if register_tools:
        from baba_mcp.tools import monitor, transaction, tokens, smartcontract, userfields, diag
        for mod in (monitor, transaction, tokens, smartcontract, userfields, diag):
            mod.register(server)

    return server


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _run_stdio(server: Server) -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


async def _run_http(server: Server, host: str, port: int) -> None:
    from mcp.server.sse import SseServerTransport
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as (r, w):
            await server.run(r, w, server.create_initialization_options())

    app = Starlette(routes=[
        Route("/sse", handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ])
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    await uvicorn.Server(config).serve()


def main() -> None:
    cfg = load_config()
    _setup_logging(cfg.log_level)
    server = build_server(cfg)

    if cfg.transport == "stdio":
        asyncio.run(_run_stdio(server))
    elif cfg.transport == "http":
        if cfg.http_host != "127.0.0.1" and not cfg.auth_token:
            logging.warning(
                "MCP exposed on %s without MCP_AUTH_TOKEN — strongly recommended for production",
                cfg.http_host,
            )
        asyncio.run(_run_http(server, cfg.http_host, cfg.http_port))
    else:
        raise SystemExit(f"Unknown MCP_TRANSPORT={cfg.transport!r}")


if __name__ == "__main__":
    main()
