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
    from starlette.routing import Route, Mount

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as (r, w):
            await server.run(r, w, server.create_initialization_options())

    inner_app = Starlette(routes=[
        Route("/sse", handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ])

    # Pure-ASGI middleware: BaseHTTPMiddleware breaks SSE streams
    # ("TypeError: 'NoneType' object is not callable" when it tries to wrap
    # the response of a transport that bypasses the middleware's send).
    #
    # Bearer is enforced ONLY on GET /sse (session establishment). The
    # POST /messages/?session_id=... calls are authorised by the
    # unguessable session_id minted by SseServerTransport after a
    # successful handshake — that's the capability, not the bearer. The
    # mobile / Anthropic-backed client sends the bearer on /sse only;
    # gating /messages/ produces 401, which the upstream client surfaces
    # as a content-length:0 403.
    #
    # On /sse we also inject X-Accel-Buffering / Cache-Control / Connection
    # headers so reverse proxies (Nginx, Cloudflare Tunnel, Envoy) don't
    # buffer the first event: frame.
    async def _send_text(send, status, text):
        body = text.encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    class AuthAndSseHeadersASGI:
        def __init__(self, app, token, whitelist):
            self.app = app
            self.token = token
            self.whitelist = whitelist

        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http":
                await self.app(scope, receive, send)
                return
            path = scope.get("path", "")
            if self.whitelist and "0.0.0.0/0" not in self.whitelist:
                client = scope.get("client") or ("unknown", 0)
                if client[0] not in self.whitelist:
                    await _send_text(send, 403,
                        f"403 Forbidden: client {client[0]} not in MCP_WHITELIST_IPS")
                    return
            if self.token and path == "/sse":
                hdrs = dict(scope.get("headers") or [])
                got = hdrs.get(b"authorization", b"").decode("latin-1", "replace")
                if got != f"Bearer {self.token}":
                    await _send_text(send, 401,
                        "401 Unauthorized: missing or invalid Bearer token")
                    return

            if path == "/sse":
                async def send_with_sse_headers(message):
                    if message["type"] == "http.response.start":
                        extra = [
                            (b"x-accel-buffering", b"no"),
                            (b"cache-control", b"no-cache"),
                            (b"connection", b"keep-alive"),
                        ]
                        message = dict(message)
                        message["headers"] = list(message.get("headers") or []) + extra
                    await send(message)
                await self.app(scope, receive, send_with_sse_headers)
            else:
                await self.app(scope, receive, send)

    app = AuthAndSseHeadersASGI(inner_app, auth_token, whitelist_ips)
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
