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
        from mcp.types import Tool, TextContent
        import json as _json

        modules = (monitor, transaction, tokens, smartcontract, userfields, diag)
        merged_dispatch: dict = {}
        merged_tool_defs: list[Tool] = []
        for mod in modules:
            for tool_name, entry in mod._DISPATCH.items():
                if tool_name in merged_dispatch:
                    raise RuntimeError(f"Tool name collision: {tool_name!r}")
                merged_dispatch[tool_name] = entry
            merged_tool_defs.extend(mod._TOOL_DEFS)

        @server.list_tools()
        async def _list_tools() -> list[Tool]:
            return list(merged_tool_defs)

        @server.call_tool()
        async def _call(name: str, arguments: dict) -> list[TextContent]:
            client = server.gateway  # type: ignore[attr-defined]
            if name not in merged_dispatch:
                raise ValueError(f"Unknown tool: {name}")
            cls, impl = merged_dispatch[name]
            inp = cls.model_validate(arguments)
            res = await impl(client, inp)
            return [TextContent(type="text", text=_json.dumps(res, ensure_ascii=False))]

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


async def _run_http(server: Server, host: str, port: int,
                    auth_token: Optional[str] = None,
                    whitelist_ips: Optional[list[str]] = None) -> None:
    from mcp.server.sse import SseServerTransport
    import uvicorn
    from starlette.applications import Starlette
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route, Mount

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as (r, w):
            await server.run(r, w, server.create_initialization_options())

    class AuthMiddleware(BaseHTTPMiddleware):
        """Optional Bearer-token + IP allowlist gate on /sse and /messages/.

        Active only when ``auth_token`` is set or ``whitelist_ips`` is non-default.
        Returns 401 on missing/wrong token, 403 on disallowed IP.
        """
        async def dispatch(self, request, call_next):
            client_ip = (request.client.host if request.client else None) or "unknown"
            if whitelist_ips and "0.0.0.0/0" not in whitelist_ips:
                if client_ip not in whitelist_ips:
                    return PlainTextResponse(
                        f"403 Forbidden: client {client_ip} not in MCP_WHITELIST_IPS",
                        status_code=403,
                    )
            if auth_token:
                header = request.headers.get("authorization", "")
                expected = f"Bearer {auth_token}"
                if header != expected:
                    return PlainTextResponse(
                        "401 Unauthorized: missing or invalid Bearer token",
                        status_code=401,
                    )
            return await call_next(request)

    app = Starlette(routes=[
        Route("/sse", handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ])
    if auth_token or (whitelist_ips and "0.0.0.0/0" not in whitelist_ips):
        app.add_middleware(AuthMiddleware)
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
        asyncio.run(_run_http(server, cfg.http_host, cfg.http_port,
                              auth_token=cfg.auth_token,
                              whitelist_ips=cfg.whitelist_ips))
    else:
        raise SystemExit(f"Unknown MCP_TRANSPORT={cfg.transport!r}")


if __name__ == "__main__":
    main()
