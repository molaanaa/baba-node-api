# baba-credits MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Espongo il gateway HTTP `baba-node-api` come server MCP `baba-credits` (29 tools 1:1 con gli endpoint REST) e versiono nel repo una skill che documenta tutte le operazioni blockchain Credits per agenti AI.

**Architecture:** Thin Python wrapper non-custodial (package `baba_mcp/`) che traduce ogni chiamata MCP in `POST` HTTP al gateway Flask. Due processi disaccoppiati (gateway + MCP) gestiti da pm2 ecosystem. Skill versionata in `.claude/skills/baba-credits/`.

**Tech Stack:** Python 3.8+, `mcp>=1.0.0`, `httpx>=0.27.0` (async HTTP client), `pydantic>=2.5.0` (I/O validation), `pytest` (TDD), `pm2` (process bundle).

**Spec:** `docs/superpowers/specs/2026-04-29-baba-credits-mcp-design.md`.

---

## Phase 1 — Foundations

### Task 1: Package skeleton + nuove dipendenze

**Files:**
- Create: `baba_mcp/__init__.py`
- Create: `baba_mcp/tools/__init__.py`
- Modify: `requirements.txt`
- Create: `requirements-dev.txt` (se manca, append; il branch già ne ha uno)

- [ ] **Step 1: Crea le directory e gli `__init__.py`**

```bash
mkdir -p baba_mcp/tools
printf '"""baba-credits MCP server package."""\n__version__ = "0.1.0"\n' > baba_mcp/__init__.py
printf '"""Tool registration modules, one per category."""\n' > baba_mcp/tools/__init__.py
```

- [ ] **Step 2: Aggiungi le dipendenze a `requirements.txt`**

Append (append, non sostituire):

```text
mcp>=1.0.0
httpx>=0.27.0
pydantic>=2.5.0
```

- [ ] **Step 3: Verifica che il package sia importabile**

Run:
```bash
python3 -c "import baba_mcp; print(baba_mcp.__version__)"
```
Expected: `0.1.0`

- [ ] **Step 4: Commit**

```bash
git add baba_mcp/ requirements.txt
git commit -m "feat(mcp): add baba_mcp package skeleton + new deps"
```

---

### Task 2: Modello errori (`baba_mcp/errors.py`)

**Files:**
- Create: `baba_mcp/errors.py`
- Test: `tests/test_mcp_errors.py`

- [ ] **Step 1: Scrivi i test failing**

`tests/test_mcp_errors.py`:

```python
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
```

- [ ] **Step 2: Run test to verify they fail**

Run:
```bash
pytest tests/test_mcp_errors.py -v
```
Expected: 7 FAILED with `ModuleNotFoundError: No module named 'baba_mcp.errors'`

- [ ] **Step 3: Implementa `baba_mcp/errors.py`**

```python
"""Mapping fra errori HTTP del gateway e codici di errore MCP strutturati.

Codici esposti agli agenti:
  invalid_input   - 400: schema sbagliato; non ritentare con stesso input
  not_found       - 404: risorsa inesistente; smetti di cercare
  node_unavailable- 503: nodo Credits offline; retry con backoff
  rate_limited    - 429: gateway rate limit superato
  node_error      - 500 con `messageError` dal nodo Credits (es. wrong signature)
  internal        - altri 5xx: errore inatteso del gateway
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass
class McpToolError(Exception):
    code: str
    message: str
    details: Mapping[str, Any]

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def map_http_error(status: int, body: Mapping[str, Any]) -> McpToolError:
    msg = body.get("messageError") or body.get("message") or f"HTTP {status}"
    if status == 400:
        return McpToolError("invalid_input", msg, body)
    if status == 404:
        return McpToolError("not_found", msg, body)
    if status == 429:
        return McpToolError("rate_limited", msg, body)
    if status == 503:
        return McpToolError("node_unavailable", msg, body)
    if status == 500 and body.get("messageError"):
        return McpToolError("node_error", msg, body)
    return McpToolError("internal", msg, body)
```

- [ ] **Step 4: Run tests**

Run:
```bash
pytest tests/test_mcp_errors.py -v
```
Expected: 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add baba_mcp/errors.py tests/test_mcp_errors.py
git commit -m "feat(mcp): error mapping HTTP -> MCP tool error codes"
```

---

### Task 3: HTTP client async (`baba_mcp/client.py`)

**Files:**
- Create: `baba_mcp/client.py`
- Test: `tests/test_mcp_client.py`

- [ ] **Step 1: Scrivi i test failing (httpx.MockTransport)**

`tests/test_mcp_client.py`:

```python
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
```

- [ ] **Step 2: Run tests, verify fail**

Run:
```bash
pytest tests/test_mcp_client.py -v
```
Expected: FAIL `ModuleNotFoundError: No module named 'baba_mcp.client'`

- [ ] **Step 3: Implementa `baba_mcp/client.py`**

```python
"""Async HTTP client verso il gateway baba-node-api.

- POST JSON con header opzionale `Authorization: Bearer <MCP_AUTH_TOKEN>`.
- Retry esponenziale (1s/2s/4s) solo su 503 e timeout.
- Tutti gli altri errori HTTP sono tradotti in McpToolError tramite
  baba_mcp.errors.map_http_error.
"""
from __future__ import annotations
import asyncio
import httpx
from typing import Any, Mapping, Optional

from baba_mcp.errors import map_http_error, McpToolError


class GatewayClient:
    def __init__(
        self,
        base_url: str,
        timeout_ms: int = 120_000,
        max_retries: int = 3,
        auth_token: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_ms / 1000.0
        self._max_retries = max_retries
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_s,
            headers=headers,
            transport=transport,
        )

    async def post(self, path: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        last_err: Optional[McpToolError] = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.post(path, json=dict(body))
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_err = McpToolError(
                    "node_unavailable", f"transport: {e}", {"attempt": attempt + 1}
                )
                await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code == 503:
                try:
                    body_json = resp.json()
                except Exception:
                    body_json = {"success": False}
                last_err = map_http_error(503, body_json)
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise last_err

            if 200 <= resp.status_code < 300:
                return resp.json()

            try:
                body_json = resp.json()
            except Exception:
                body_json = {"message": resp.text or f"HTTP {resp.status_code}"}
            raise map_http_error(resp.status_code, body_json)

        assert last_err is not None
        raise last_err

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Run tests, verify pass**

Run:
```bash
pytest tests/test_mcp_client.py -v
```
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add baba_mcp/client.py tests/test_mcp_client.py
git commit -m "feat(mcp): async HTTP client with retry + auth + error mapping"
```

---

### Task 4: Schemas Pydantic riutilizzabili (`baba_mcp/schemas.py`)

**Files:**
- Create: `baba_mcp/schemas.py`
- Test: `tests/test_mcp_schemas.py`

- [ ] **Step 1: Scrivi test failing**

`tests/test_mcp_schemas.py`:

```python
import pytest
from pydantic import ValidationError
from baba_mcp.schemas import PublicKeyInput, PaginatedInput


def test_public_key_required():
    with pytest.raises(ValidationError):
        PublicKeyInput()

def test_public_key_accepts_alias():
    m = PublicKeyInput.model_validate({"PublicKey": "abc"})
    assert m.public_key == "abc"

def test_paginated_defaults():
    m = PaginatedInput.model_validate({"PublicKey": "abc"})
    assert m.offset == 0
    assert m.limit == 10
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_mcp_schemas.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implementa `baba_mcp/schemas.py`**

```python
"""Pydantic models riusabili per i payload MCP <-> gateway.

Il gateway accetta sia camelCase (`publicKey`) sia PascalCase (`PublicKey`).
Manteniamo lo stesso comportamento con `populate_by_name` + alias.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class PublicKeyInput(_Base):
    public_key: str = Field(alias="PublicKey", description="Base58-encoded wallet public key")


class PaginatedInput(PublicKeyInput):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=500)


class TokenAddressInput(_Base):
    token: str = Field(description="Base58-encoded token contract address")


class TransactionIdInput(_Base):
    transaction_id: str = Field(
        alias="transactionId",
        pattern=r"^\d+\.\d+$",
        description="Format: <poolSeq>.<index1>",
    )


class TransferIntent(_Base):
    """Campi comuni a Transaction/Pack e Transaction/Execute."""
    public_key: str = Field(alias="PublicKey")
    receiver_public_key: str = Field(alias="ReceiverPublicKey")
    amount_as_string: str = Field(alias="amountAsString", default="0")
    fee_as_string: str = Field(alias="feeAsString", default="0")
    user_data: str = Field(alias="UserData", default="")
    delegate_enable: Optional[bool] = Field(alias="DelegateEnable", default=False)
    delegate_disable: Optional[bool] = Field(alias="DelegateDisable", default=False)
    date_expired_utc: Optional[str] = Field(alias="DateExpiredUtc", default="")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp_schemas.py -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add baba_mcp/schemas.py tests/test_mcp_schemas.py
git commit -m "feat(mcp): shared Pydantic input models"
```

---

### Task 5: Server skeleton (`baba_mcp/server.py`)

Il server è invocabile con `python -m baba_mcp.server`. Modalità default `stdio`. Modalità `http` esposta solo se `MCP_TRANSPORT=http`.

**Files:**
- Create: `baba_mcp/server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Scrivi test failing**

`tests/test_mcp_server.py`:

```python
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
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_mcp_server.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implementa `baba_mcp/server.py`**

```python
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp_server.py -v
```
Expected: 3 PASSED. (`build_server(register_tools=False)` evita di importare i moduli tools che ancora non esistono.)

- [ ] **Step 5: Commit**

```bash
git add baba_mcp/server.py tests/test_mcp_server.py
git commit -m "feat(mcp): server skeleton with stdio + http transport"
```

---

### Task 6: Tool registration helper (`baba_mcp/tools/_helpers.py`)

Centralizza il pattern di registrazione: input Pydantic → POST verso gateway → ritorno dict.

**Files:**
- Create: `baba_mcp/tools/_helpers.py`
- Test: `tests/test_mcp_tool_helpers.py`

- [ ] **Step 1: Test failing**

`tests/test_mcp_tool_helpers.py`:

```python
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
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_mcp_tool_helpers.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implementa**

`baba_mcp/tools/_helpers.py`:

```python
"""Helpers comuni per la registrazione dei tools MCP."""
from __future__ import annotations
from typing import Any, Mapping
from pydantic import BaseModel
from baba_mcp.client import GatewayClient


async def call_gateway(
    client: GatewayClient, path: str, payload: BaseModel
) -> Mapping[str, Any]:
    """Serializza un input Pydantic con i nomi alias (PascalCase per il gateway)
    e fa POST. Tutti gli errori HTTP sono già tradotti in McpToolError dal client.
    """
    body = payload.model_dump(by_alias=True, exclude_none=True)
    return await client.post(path, body)
```

- [ ] **Step 4: Run**

```bash
pytest tests/test_mcp_tool_helpers.py -v
```
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add baba_mcp/tools/_helpers.py tests/test_mcp_tool_helpers.py
git commit -m "feat(mcp): tool registration helper (call_gateway)"
```

---

### Task 7: Canary tool — `monitor_get_balance`

Primo tool end-to-end: fissa il pattern che tutti gli altri seguono.

**Files:**
- Create: `baba_mcp/tools/monitor.py` (parziale, solo balance + register stub)
- Test: `tests/test_mcp_monitor_balance.py`

- [ ] **Step 1: Test failing**

`tests/test_mcp_monitor_balance.py`:

```python
import asyncio, httpx, pytest
from baba_mcp.client import GatewayClient
from baba_mcp.errors import McpToolError
from baba_mcp.tools.monitor import _get_balance_impl, MonitorGetBalanceInput


def make_client(handler):
    return GatewayClient(
        base_url="http://gw.test",
        transport=httpx.MockTransport(handler),
        timeout_ms=2000,
        max_retries=1,
    )


def test_get_balance_happy_path():
    seen = {}
    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = req.content
        return httpx.Response(200, json={
            "balance": "1.234", "tokens": [], "delegatedOut": 0, "delegatedIn": 0,
            "success": True, "message": "Tokens not supported",
        })
    c = make_client(handler)
    inp = MonitorGetBalanceInput(public_key="WalletAaa")
    out = asyncio.run(_get_balance_impl(c, inp))
    assert seen["url"] == "http://gw.test/api/Monitor/GetBalance"
    assert b'"PublicKey": "WalletAaa"' in seen["body"]
    assert out["balance"] == "1.234"
    assert out["success"] is True


def test_get_balance_503_propagates():
    def handler(req):
        return httpx.Response(503, json={"success": False})
    c = make_client(handler)
    with pytest.raises(McpToolError) as ei:
        asyncio.run(_get_balance_impl(c, MonitorGetBalanceInput(public_key="x")))
    assert ei.value.code == "node_unavailable"
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_mcp_monitor_balance.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implementa `baba_mcp/tools/monitor.py` (versione minima per balance)**

```python
"""Monitor tools — wallet inspection + estimated fee + long-poll waits.

Tools:
  monitor_get_balance, monitor_get_wallet_info,
  monitor_get_transactions_by_wallet, monitor_get_estimated_fee,
  monitor_wait_for_block, monitor_wait_for_smart_transaction
"""
from __future__ import annotations
from typing import Any, Mapping
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base, PublicKeyInput, PaginatedInput
from baba_mcp.tools._helpers import call_gateway


# ---------- Inputs ----------

class MonitorGetBalanceInput(PublicKeyInput):
    pass


# ---------- Implementations (testabili in isolamento) ----------

async def _get_balance_impl(client, inp: MonitorGetBalanceInput) -> Mapping[str, Any]:
    return await call_gateway(client, "/api/Monitor/GetBalance", inp)


# ---------- Registration ----------

def register(server: Server) -> None:
    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name="monitor_get_balance",
                description=(
                    "Read the CS balance + delegation totals of a Credits wallet. "
                    "Read-only. Input: { PublicKey: <base58> }."
                ),
                inputSchema=MonitorGetBalanceInput.model_json_schema(by_alias=True),
                annotations={"readOnlyHint": True},
            ),
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        client = server.gateway  # type: ignore[attr-defined]
        if name == "monitor_get_balance":
            inp = MonitorGetBalanceInput.model_validate(arguments)
            res = await _get_balance_impl(client, inp)
            import json
            return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
        raise ValueError(f"Unknown tool: {name}")
```

NB: la funzione `_get_balance_impl` è separata dalla registrazione MCP così possiamo testarla unitariamente senza dover bootstrappare il server. Stesso pattern per tutti i tool successivi.

- [ ] **Step 4: Run**

```bash
pytest tests/test_mcp_monitor_balance.py -v
```
Expected: 2 PASSED.

- [ ] **Step 5: Stub register chiamato dagli altri moduli (anti-import-error)**

Dato che `baba_mcp/server.py` importa `transaction, tokens, smartcontract, userfields, diag` ma non esistono ancora, crea stub vuoti di register per ognuno per evitare import error nei test:

```bash
for m in transaction tokens smartcontract userfields diag; do
  printf '"""Stub - tools registered in subsequent tasks."""\nfrom mcp.server import Server\n\ndef register(server: Server) -> None:\n    pass\n' > "baba_mcp/tools/$m.py"
done
```

- [ ] **Step 6: Verifica che il server bootstrap non crashi**

```bash
python3 -c "from baba_mcp.server import load_config, build_server; build_server(load_config())"
```
Expected: nessun errore.

- [ ] **Step 7: Commit**

```bash
git add baba_mcp/tools/ tests/test_mcp_monitor_balance.py
git commit -m "feat(mcp): canary tool monitor_get_balance + stub modules"
```

---

## Phase 2 — Restanti tools (28)

> **Pattern unificato per ognuno dei 28 tools rimanenti** — ogni task segue 5 step identici (test failing → run → impl → run → commit). Il codice di test e di implementazione è esplicito per ogni tool perché parametri e response shape variano.

> Ognuna delle task seguenti **modifica `baba_mcp/tools/<categoria>.py`** aggiungendo:
> 1. Un nuovo modello Pydantic `<Tool>Input` (eredita da `_Base` o sotto-modello apposito).
> 2. Una funzione `_<tool>_impl(client, inp)` che chiama `call_gateway`.
> 3. Una nuova entry in `_list_tools()` con `name`, `description`, `inputSchema`, `annotations`.
> 4. Un nuovo branch `if name == "<tool>":` in `_call`.
> 5. Un test in `tests/test_mcp_<categoria>_tools.py` (file unico per categoria, test cumulati).

> Per non duplicare boilerplate identico, l'engineer può estrarre le parti `_list_tools` e `_call` in helper interni dopo Task 13 (refactor opzionale, fa parte di Task 13 stessa).

### Task 8: `monitor_get_wallet_info`

**Files:**
- Modify: `baba_mcp/tools/monitor.py`
- Test: `tests/test_mcp_monitor_tools.py` (file nuovo, raggruppa tutti i monitor tools dopo balance)

- [ ] **Step 1: Test failing**

```python
# tests/test_mcp_monitor_tools.py
import asyncio, httpx, pytest
from baba_mcp.client import GatewayClient
from baba_mcp.tools.monitor import (
    MonitorGetWalletInfoInput, _get_wallet_info_impl,
)


def make_client(handler):
    return GatewayClient(
        base_url="http://gw.test",
        transport=httpx.MockTransport(handler),
        timeout_ms=2000, max_retries=1,
    )


def test_get_wallet_info_full_response():
    def handler(req):
        assert str(req.url).endswith("/api/Monitor/GetWalletInfo")
        return httpx.Response(200, json={
            "balance": "100.0",
            "lastTransaction": 42,
            "delegated": {"incoming": 0, "outgoing": 0, "donors": [], "recipients": []},
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_get_wallet_info_impl(c, MonitorGetWalletInfoInput(public_key="x")))
    assert out["balance"] == "100.0"
    assert out["lastTransaction"] == 42
```

- [ ] **Step 2: Run, fail expected**

- [ ] **Step 3: Aggiungi a `baba_mcp/tools/monitor.py`**

```python
class MonitorGetWalletInfoInput(PublicKeyInput):
    pass

async def _get_wallet_info_impl(client, inp):
    return await call_gateway(client, "/api/Monitor/GetWalletInfo", inp)
```

E nel `_list_tools()` aggiungi:

```python
Tool(
    name="monitor_get_wallet_info",
    description=(
        "Read full wallet data: balance + lastTransactionId + delegations "
        "(incoming/outgoing totals + donors/recipients lists). Read-only."
    ),
    inputSchema=MonitorGetWalletInfoInput.model_json_schema(by_alias=True),
    annotations={"readOnlyHint": True},
),
```

E nel `_call` aggiungi prima del `raise ValueError`:

```python
if name == "monitor_get_wallet_info":
    inp = MonitorGetWalletInfoInput.model_validate(arguments)
    res = await _get_wallet_info_impl(client, inp)
    import json
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
```

- [ ] **Step 4: Run**

```bash
pytest tests/test_mcp_monitor_tools.py -v
```
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add baba_mcp/tools/monitor.py tests/test_mcp_monitor_tools.py
git commit -m "feat(mcp): tool monitor_get_wallet_info"
```

---

### Task 9: `monitor_get_transactions_by_wallet`

- [ ] **Step 1: Aggiungi test in `tests/test_mcp_monitor_tools.py`**

```python
from baba_mcp.tools.monitor import (
    MonitorGetTransactionsByWalletInput, _get_transactions_by_wallet_impl,
)

def test_get_transactions_by_wallet_passes_pagination():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"message": None, "success": True, "transactions": []})
    c = make_client(handler)
    inp = MonitorGetTransactionsByWalletInput(public_key="x", offset=10, limit=20)
    out = asyncio.run(_get_transactions_by_wallet_impl(c, inp))
    assert b'"offset": 10' in seen["body"]
    assert b'"limit": 20' in seen["body"]
    assert out["success"] is True
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Aggiungi a `monitor.py`**

```python
class MonitorGetTransactionsByWalletInput(PaginatedInput):
    pass

async def _get_transactions_by_wallet_impl(client, inp):
    return await call_gateway(client, "/api/Monitor/GetTransactionsByWallet", inp)
```

Tool entry:
```python
Tool(
    name="monitor_get_transactions_by_wallet",
    description=(
        "Paginated transaction history for a wallet. Returns id, sum, fee, "
        "from/to, time, status, currency. Default page size 10, max 500. Read-only."
    ),
    inputSchema=MonitorGetTransactionsByWalletInput.model_json_schema(by_alias=True),
    annotations={"readOnlyHint": True},
),
```

Branch in `_call`:
```python
if name == "monitor_get_transactions_by_wallet":
    inp = MonitorGetTransactionsByWalletInput.model_validate(arguments)
    res = await _get_transactions_by_wallet_impl(client, inp)
    import json
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
```

- [ ] **Step 4: Run, pass.**
- [ ] **Step 5: Commit `feat(mcp): tool monitor_get_transactions_by_wallet`**

---

### Task 10: `monitor_get_estimated_fee`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.monitor import MonitorGetEstimatedFeeInput, _get_estimated_fee_impl

def test_get_estimated_fee():
    def handler(req):
        return httpx.Response(200, json={"fee": 0.00874, "success": True, "message": ""})
    c = make_client(handler)
    out = asyncio.run(_get_estimated_fee_impl(c, MonitorGetEstimatedFeeInput(transactionSize=9)))
    assert out["fee"] == 0.00874
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Aggiungi a `monitor.py`**

```python
class MonitorGetEstimatedFeeInput(_Base):
    transaction_size: int = Field(alias="transactionSize", ge=0)

async def _get_estimated_fee_impl(client, inp):
    return await call_gateway(client, "/api/Monitor/GetEstimatedFee", inp)
```

Tool entry e branch `_call` come da pattern (nome `monitor_get_estimated_fee`, descrizione "Estimate fee for a transaction of given byte size. Read-only.", `readOnlyHint`).

- [ ] **Step 4: Run, pass.**
- [ ] **Step 5: Commit.**

---

### Task 11: `monitor_wait_for_block`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.monitor import MonitorWaitForBlockInput, _wait_for_block_impl

def test_wait_for_block_returns_hash_and_changed_flag():
    def handler(req):
        return httpx.Response(200, json={
            "blockHash": "PoolHashB58...",
            "changed": True,
            "success": True,
        })
    c = make_client(handler)
    out = asyncio.run(_wait_for_block_impl(c, MonitorWaitForBlockInput(timeoutMs=30000)))
    assert out["changed"] is True
    assert "blockHash" in out
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Aggiungi**

```python
from typing import Optional

class MonitorWaitForBlockInput(_Base):
    timeout_ms: int = Field(alias="timeoutMs", ge=0, le=60000, default=30000)
    pool_hash: Optional[str] = Field(alias="poolHash", default=None,
        description="Optional base58 hash of last seen block (long-poll cursor)")

async def _wait_for_block_impl(client, inp):
    return await call_gateway(client, "/api/Monitor/WaitForBlock", inp)
```

Tool entry: descrizione "Long-poll: blocks until a new pool is sealed on the node, or timeoutMs elapses. Returns blockHash + `changed` flag. Read-only.", `readOnlyHint`.

Branch `_call`: pattern standard.

- [ ] **Step 4: Run, pass.**
- [ ] **Step 5: Commit.**

---

### Task 12: `monitor_wait_for_smart_transaction`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.monitor import (
    MonitorWaitForSmartTransactionInput, _wait_for_smart_transaction_impl,
)

def test_wait_for_smart_transaction_passes_address_and_timeout():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={
            "transactionId": "12345.1", "found": True, "success": True,
        })
    c = make_client(handler)
    inp = MonitorWaitForSmartTransactionInput(address="ContractB58", timeoutMs=20000)
    out = asyncio.run(_wait_for_smart_transaction_impl(c, inp))
    assert b'"address": "ContractB58"' in seen["body"]
    assert b'"timeoutMs": 20000' in seen["body"]
    assert out["found"] is True
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Aggiungi**

```python
class MonitorWaitForSmartTransactionInput(_Base):
    address: str
    timeout_ms: int = Field(alias="timeoutMs", ge=0, le=60000, default=30000)

async def _wait_for_smart_transaction_impl(client, inp):
    return await call_gateway(client, "/api/Monitor/WaitForSmartTransaction", inp)
```

Tool entry: descrizione "Long-poll: blocks until the next smart-contract transaction targeting `address` is sealed. Returns transactionId + found. Read-only.", `readOnlyHint`. Branch `_call` standard.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 13: Refactor `_call` di monitor.py in dispatch dict (opzionale ma consigliato)

Dopo 6 tools nel modulo, il blocco `if/elif` in `_call` diventa rumoroso. Refactor:

- [ ] **Step 1: Test (no behavior change)**

Ri-eseguire tutti i test del file `tests/test_mcp_monitor_tools.py` + `tests/test_mcp_monitor_balance.py` deve restare verde.

- [ ] **Step 2: Modifica `monitor.py`**

Sostituisci il `_call` con:

```python
import json

_DISPATCH = {
    "monitor_get_balance":              (MonitorGetBalanceInput, _get_balance_impl),
    "monitor_get_wallet_info":          (MonitorGetWalletInfoInput, _get_wallet_info_impl),
    "monitor_get_transactions_by_wallet":(MonitorGetTransactionsByWalletInput, _get_transactions_by_wallet_impl),
    "monitor_get_estimated_fee":        (MonitorGetEstimatedFeeInput, _get_estimated_fee_impl),
    "monitor_wait_for_block":           (MonitorWaitForBlockInput, _wait_for_block_impl),
    "monitor_wait_for_smart_transaction":(MonitorWaitForSmartTransactionInput, _wait_for_smart_transaction_impl),
}

@server.call_tool()
async def _call(name: str, arguments: dict) -> list[TextContent]:
    client = server.gateway  # type: ignore[attr-defined]
    if name not in _DISPATCH:
        raise ValueError(f"Unknown tool: {name}")
    cls, impl = _DISPATCH[name]
    inp = cls.model_validate(arguments)
    res = await impl(client, inp)
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
```

- [ ] **Step 3: Run all monitor tests, must pass.**

```bash
pytest tests/test_mcp_monitor_tools.py tests/test_mcp_monitor_balance.py -v
```

- [ ] **Step 4: Commit `refactor(mcp): dispatch dict in monitor tools`**

> **Nota per le categorie successive**: usa il dispatch-dict pattern fin dall'inizio (niente if/elif catena).

---

### Task 14: Categoria `transaction` — file iniziale + `transaction_get_info`

**Files:**
- Modify: `baba_mcp/tools/transaction.py` (sostituisci lo stub vuoto)
- Test: `tests/test_mcp_transaction_tools.py` (nuovo)

- [ ] **Step 1: Test**

```python
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
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implementa `baba_mcp/tools/transaction.py`**

```python
"""Transaction tools — info / pack / execute / result."""
from __future__ import annotations
import json
from typing import Any, Mapping
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base, TransactionIdInput, TransferIntent
from baba_mcp.tools._helpers import call_gateway


class TransactionGetInfoInput(TransactionIdInput):
    pass


async def _get_info_impl(client, inp):
    return await call_gateway(client, "/api/Transaction/GetTransactionInfo", inp)


_DISPATCH: dict = {
    "transaction_get_info": (TransactionGetInfoInput, _get_info_impl),
}

_TOOL_DEFS = [
    Tool(
        name="transaction_get_info",
        description=(
            "Fetch full info of a single transaction by id (`<poolSeq>.<index1>`). "
            "Returns from/to, sum, fee, status, transactionType, userData, signature. "
            "Read-only."
        ),
        inputSchema=TransactionGetInfoInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
]


def register(server: Server) -> None:
    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return list(_TOOL_DEFS)

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        client = server.gateway  # type: ignore[attr-defined]
        if name not in _DISPATCH:
            raise ValueError(f"Unknown tool: {name}")
        cls, impl = _DISPATCH[name]
        inp = cls.model_validate(arguments)
        res = await impl(client, inp)
        return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
```

- [ ] **Step 4: Run, pass.**

- [ ] **Step 5: Commit `feat(mcp): tool transaction_get_info + module bootstrap`.**

---

### Task 15: `transaction_pack`

- [ ] **Step 1: Test in `tests/test_mcp_transaction_tools.py`**

```python
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
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi a `transaction.py`**

```python
class TransactionPackInput(TransferIntent):
    pass

async def _pack_impl(client, inp):
    return await call_gateway(client, "/api/Transaction/Pack", inp)
```

Aggiungi a `_DISPATCH`:
```python
"transaction_pack": (TransactionPackInput, _pack_impl),
```

E a `_TOOL_DEFS`:
```python
Tool(
    name="transaction_pack",
    description=(
        "Build the canonical signing payload for a CS transfer. "
        "Returns base58 `transactionPackagedStr` ready to be signed client-side "
        "(ed25519). The payload encodes inner_id, source, target, amount, fee, "
        "currency, userFields. Pass feeAsString=\"0\" to use the recommendedFee. "
        "No on-chain side-effect."
    ),
    inputSchema=TransactionPackInput.model_json_schema(by_alias=True),
    annotations={"idempotentHint": True},
),
```

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 16: `transaction_execute`

- [ ] **Step 1: Test**

```python
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
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi a `transaction.py`**

```python
class TransactionExecuteInput(TransferIntent):
    transaction_signature: str = Field(alias="TransactionSignature", min_length=1)

async def _execute_impl(client, inp):
    return await call_gateway(client, "/api/Transaction/Execute", inp)
```

Dispatch e tool entry:
```python
"transaction_execute": (TransactionExecuteInput, _execute_impl),
```
```python
Tool(
    name="transaction_execute",
    description=(
        "Submit a signed CS transfer to the Credits node. Requires "
        "TransactionSignature (base58 ed25519 signature of the packagedStr "
        "produced by transaction_pack). The same PublicKey/ReceiverPublicKey/"
        "amountAsString/feeAsString/UserData passed to transaction_pack must be "
        "passed here unchanged, otherwise the inner_id rebuilt server-side will "
        "not match and the node will reject with 'Transaction has wrong "
        "signature.'. Writes to the blockchain — costs fee."
    ),
    inputSchema=TransactionExecuteInput.model_json_schema(by_alias=True),
    annotations={"destructiveHint": True},
),
```

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 17: `transaction_result`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.transaction import TransactionResultInput, _result_impl

def test_transaction_result_returns_status():
    def handler(req):
        return httpx.Response(200, json={
            "transactionId": "174575023.1", "found": True,
            "executionTime": 12, "returnValue": None,
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_result_impl(c, TransactionResultInput(transactionId="174575023.1")))
    assert out["found"] is True
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
class TransactionResultInput(TransactionIdInput):
    pass

async def _result_impl(client, inp):
    return await call_gateway(client, "/api/Transaction/Result", inp)
```

Dispatch + tool def, descrizione "Get the SmartExecutionResult of a smart-contract transaction (executionTime, returnValue Variant, status). For non-smart transactions returns minimal info. Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 18: Categoria `tokens` — file iniziale + `tokens_info`

**Files:**
- Modify: `baba_mcp/tools/tokens.py` (sostituisce stub)
- Test: `tests/test_mcp_tokens_tools.py`

- [ ] **Step 1: Test**

```python
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
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implementa `baba_mcp/tools/tokens.py`**

```python
"""Tokens tools — balances/transfers/info/holders/transactions."""
from __future__ import annotations
import json
from typing import Any, Mapping, Optional
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base, TokenAddressInput
from baba_mcp.tools._helpers import call_gateway


class TokensInfoInput(TokenAddressInput):
    pass

async def _info_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/Info", inp)


_DISPATCH: dict = {
    "tokens_info": (TokensInfoInput, _info_impl),
}

_TOOL_DEFS = [
    Tool(
        name="tokens_info",
        description=(
            "Read metadata of a Credits token (name/code/decimals/totalSupply/owner). "
            "Read-only."
        ),
        inputSchema=TokensInfoInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
]


def register(server: Server) -> None:
    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return list(_TOOL_DEFS)

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        client = server.gateway  # type: ignore[attr-defined]
        if name not in _DISPATCH:
            raise ValueError(f"Unknown tool: {name}")
        cls, impl = _DISPATCH[name]
        inp = cls.model_validate(arguments)
        res = await impl(client, inp)
        return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
```

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 19: `tokens_balances_get`

- [ ] **Step 1: Test**

```python
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
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Aggiungi**

```python
from baba_mcp.schemas import PaginatedInput

class TokensBalancesGetInput(PaginatedInput):
    pass

async def _balances_get_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/BalancesGet", inp)
```

`_DISPATCH["tokens_balances_get"] = (TokensBalancesGetInput, _balances_get_impl)`. Tool def description "List token balances for a wallet (paginated). Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 20: `tokens_transfers_get`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.tokens import TokensTransfersGetInput, _transfers_get_impl

def test_tokens_transfers_get():
    def handler(req):
        return httpx.Response(200, json={"transfers": [], "success": True, "message": None})
    c = make_client(handler)
    inp = TokensTransfersGetInput(token="TokB58", offset=0, limit=10)
    out = asyncio.run(_transfers_get_impl(c, inp))
    assert out["success"] is True
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Aggiungi**

```python
class TokensTransfersGetInput(_Base):
    token: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=500)

async def _transfers_get_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/TransfersGet", inp)
```

Tool def "List recent transfers of a specific token. Paginated. Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 21: `tokens_holders_get`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.tokens import TokensHoldersGetInput, _holders_get_impl

def test_tokens_holders_get_with_order():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"holders": [], "success": True, "message": None})
    c = make_client(handler)
    inp = TokensHoldersGetInput(token="TokB58", offset=0, limit=10, order=0, desc=True)
    out = asyncio.run(_holders_get_impl(c, inp))
    assert b'"order": 0' in seen["body"]
    assert b'"desc": true' in seen["body"]
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Aggiungi**

```python
class TokensHoldersGetInput(_Base):
    token: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=500)
    order: int = Field(default=0, description="0=balance, 1=transfersCount")
    desc: bool = Field(default=True)

async def _holders_get_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/HoldersGet", inp)
```

Tool def "List token holders sorted by balance (default) or transfersCount. Paginated. Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 22: `tokens_transactions_get`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.tokens import TokensTransactionsGetInput, _transactions_get_impl

def test_tokens_transactions_get():
    def handler(req):
        return httpx.Response(200, json={"transactions": [], "success": True, "message": None})
    c = make_client(handler)
    inp = TokensTransactionsGetInput(token="TokB58", offset=0, limit=10)
    out = asyncio.run(_transactions_get_impl(c, inp))
    assert out["success"] is True
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Aggiungi**

```python
class TokensTransactionsGetInput(_Base):
    token: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=500)

async def _transactions_get_impl(client, inp):
    return await call_gateway(client, "/api/Tokens/TransactionsGet", inp)
```

Tool def "List on-chain transactions interacting with a specific token contract. Paginated. Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 23: Categoria `smartcontract` — file iniziale + `smartcontract_compile`

**Files:**
- Modify: `baba_mcp/tools/smartcontract.py`
- Test: `tests/test_mcp_smartcontract_tools.py`

- [ ] **Step 1: Test**

```python
import asyncio, httpx, pytest
from baba_mcp.client import GatewayClient
from baba_mcp.tools.smartcontract import SmartContractCompileInput, _compile_impl

def make_client(handler):
    return GatewayClient(base_url="http://gw.test",
        transport=httpx.MockTransport(handler), timeout_ms=10_000, max_retries=1)

def test_smartcontract_compile_returns_bytecode():
    def handler(req):
        return httpx.Response(200, json={
            "byteCodeObjects": [{"name": "BasicCounter",
                "byteCode": "yv66vgAAA..."}],
            "tokenStandard": 0, "success": True, "message": None,
        })
    c = make_client(handler)
    code = "import com.credits.scapi.v0.SmartContract;\n public class C extends SmartContract { ... }"
    inp = SmartContractCompileInput(sourceCode=code)
    out = asyncio.run(_compile_impl(c, inp))
    assert out["byteCodeObjects"][0]["name"] == "BasicCounter"
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implementa `baba_mcp/tools/smartcontract.py`**

```python
"""SmartContract tools — compile/pack/deploy/execute/get/methods/state/list."""
from __future__ import annotations
import json
from typing import Any, List, Mapping, Optional
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base
from baba_mcp.tools._helpers import call_gateway


class SmartContractCompileInput(_Base):
    source_code: str = Field(alias="sourceCode", min_length=1)


async def _compile_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Compile", inp)


_DISPATCH: dict = {
    "smartcontract_compile": (SmartContractCompileInput, _compile_impl),
}

_TOOL_DEFS = [
    Tool(
        name="smartcontract_compile",
        description=(
            "Compile Java source for a Credits smart contract. The sourceCode "
            "MUST contain `import com.credits.scapi.v0.SmartContract;` "
            "explicitly — the executor fails silently otherwise. Compile may "
            "take up to ~120s under load. Returns byteCodeObjects (base64) ready "
            "to be passed to smartcontract_pack/deploy. Read-only (no on-chain "
            "side-effect)."
        ),
        inputSchema=SmartContractCompileInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True, "idempotentHint": True},
    ),
]


def register(server: Server) -> None:
    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return list(_TOOL_DEFS)

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        client = server.gateway  # type: ignore[attr-defined]
        if name not in _DISPATCH:
            raise ValueError(f"Unknown tool: {name}")
        cls, impl = _DISPATCH[name]
        inp = cls.model_validate(arguments)
        res = await impl(client, inp)
        return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
```

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 24: `smartcontract_pack`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.smartcontract import SmartContractPackInput, _pack_impl

def test_smartcontract_pack_deploy_payload():
    def handler(req):
        return httpx.Response(200, json={
            "success": True,
            "dataResponse": {
                "transactionPackagedStr": "ScPack58...",
                "transactionInnerId": 7,
                "deployedAddress": "FwdrHR...",
                "recommendedFee": 0.1,
            },
            "message": None,
        })
    c = make_client(handler)
    inp = SmartContractPackInput(
        public_key="A", source_code="...",
        byte_code_objects=[{"name": "BasicCounter", "byteCode": "AAA="}],
        operation="deploy",
    )
    out = asyncio.run(_pack_impl(c, inp))
    assert out["dataResponse"]["transactionInnerId"] == 7
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
class SmartContractPackInput(_Base):
    public_key: str = Field(alias="PublicKey")
    operation: str = Field(description='"deploy" or "execute"')
    receiver_public_key: Optional[str] = Field(alias="ReceiverPublicKey", default=None,
        description="Required for execute (target contract address)")
    source_code: Optional[str] = Field(alias="sourceCode", default=None,
        description="Required for deploy")
    byte_code_objects: Optional[List[dict]] = Field(alias="byteCodeObjects", default=None,
        description="Required for deploy: [{name, byteCode(base64)}, ...]")
    method: Optional[str] = Field(default=None, description="Required for execute")
    params: Optional[List[dict]] = Field(default=None,
        description="Variant list for execute method args")
    fee_as_string: str = Field(alias="feeAsString", default="0")
    user_data: str = Field(alias="UserData", default="")

async def _pack_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Pack", inp)
```

Aggiungi `"smartcontract_pack": (SmartContractPackInput, _pack_impl)` al dispatch e tool def:

```python
Tool(
    name="smartcontract_pack",
    description=(
        "Build the canonical signing payload for a smart-contract Deploy or "
        "Execute. operation='deploy' requires sourceCode + byteCodeObjects; "
        "operation='execute' requires ReceiverPublicKey (contract addr) + method "
        "+ params (Variant list). The response includes transactionInnerId — you "
        "MUST pass it back unchanged to smartcontract_deploy/execute, otherwise "
        "the rebuilt inner_id may differ and the signature will be rejected. "
        "For deploy, also returns deployedAddress (deterministic). No on-chain "
        "side-effect."
    ),
    inputSchema=SmartContractPackInput.model_json_schema(by_alias=True),
    annotations={"idempotentHint": True},
),
```

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 25: `smartcontract_deploy`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.smartcontract import SmartContractDeployInput, _deploy_impl

def test_smartcontract_deploy_with_inner_id_override():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={
            "success": True,
            "transactionId": "174580000.1",
            "deployedAddress": "FwdrHR...",
            "actualFee": "0.1", "message": None,
        })
    c = make_client(handler)
    inp = SmartContractDeployInput(
        public_key="A", source_code="...",
        byte_code_objects=[{"name": "C", "byteCode": "AAA="}],
        transaction_signature="Sig58...",
        transaction_inner_id=7,
    )
    out = asyncio.run(_deploy_impl(c, inp))
    assert out["transactionId"] == "174580000.1"
    assert b'"transactionInnerId": 7' in seen["body"]
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
class SmartContractDeployInput(_Base):
    public_key: str = Field(alias="PublicKey")
    source_code: str = Field(alias="sourceCode")
    byte_code_objects: List[dict] = Field(alias="byteCodeObjects")
    transaction_signature: str = Field(alias="TransactionSignature")
    transaction_inner_id: int = Field(alias="transactionInnerId", ge=1,
        description="Must be the same value returned by smartcontract_pack")
    fee_as_string: str = Field(alias="feeAsString", default="0")
    user_data: str = Field(alias="UserData", default="")

async def _deploy_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Deploy", inp)
```

Tool def:
```python
Tool(
    name="smartcontract_deploy",
    description=(
        "Deploy a Java smart contract on Credits. Requires the byteCodeObjects "
        "from smartcontract_compile and the signed payload from smartcontract_pack "
        "(operation='deploy'). transactionInnerId MUST equal the value returned by "
        "smartcontract_pack. Writes to the blockchain — fee ~0.1 CS."
    ),
    inputSchema=SmartContractDeployInput.model_json_schema(by_alias=True),
    annotations={"destructiveHint": True},
),
```

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 26: `smartcontract_execute`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.smartcontract import SmartContractExecuteInput, _execute_impl

def test_smartcontract_execute():
    def handler(req):
        return httpx.Response(200, json={
            "success": True, "transactionId": "174580010.1",
            "actualFee": "0.05", "smartContractResult": None, "message": None,
        })
    c = make_client(handler)
    inp = SmartContractExecuteInput(
        public_key="A", receiver_public_key="ContrB58", method="getCounter",
        params=[], transaction_signature="Sig58...", transaction_inner_id=8,
    )
    out = asyncio.run(_execute_impl(c, inp))
    assert out["success"] is True
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
class SmartContractExecuteInput(_Base):
    public_key: str = Field(alias="PublicKey")
    receiver_public_key: str = Field(alias="ReceiverPublicKey",
        description="Contract address (base58)")
    method: str
    params: List[dict] = Field(default_factory=list,
        description="Variant list of arguments")
    transaction_signature: str = Field(alias="TransactionSignature")
    transaction_inner_id: int = Field(alias="transactionInnerId", ge=1)
    fee_as_string: str = Field(alias="feeAsString", default="0")
    user_data: str = Field(alias="UserData", default="")

async def _execute_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Execute", inp)
```

Tool def "Call a method on a deployed Credits smart contract. Requires signed payload from smartcontract_pack (operation='execute'). transactionInnerId must equal the pack response. Writes to the blockchain.", `destructiveHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 27: `smartcontract_get`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.smartcontract import SmartContractGetInput, _get_impl

def test_smartcontract_get_returns_source_and_bytecode():
    def handler(req):
        return httpx.Response(200, json={
            "address": "FwdrHR...", "deployer": "OwnerB58",
            "sourceCode": "public class C ...",
            "byteCodeObjects": [{"name": "C", "byteCode": "AAA="}],
            "transactionsCount": 4, "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_get_impl(c, SmartContractGetInput(address="FwdrHR...")))
    assert out["transactionsCount"] == 4
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
class SmartContractGetInput(_Base):
    address: str

async def _get_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Get", inp)
```

Tool def "Read deployed smart contract: deployer, sourceCode, byteCodeObjects, transactionsCount. Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 28: `smartcontract_methods`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.smartcontract import SmartContractMethodsInput, _methods_impl

def test_smartcontract_methods_by_address():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={
            "methods": [{"name": "getCounter", "args": [], "returnType": "long"}],
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_methods_impl(c, SmartContractMethodsInput(address="FwdrHR...")))
    assert len(out["methods"]) == 1
    assert b'"address": "FwdrHR..."' in seen["body"]

def test_smartcontract_methods_by_bytecode():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"methods": [], "success": True, "message": None})
    c = make_client(handler)
    out = asyncio.run(_methods_impl(c, SmartContractMethodsInput(
        byte_code_objects=[{"name": "C", "byteCode": "AAA="}])))
    assert b'"byteCodeObjects"' in seen["body"]
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
from pydantic import model_validator

class SmartContractMethodsInput(_Base):
    address: Optional[str] = None
    byte_code_objects: Optional[List[dict]] = Field(alias="byteCodeObjects", default=None)

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.address is None) == (self.byte_code_objects is None):
            raise ValueError("Provide exactly one of: address, byteCodeObjects")
        return self

async def _methods_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/Methods", inp)
```

Tool def "List the public methods of a smart contract. Provide either `address` (deployed contract) or `byteCodeObjects` (pre-deploy inspection). Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 29: `smartcontract_state`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.smartcontract import SmartContractStateInput, _state_impl

def test_smartcontract_state():
    def handler(req):
        return httpx.Response(200, json={
            "fields": [{"name": "counter", "type": "long", "value": 4}],
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_state_impl(c, SmartContractStateInput(address="FwdrHR...")))
    assert out["fields"][0]["value"] == 4
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
class SmartContractStateInput(_Base):
    address: str

async def _state_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/State", inp)
```

Tool def "Read the current public state (instance fields) of a deployed smart contract. Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 30: `smartcontract_list_by_wallet`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.smartcontract import SmartContractListByWalletInput, _list_by_wallet_impl

def test_smartcontract_list_by_wallet_paginated():
    seen = {}
    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"contracts": [], "success": True, "message": None})
    c = make_client(handler)
    out = asyncio.run(_list_by_wallet_impl(c, SmartContractListByWalletInput(
        deployer="OwnerB58", offset=0, limit=10)))
    assert b'"offset": 0' in seen["body"]
    assert b'"limit": 10' in seen["body"]
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
class SmartContractListByWalletInput(_Base):
    deployer: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=500)

async def _list_by_wallet_impl(client, inp):
    return await call_gateway(client, "/api/SmartContract/ListByWallet", inp)
```

Tool def "List smart contracts deployed by a wallet (paginated). Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 31: Categoria `userfields` — `userfields_encode`

**Files:**
- Modify: `baba_mcp/tools/userfields.py`
- Test: `tests/test_mcp_userfields_tools.py`

- [ ] **Step 1: Test**

```python
import asyncio, httpx
from baba_mcp.client import GatewayClient
from baba_mcp.tools.userfields import UserFieldsEncodeInput, _encode_impl

def make_client(handler):
    return GatewayClient(base_url="http://gw.test",
        transport=httpx.MockTransport(handler), timeout_ms=2000, max_retries=1)

def test_userfields_encode():
    def handler(req):
        return httpx.Response(200, json={
            "success": True, "userData": "uF58...", "message": None,
        })
    c = make_client(handler)
    inp = UserFieldsEncodeInput(
        contentHashAlgo="sha-256",
        contentHash="0011223344556677889900112233445566778899001122334455667788990011",
        contentCid="bafybeigdyrabc",
        mime="image/png",
        sizeBytes=1234567,
    )
    out = asyncio.run(_encode_impl(c, inp))
    assert out["userData"].startswith("uF58")
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implementa `baba_mcp/tools/userfields.py`**

```python
"""UserFields v1 codec tools."""
from __future__ import annotations
import json
from typing import Any, Mapping, Optional
from pydantic import Field
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base
from baba_mcp.tools._helpers import call_gateway


class UserFieldsEncodeInput(_Base):
    content_hash_algo: str = Field(alias="contentHashAlgo", default="sha-256")
    content_hash: str = Field(alias="contentHash", min_length=1)
    content_cid: Optional[str] = Field(alias="contentCid", default=None)
    mime: Optional[str] = None
    size_bytes: Optional[int] = Field(alias="sizeBytes", default=None, ge=0)


async def _encode_impl(client, inp):
    return await call_gateway(client, "/api/UserFields/Encode", inp)


_DISPATCH: dict = {
    "userfields_encode": (UserFieldsEncodeInput, _encode_impl),
}

_TOOL_DEFS = [
    Tool(
        name="userfields_encode",
        description=(
            "Encode userFields v1 payload (hash + CID + mime + sizeBytes) into a "
            "base58 blob ready to be passed as `UserData` to transaction_pack. "
            "Pure function: no on-chain side-effect."
        ),
        inputSchema=UserFieldsEncodeInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True, "idempotentHint": True},
    ),
]


def register(server: Server) -> None:
    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return list(_TOOL_DEFS)

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        client = server.gateway  # type: ignore[attr-defined]
        if name not in _DISPATCH:
            raise ValueError(f"Unknown tool: {name}")
        cls, impl = _DISPATCH[name]
        inp = cls.model_validate(arguments)
        res = await impl(client, inp)
        return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
```

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 32: `userfields_decode`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.userfields import UserFieldsDecodeInput, _decode_impl

def test_userfields_decode():
    def handler(req):
        return httpx.Response(200, json={
            "success": True,
            "fields": {"contentHashAlgo": "sha-256", "contentHash": "0011...",
                       "contentCid": "bafy...", "mime": "image/png", "sizeBytes": 1234567},
            "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_decode_impl(c, UserFieldsDecodeInput(userData="uF58...")))
    assert out["fields"]["mime"] == "image/png"
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
class UserFieldsDecodeInput(_Base):
    user_data: str = Field(alias="userData", min_length=1)

async def _decode_impl(client, inp):
    return await call_gateway(client, "/api/UserFields/Decode", inp)
```

Tool def "Decode a userFields v1 base58 blob (as stored in a tx's UserData) into structured fields. Pure function. Read-only.", `readOnlyHint` + `idempotentHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 33: Categoria `diag` — `diag_get_active_nodes`

**Files:**
- Modify: `baba_mcp/tools/diag.py`
- Test: `tests/test_mcp_diag_tools.py`

- [ ] **Step 1: Test**

```python
import asyncio, httpx
from baba_mcp.client import GatewayClient
from baba_mcp.tools.diag import DiagEmptyInput, _active_nodes_impl

def make_client(handler):
    return GatewayClient(base_url="http://gw.test",
        transport=httpx.MockTransport(handler), timeout_ms=2000, max_retries=1)

def test_diag_get_active_nodes():
    def handler(req):
        return httpx.Response(200, json={
            "nodes": [{"publicKey": "NodeB58", "version": "5.x"}],
            "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_active_nodes_impl(c, DiagEmptyInput()))
    assert out["nodes"][0]["publicKey"] == "NodeB58"
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implementa `baba_mcp/tools/diag.py`**

```python
"""Diagnostic tools — active nodes / tx count / node info / supply."""
from __future__ import annotations
import json
from typing import Any, Mapping
from mcp.server import Server
from mcp.types import Tool, TextContent

from baba_mcp.schemas import _Base
from baba_mcp.tools._helpers import call_gateway


class DiagEmptyInput(_Base):
    pass


async def _active_nodes_impl(client, inp):
    return await call_gateway(client, "/api/Diag/GetActiveNodes", inp)


_DISPATCH: dict = {
    "diag_get_active_nodes": (DiagEmptyInput, _active_nodes_impl),
}

_TOOL_DEFS = [
    Tool(
        name="diag_get_active_nodes",
        description="List trusted/active nodes seen by the local node. Read-only.",
        inputSchema=DiagEmptyInput.model_json_schema(by_alias=True),
        annotations={"readOnlyHint": True},
    ),
]


def register(server: Server) -> None:
    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return list(_TOOL_DEFS)

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        client = server.gateway  # type: ignore[attr-defined]
        if name not in _DISPATCH:
            raise ValueError(f"Unknown tool: {name}")
        cls, impl = _DISPATCH[name]
        inp = cls.model_validate(arguments)
        res = await impl(client, inp)
        return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]
```

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 34: `diag_get_active_transactions_count`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.diag import _active_tx_count_impl, DiagEmptyInput

def test_diag_active_tx_count():
    def handler(req):
        return httpx.Response(200, json={"count": 17, "success": True, "message": None})
    c = make_client(handler)
    out = asyncio.run(_active_tx_count_impl(c, DiagEmptyInput()))
    assert out["count"] == 17
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
async def _active_tx_count_impl(client, inp):
    return await call_gateway(client, "/api/Diag/GetActiveTransactionsCount", inp)
```

Dispatch entry e tool def "Number of unconfirmed transactions currently in the mempool. Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 35: `diag_get_node_info`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.diag import _node_info_impl, DiagEmptyInput

def test_diag_node_info():
    def handler(req):
        return httpx.Response(200, json={
            "nodeVersion": "5.x", "uptimeMs": 12345678,
            "blockchainTopHash": "Hash58...", "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_node_info_impl(c, DiagEmptyInput()))
    assert out["nodeVersion"] == "5.x"
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
async def _node_info_impl(client, inp):
    return await call_gateway(client, "/api/Diag/GetNodeInfo", inp)
```

Tool def "Local Credits node version, uptime, top block hash. Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 36: `diag_get_supply`

- [ ] **Step 1: Test**

```python
from baba_mcp.tools.diag import _supply_impl, DiagEmptyInput

def test_diag_supply():
    def handler(req):
        return httpx.Response(200, json={
            "initial": "250000000.0", "mined": "1234567.0",
            "currentSupply": "251234567.0", "success": True, "message": None,
        })
    c = make_client(handler)
    out = asyncio.run(_supply_impl(c, DiagEmptyInput()))
    assert out["currentSupply"].startswith("251")
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Aggiungi**

```python
async def _supply_impl(client, inp):
    return await call_gateway(client, "/api/Diag/GetSupply", inp)
```

Tool def "Total CS supply on the network: initial + mined + currentSupply. Read-only.", `readOnlyHint`.

- [ ] **Step 4: Run.**
- [ ] **Step 5: Commit.**

---

### Task 37: Sanity check globale — server lista 29 tools

**Files:**
- Test: `tests/test_mcp_full_listing.py`

- [ ] **Step 1: Test**

```python
import asyncio
from baba_mcp.server import build_server, load_config


def test_server_lists_all_29_tools(monkeypatch):
    monkeypatch.delenv("BABA_GATEWAY_URL", raising=False)
    cfg = load_config()
    server = build_server(cfg)

    # Estrae i nomi dei tools registrati attraverso l'handler list_tools
    # (ogni modulo registra il suo @server.list_tools())
    handlers = server._list_tools_handlers  # type: ignore[attr-defined]
    names = []
    for handler in handlers:
        result = asyncio.run(handler())
        names.extend(t.name for t in result)

    expected = {
        "monitor_get_balance", "monitor_get_wallet_info",
        "monitor_get_transactions_by_wallet", "monitor_get_estimated_fee",
        "monitor_wait_for_block", "monitor_wait_for_smart_transaction",
        "transaction_get_info", "transaction_pack",
        "transaction_execute", "transaction_result",
        "userfields_encode", "userfields_decode",
        "tokens_balances_get", "tokens_transfers_get", "tokens_info",
        "tokens_holders_get", "tokens_transactions_get",
        "smartcontract_compile", "smartcontract_pack",
        "smartcontract_deploy", "smartcontract_execute",
        "smartcontract_get", "smartcontract_methods",
        "smartcontract_state", "smartcontract_list_by_wallet",
        "diag_get_active_nodes", "diag_get_active_transactions_count",
        "diag_get_node_info", "diag_get_supply",
    }
    assert set(names) == expected
    assert len(names) == 29
```

> **Nota tecnica**: il modo esatto di accedere agli handler dipende dall'API SDK installata. Se `server._list_tools_handlers` non è il nome corretto nella versione `mcp>=1.0` installata, l'engineer adatta usando il decoratore `@server.list_tools()` in modalità "test introspection" oppure fa il chiamata via `mcp.client.session` in-process. L'obiettivo del test è solo: enumera i tools registrati e confronta con il set atteso.

- [ ] **Step 2: Run, dovrebbe passare già**

```bash
pytest tests/test_mcp_full_listing.py -v
```

Se fallisce per il dettaglio sopra, aggiusta il modo di estrarre i nomi (es. usando `mcp.client.session.ClientSession` con uno stdio in-process). Quando passa, prosegui.

- [ ] **Step 3: Commit `test(mcp): assert all 29 tools registered`.**

---

## Phase 3 — Skill `baba-credits`

### Task 38: `SKILL.md` — entry point

**Files:**
- Create: `.claude/skills/baba-credits/SKILL.md`

- [ ] **Step 1: Crea il file con frontmatter + sezioni**

Contenuto completo (~250 righe):

```markdown
---
name: baba-credits
description: |
  Use when the user wants to interact with the Credits blockchain via the
  baba-credits MCP server — sending CS transfers, deploying/calling Java
  smart contracts, querying balances, transactions, tokens, attaching
  userFields metadata (ArtVerse-style), or running node diagnostics.
  Triggers when the user mentions: Credits, CS coin, $CS, baba-credits,
  Credits wallet, BABA Wallet, smart contract on Credits, ArtVerse mint.
---

# baba-credits

## TL;DR

You are talking to a Python MCP server (`baba-credits`) that wraps the BABA Wallet
HTTP gateway, which in turn talks Thrift to a Credits node. The server is
**non-custodial**: it never holds private keys. All write operations require the
client (you, or the wallet you're embedded in) to produce an ed25519 signature
and submit it to the server.

The canonical pipeline for any write is:

    1. *_pack         → returns base58 transactionPackagedStr (and innerId)
    2. (client-side)  → ed25519 sign of the raw bytes of that base58 blob
    3. *_execute      → submit signed payload + same params + same innerId
    4. (optional)     → monitor_wait_for_block / transaction_get_info

For read-only inspection just call the corresponding `*_get_*`, `*_info`,
`*_state`, or `diag_*` tool directly.

## Decision tree — which tool do I use?

- "How much CS does wallet X hold?" → `monitor_get_balance`
- "What did wallet X do recently?" → `monitor_get_transactions_by_wallet`
- "What is transaction 174575023.1?" → `transaction_get_info`
- "Did my smart-contract call succeed?" → `transaction_result`
- "Send N CS from A to B" → recipe `transfer-cs.md`
- "Deploy this Java contract" → recipe `deploy-contract.md`
- "Call method `x` on contract C" → recipe `execute-method.md`
- "Mint an ArtVerse asset" → recipe `attach-metadata.md` + `transfer-cs.md`
- "Show me details of the network" → `diag_*`
- "Wait until the next block" → `monitor_wait_for_block` (long-poll)

## Critical constraints (read before writing)

These come from on-chain validation in 2026-04-27/28 and are NOT optional:

1. **Fix `transactionInnerId` between Pack and Execute.** `*_pack` derives
   inner_id from `lastTransactionId+1`. If a parallel transaction on the same
   wallet bumps that counter between your Pack and your Execute, the rebuilt
   inner_id at submit time differs and the node rejects with `"Transaction has
   wrong signature."` — pre-broadcast (no fee consumed). Fix: read
   `transactionInnerId` from the Pack response and pass it back to
   `*_deploy/_execute`.

2. **Java smart contracts MUST import the SCAPI explicitly.** The first line
   of source must include `import com.credits.scapi.v0.SmartContract;`. Without
   it the executor compiles silently to broken bytecode.

3. **Deploy address is deterministic.** It is `blake2s(source ‖ inner_id_LE6 ‖
   concat(byteCode))`. The Pack response includes `deployedAddress` so you
   don't need to recompute it client-side; but if you do, the formula above is
   the exact one used by the node.

4. **Compile is slow.** Up to ~120s under load. Do not timeout aggressively.

5. **`transaction_execute` rejected with "wrong signature" does NOT consume
   fee.** This is a safety feature of the node. It also means the agent
   should NOT retry blindly — re-pack, re-sign, re-submit instead.

## Tools — quick reference

See `tools-reference.md` for the full catalog (29 tools, 6 categories).

| Category | Count | Notable |
|---|---|---|
| `monitor_*` | 6 | balance, history, fee estimation, long-poll waits |
| `transaction_*` | 4 | get/pack/execute/result for plain CS transfers |
| `userfields_*` | 2 | encode/decode of v1 metadata blobs (ArtVerse) |
| `tokens_*` | 5 | balances, transfers, info, holders, transactions |
| `smartcontract_*` | 8 | compile, pack, deploy, execute, get, methods, state, list |
| `diag_*` | 4 | active nodes, mempool count, node info, supply |

## Recipes (full pipelines)

- `recipes/transfer-cs.md` — send CS from A to B
- `recipes/deploy-contract.md` — Java contract on-chain
- `recipes/execute-method.md` — call a method on a deployed contract
- `recipes/inspect-wallet.md` — read-only exploration
- `recipes/attach-metadata.md` — userFields v1 (ArtVerse minting)
- `recipes/token-operations.md` — token info / balances / transfers / holders

## Client-side signing

The MCP server NEVER signs. You sign client-side. See:

- `signing/python-pynacl.md` — 5 lines of Python (validated on-chain 2026-04-27)
- `signing/typescript-tweetnacl.md` — equivalent for JS/TS wallets

If you are an "agent with a key" the private key is in your env (`BABA_PRIVATE_KEY`).
If you are embedded in a smart wallet, the wallet keystore signs without exposing the key.

## Errors — what they mean and what to do

| Code | Meaning | Action |
|---|---|---|
| `invalid_input` | Schema mismatch (e.g. malformed transactionId) | Do NOT retry. Fix the input. |
| `not_found` | Tx/contract does not exist | Stop searching. |
| `node_unavailable` | Credits node offline (HTTP 503) | Retry with backoff (1s/2s/4s). |
| `node_error` | Semantic error from node (e.g. wrong signature) | Do NOT blind-retry. Re-pack, re-sign. |
| `rate_limited` | Gateway rate limit hit | Wait `Retry-After` then retry. |
| `internal` | Unexpected gateway error | Surface to the user; collect details. |

## When NOT to use this skill

- The MCP server `baba-credits` is not connected in the current session.
- The user asks for a custodial action ("create me a wallet", "store my keys").
  We do NOT generate or store private keys. Direct them to the BABA Wallet app.
- The user asks about a different blockchain (Ethereum, Solana, etc.).

## Troubleshooting

See `troubleshooting.md` for the mapping of common error messages to causes
and fixes (covers the 12 schema/runtime bugs already fixed in the codebase).
```

- [ ] **Step 2: Validate frontmatter (no extra deps)**

```bash
python3 - <<'PY'
import pathlib
text = pathlib.Path('.claude/skills/baba-credits/SKILL.md').read_text()
parts = text.split('---', 2)
assert len(parts) >= 3, "missing closing --- of frontmatter"
fm_text = parts[1]
# basic sanity checks (no YAML dependency)
assert 'name: baba-credits' in fm_text
assert 'description: |' in fm_text
desc_block = fm_text.split('description: |', 1)[1]
desc = '\n'.join(line.strip() for line in desc_block.splitlines() if line.strip())
assert len(desc) < 1024, f"description too long: {len(desc)}"
print("OK frontmatter, description length =", len(desc))
PY
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/baba-credits/SKILL.md
git commit -m "docs(skill): SKILL.md entry point for baba-credits"
```

---

### Task 39: `tools-reference.md`

**Files:**
- Create: `.claude/skills/baba-credits/tools-reference.md`

- [ ] **Step 1: Crea il catalogo dei 29 tools**

Layout per categoria. Ogni tool ha questa struttura:

```markdown
### `<tool_name>`
**Endpoint:** `POST /api/<path>`  **Annotations:** read-only / destructive / idempotent

**Input:**
| field | type | required | notes |
|---|---|---|---|
| `PublicKey` | string (base58) | yes | wallet address |
| ... | | | |

**Output (sample):**
\`\`\`json
{ "balance": "10.0", "success": true, "message": null }
\`\`\`

**When to use:** ...
```

Compila tutti i 29 tools con i campi esatti dal corrispondente `payloads/*.json` del repo (riusabile come `examples`). Per ogni tool, mantieni almeno: nome, endpoint REST, annotations, tabella input minima (campi richiesti), 1 sample output JSON, 1 frase "When to use".

L'engineer per essere veloce può scrivere uno script una tantum:

```python
# scripts/gen_tools_reference.py (one-shot, NO commit)
# Legge baba_mcp/tools/*.py + payloads/*.json e genera le sezioni del file.
# Ma poiché lo schema input/output è già nei moduli, è sufficiente fare un dump
# e refining manuale.
```

(Lo script è opzionale; preferibile compilare a mano per controllare la qualità.)

- [ ] **Step 2: Verifica che tutti i 29 nomi compaiano**

```bash
for t in monitor_get_balance monitor_get_wallet_info \
  monitor_get_transactions_by_wallet monitor_get_estimated_fee \
  monitor_wait_for_block monitor_wait_for_smart_transaction \
  transaction_get_info transaction_pack transaction_execute transaction_result \
  userfields_encode userfields_decode \
  tokens_balances_get tokens_transfers_get tokens_info tokens_holders_get tokens_transactions_get \
  smartcontract_compile smartcontract_pack smartcontract_deploy smartcontract_execute \
  smartcontract_get smartcontract_methods smartcontract_state smartcontract_list_by_wallet \
  diag_get_active_nodes diag_get_active_transactions_count diag_get_node_info diag_get_supply ; do
  grep -q "^### \`$t\`" .claude/skills/baba-credits/tools-reference.md || echo "MISSING: $t"
done
```
Expected: nessun "MISSING".

- [ ] **Step 3: Commit `docs(skill): tools-reference catalogue`**

---

### Task 40: Recipe `transfer-cs.md`

**Files:**
- Create: `.claude/skills/baba-credits/recipes/transfer-cs.md`

- [ ] **Step 1: Scrivi la recipe completa**

```markdown
# Recipe: send CS from wallet A to wallet B

## When to use
The user asks "send N CS to <address>", "transfer CS", "pay <wallet>",
and you (the agent) have access to A's private key (or to a wallet keystore
that can sign on A's behalf).

## Prerequisites
- `BABA_PRIVATE_KEY` available, OR the embedding wallet can sign for A.
- `monitor_get_balance({"PublicKey": A})` returns balance ≥ N + estimated fee.

## Pipeline

### Step 1 — Estimate the fee
\`\`\`
monitor_get_estimated_fee({"transactionSize": 9})
→ { "fee": 0.00874, "success": true }
\`\`\`

### Step 2 — Verify balance
\`\`\`
monitor_get_balance({"PublicKey": A})
→ { "balance": "10.0", "success": true }
\`\`\`
If balance < N + fee: ABORT, tell the user.

### Step 3 — Pack the transaction
\`\`\`
transaction_pack({
    "PublicKey": A,
    "ReceiverPublicKey": B,
    "amountAsString": "0.001",
    "feeAsString": "0",
    "UserData": ""
})
→ { "dataResponse": {
        "transactionPackagedStr": "<base58>",
        "recommendedFee": 0.00874
    }, "success": true }
\`\`\`
*Capture the `transactionPackagedStr` for step 4.*

### Step 4 — Sign client-side
See `signing/python-pynacl.md`:
\`\`\`python
sig_b58 = sign_packaged(packaged_str_b58, private_key_b58)
\`\`\`

### Step 5 — Submit
\`\`\`
transaction_execute({
    "PublicKey": A,
    "ReceiverPublicKey": B,
    "amountAsString": "0.001",
    "feeAsString": "0",
    "UserData": "",
    "TransactionSignature": sig_b58
})
→ { "success": true, "transactionId": "174575023.1", "actualFee": "0.00874" }
\`\`\`

### Step 6 — Confirm (optional)
\`\`\`
monitor_wait_for_block({"timeoutMs": 30000})
transaction_get_info({"transactionId": "174575023.1"})
→ { "found": true, "status": "Success" }
\`\`\`

## Common errors
- `"Missing Data"` — `PublicKey` or `TransactionSignature` is empty.
- `"Transaction has wrong signature."` — same `Amount`/`Fee`/`UserData` MUST
  be passed both to Pack and to Execute. If they differ, the inner_id derivation
  changes and the signature no longer matches.
- `node_unavailable` (503) — retry with backoff 1s/2s/4s.

## On-chain confirmation
A transaction is final after ~3 seconds (one pool seal). For UI feedback you
can either long-poll `monitor_wait_for_block` or short-poll `transaction_get_info`
every 2 seconds for up to 30 seconds.
```

- [ ] **Step 2: Commit `docs(skill): recipe transfer-cs`.**

---

### Task 41: Recipe `deploy-contract.md`

**Files:** `.claude/skills/baba-credits/recipes/deploy-contract.md`

- [ ] **Step 1: Scrivi la recipe** con la pipeline `Compile → Pack(deploy) → sign → Deploy → Wait`. Includi codice Java esempio (BasicCounter) con l'import obbligatorio e mostra come catturare `transactionInnerId` dalla response di Pack per ripassarlo a Deploy. Incolla i payload da `payloads/smartcontract/Compile.json`, `Pack.json`, `Deploy.json` come riferimento.

- [ ] **Step 2: Commit `docs(skill): recipe deploy-contract`.**

---

### Task 42: Recipe `execute-method.md`

**Files:** `.claude/skills/baba-credits/recipes/execute-method.md`

- [ ] **Step 1: Scrivi la recipe** con pipeline `Methods (discovery) → Pack(execute) → sign → Execute → Result`. Spiega Variant params (riferimento `services/monitor.py:_variant_to_python`), gestione di `transactionInnerId` (stesso vincolo del deploy), e come decodificare la `returnValue` dal `transaction_result`.

- [ ] **Step 2: Commit.**

---

### Task 43: Recipe `inspect-wallet.md`

**Files:** `.claude/skills/baba-credits/recipes/inspect-wallet.md`

- [ ] **Step 1: Scrivi la recipe read-only** che combina `monitor_get_wallet_info` + `monitor_get_transactions_by_wallet` (paginato) + `tokens_balances_get` per dare all'agente una "fotografia" completa di un wallet senza scrivere on-chain. Esempio output sintetizzato per l'utente finale.

- [ ] **Step 2: Commit.**

---

### Task 44: Recipe `attach-metadata.md`

**Files:** `.claude/skills/baba-credits/recipes/attach-metadata.md`

- [ ] **Step 1: Scrivi la recipe userFields v1** per il caso ArtVerse: dato un asset (file image/video con hash sha-256, IPFS CID, mime, sizeBytes), come usare `userfields_encode` per produrre il blob base58 e poi passarlo come `UserData` a `transaction_pack`. Includi esempio numerico copiato da `payloads/userfields/Encode.json`.

- [ ] **Step 2: Commit.**

---

### Task 45: Recipe `token-operations.md`

**Files:** `.claude/skills/baba-credits/recipes/token-operations.md`

- [ ] **Step 1: Scrivi la recipe** che mostra:
  - lookup metadata token: `tokens_info`
  - balance multi-token wallet: `tokens_balances_get`
  - history di un token specifico: `tokens_transfers_get`
  - top holders: `tokens_holders_get` con `order=0,desc=true`
  - storia tx contratto: `tokens_transactions_get`
- Sottolinea che mandare token (transfer) richiede `smartcontract_execute` con `method="transfer"` (i token Credits sono smart contracts).

- [ ] **Step 2: Commit.**

---

### Task 46: Signing — `python-pynacl.md`

**Files:** `.claude/skills/baba-credits/signing/python-pynacl.md`

- [ ] **Step 1: Scrivi**

```markdown
# Sign a packaged transaction with Python (PyNaCl)

Validated on-chain 2026-04-27 with 3 mainnet transfers (e.g. tx 174575023.1).

## Install
\`\`\`bash
pip install pynacl base58
\`\`\`

## Code (5 lines)
\`\`\`python
import base58, nacl.signing

def sign_packaged(transaction_packaged_str_b58: str, private_key_b58: str) -> str:
    raw = base58.b58decode(transaction_packaged_str_b58)
    sk  = nacl.signing.SigningKey(base58.b58decode(private_key_b58)[:32])
    sig = sk.sign(raw).signature           # 64 bytes
    return base58.b58encode(sig).decode()
\`\`\`

## Notes
- The Credits private key is 64 bytes base58: first 32 = seed (used by ed25519),
  last 32 = derived public key. PyNaCl's `SigningKey` expects only the seed.
- The signature is over the **raw bytes** of the packaged blob, NOT over the
  base58 string. Decode first, then sign.
- Output is a 64-byte signature, base58-encoded — ready for `TransactionSignature`.

## Where to keep the private key
- An "agent with a key" reads it from `BABA_PRIVATE_KEY` env var.
- A wallet with embedded AI uses its own keystore (Keychain, Android Keystore,
  hardware wallet). The keystore exposes a `sign(bytes) -> bytes` API; use that
  in place of `nacl.signing.SigningKey`.
- NEVER pass the private key to any MCP tool or to the gateway.
```

- [ ] **Step 2: Commit `docs(skill): signing python pynacl snippet`.**

---

### Task 47: Signing — `typescript-tweetnacl.md`

**Files:** `.claude/skills/baba-credits/signing/typescript-tweetnacl.md`

- [ ] **Step 1: Scrivi**

```markdown
# Sign a packaged transaction with TypeScript (tweetnacl)

For wallet apps (mobile/web) embedded with an AI agent.

## Install
\`\`\`bash
npm install tweetnacl bs58
\`\`\`

## Code
\`\`\`typescript
import nacl from "tweetnacl";
import bs58 from "bs58";

export function signPackaged(
  transactionPackagedStrB58: string,
  privateKeyB58: string,
): string {
  const raw = bs58.decode(transactionPackagedStrB58);
  const sk  = bs58.decode(privateKeyB58);   // 64 bytes (seed||pub)
  const sig = nacl.sign.detached(raw, sk);  // 64 bytes
  return bs58.encode(sig);
}
\`\`\`

## Notes
- `nacl.sign.detached` expects the full 64-byte private key (seed||pub),
  unlike PyNaCl which wants the 32-byte seed only.
- For wallets with hardware-backed keystores (iOS Secure Enclave, Android
  StrongBox), replace `nacl.sign.detached` with the platform's `sign(bytes)`
  primitive — same input/output contract.
```

- [ ] **Step 2: Commit.**

---

### Task 48: `troubleshooting.md`

**Files:** `.claude/skills/baba-credits/troubleshooting.md`

- [ ] **Step 1: Scrivi la mappa errori → causa → fix**

Includi:

- `"Transaction has wrong signature."` → `transactionInnerId` cambiato fra Pack e Execute, oppure parametri Amount/Fee/UserData diversi fra le due chiamate, oppure firma fatta sulla stringa base58 invece che sui suoi bytes decodificati. Fix: ricomincia dal Pack.
- `"Missing Data"` → manca `PublicKey` o `TransactionSignature` nell'input di Execute.
- `"Empty Body"` → corpo JSON vuoto. Probabilmente l'agente ha mandato un payload mal formato.
- `"Node Unavailable"` (503) → nodo Credits offline. Retry con backoff.
- `"Failed to retrieve wallet data"` (400) → public key non base58 valida.
- `node_error` su SmartContract Deploy con executor che dice "compilation error" → dimentica `import com.credits.scapi.v0.SmartContract;` nel sourceCode.
- `AttributeError` o errore Thrift schema → assicurati di essere a HEAD del fork; il branch ha già fixato 12 bug runtime (vedi `docs/FOLLOW_UP.md`).

- [ ] **Step 2: Commit `docs(skill): troubleshooting map`.**

---

## Phase 4 — Deployment

### Task 49: `ecosystem.config.js`

**Files:** Create `ecosystem.config.js`.

- [ ] **Step 1: Scrivi il file**

```javascript
module.exports = {
  apps: [
    {
      name: "baba-node-api",
      script: "gateway.py",
      interpreter: "python3",
      cwd: __dirname,
      max_memory_restart: "512M",
      autorestart: true,
    },
    {
      name: "baba-mcp-http",
      script: "-m",
      args: "baba_mcp.server",
      interpreter: "python3",
      cwd: __dirname,
      env: {
        MCP_TRANSPORT: "http",
        MCP_HTTP_HOST: "127.0.0.1",
        MCP_HTTP_PORT: "7000",
        BABA_GATEWAY_URL: "http://127.0.0.1:5000",
      },
      max_memory_restart: "256M",
      autorestart: true,
    },
  ],
};
```

- [ ] **Step 2: Verifica sintassi**

```bash
node -c ecosystem.config.js  # solo controllo sintassi
# In alternativa, se node non è installato: pm2 ecosystem (genera template) oppure salta
```

- [ ] **Step 3: Commit `feat(deploy): pm2 ecosystem bundles gateway + mcp-http`.**

---

### Task 50: `.env.mcp.example`

**Files:** Create `.env.mcp.example`.

- [ ] **Step 1: Scrivi**

```dotenv
# baba-credits MCP server configuration (optional file; envs can also live in pm2 ecosystem)

# Where the gateway listens (must be reachable from this MCP process)
BABA_GATEWAY_URL=http://127.0.0.1:5000

# stdio (default, for Claude Code spawn) | http (SSE, for remote agents / pm2)
MCP_TRANSPORT=stdio

# Used only when MCP_TRANSPORT=http
MCP_HTTP_HOST=127.0.0.1
MCP_HTTP_PORT=7000

# Compile/Deploy can take >30s under executor load
MCP_REQUEST_TIMEOUT_MS=120000

# info | debug | warning | error
MCP_LOG_LEVEL=info

# Default currency code for tools that omit it (1 = CS)
MCP_DEFAULT_CURRENCY=1

# Bearer token required when MCP_TRANSPORT=http and exposed beyond localhost.
# Leave empty for stdio or strict-localhost setups.
MCP_AUTH_TOKEN=

# Comma-separated IP allow-list for HTTP transport
MCP_WHITELIST_IPS=127.0.0.1

# Cap concurrent MCP calls per connection (anti-abuse on long-poll waits)
MCP_MAX_CONCURRENT_CALLS=10
```

- [ ] **Step 2: Commit `feat(deploy): .env.mcp.example`.**

---

### Task 51: README — sezione "MCP Server"

**Files:** Modify `README.md`.

- [ ] **Step 1: Aggiungi una nuova sezione**

Dopo la sezione `## 📡 API Endpoints`, prima di `## 📄 License`, inserisci:

```markdown
---

## 🤖 MCP Server (`baba-credits`)

The gateway is also exposed as a **Model Context Protocol** server so AI agents
(Claude Code/Desktop, smart wallets with embedded AI, custom agents) can
operate on the Credits blockchain using structured tools.

The MCP server is a thin Python wrapper sitting on top of this gateway. It is
**non-custodial**: it never holds private keys. The signing pipeline is
`Pack → ed25519 sign (client-side) → Execute → Wait`.

### Quick start (bundled with the gateway via pm2)

\`\`\`bash
pip3 install -r requirements.txt
pm2 start ecosystem.config.js && pm2 save
# Now both:
#   gateway        on :5000 (HTTP REST)
#   baba-mcp-http  on :7000 (MCP SSE)
\`\`\`

### Local stdio (Claude Code)

Add a `.mcp.json` at the repo root:

\`\`\`json
{
  "mcpServers": {
    "baba-credits": {
      "command": "python3",
      "args": ["-m", "baba_mcp.server"],
      "cwd": "/home/credits/baba-node-api",
      "env": { "BABA_GATEWAY_URL": "http://127.0.0.1:5000" }
    }
  }
}
\`\`\`

### Tools

29 tools total, mapping 1:1 to the REST endpoints. See the skill at
`.claude/skills/baba-credits/` for the full catalog and recipes
(transfer, deploy, execute, inspect, attach metadata, token operations).

### Example end-to-end transfer (CS, 0.001 from A → B)

\`\`\`text
1. agent → transaction_pack    → returns transactionPackagedStr (base58)
2. agent → (sign client-side)  → 64-byte ed25519 signature
3. agent → transaction_execute → transactionId "174575023.1"
4. agent → monitor_wait_for_block → block sealed
\`\`\`

### Security notes

- The MCP server NEVER signs server-side (vincolo non-custodial). If you need a
  signer microservice, run a separate companion MCP — do NOT add signing here.
- When `MCP_TRANSPORT=http` and exposed beyond localhost, set `MCP_AUTH_TOKEN`
  and front the SSE port with Nginx + TLS (see `.env.mcp.example`).
```

- [ ] **Step 2: Commit `docs(readme): add MCP Server section`.**

---

## Phase 5 — Test, drift validation, CI

### Task 52: Drift validation skill ↔ codice

**Files:**
- Create: `tests/test_skill_drift.py`

- [ ] **Step 1: Test**

```python
"""Catch drift between the skill catalogue and the actual MCP server tools.

No external YAML parser required — the frontmatter is trivial enough to
sanity-check with string operations.
"""
from __future__ import annotations
import re, asyncio, pathlib

from baba_mcp.server import build_server, load_config

SKILL_DIR = pathlib.Path(".claude/skills/baba-credits")


def _registered_tool_names() -> set[str]:
    cfg = load_config()
    server = build_server(cfg)
    handlers = server._list_tools_handlers  # type: ignore[attr-defined]
    names: list[str] = []
    for h in handlers:
        names.extend(t.name for t in asyncio.run(h()))
    return set(names)


def test_tools_reference_lists_every_tool():
    text = (SKILL_DIR / "tools-reference.md").read_text()
    documented = set(re.findall(r"^### `([a-z_]+)`", text, flags=re.M))
    registered = _registered_tool_names()
    assert registered == documented, {
        "missing_in_skill": sorted(registered - documented),
        "obsolete_in_skill": sorted(documented - registered),
    }


def test_skill_md_frontmatter_valid():
    text = (SKILL_DIR / "SKILL.md").read_text()
    parts = text.split("---", 2)
    assert len(parts) >= 3, "missing closing --- of frontmatter"
    fm_text = parts[1]
    assert "name: baba-credits" in fm_text
    assert "description: |" in fm_text
    desc_block = fm_text.split("description: |", 1)[1]
    desc = "\n".join(line.strip() for line in desc_block.splitlines() if line.strip())
    assert len(desc) < 1024, f"description too long: {len(desc)}"


def test_recipe_files_present():
    expected = {
        "transfer-cs.md", "deploy-contract.md", "execute-method.md",
        "inspect-wallet.md", "attach-metadata.md", "token-operations.md",
    }
    actual = {p.name for p in (SKILL_DIR / "recipes").iterdir()}
    assert expected <= actual


def test_signing_files_present():
    expected = {"python-pynacl.md", "typescript-tweetnacl.md"}
    actual = {p.name for p in (SKILL_DIR / "signing").iterdir()}
    assert expected <= actual
```

- [ ] **Step 2: Run, verify pass**

```bash
pytest tests/test_skill_drift.py -v
```
Expected: 4 PASSED. Se `tools-reference.md` ha typo nei nomi tool, il test fallisce e indica esattamente quali. Fix inline e ri-esegui.

- [ ] **Step 3: Commit `test(mcp): drift skill <-> code`.**

---

### Task 53: Estendi CI

**Files:** Modify `.github/workflows/ci.yml`.

- [ ] **Step 1: Aggiungi step**

```yaml
      - name: Lint MCP package
        run: python -m compileall baba_mcp/

      - name: MCP unit tests
        run: pytest tests/test_mcp_*.py tests/test_skill_drift.py -v
```

- [ ] **Step 2: Verifica che tutti i test girino in locale prima di pushare**

```bash
pytest tests/ -v
```
Expected: 55 originali + nuovi (≥ 70 totali) tutti verdi.

- [ ] **Step 3: Commit `ci: run MCP tests + skill drift check`.**

---

### Task 54: Smoke on-chain manuale

**Files:**
- Create: `scripts/mcp_onchain_smoke.py`

- [ ] **Step 1: Scrivi lo script**

```python
"""Manual end-to-end smoke test of the baba-credits MCP server against a real
Credits node. Not run in CI. Requires:

  - the node reachable via the gateway (default http://127.0.0.1:5000)
  - an env var BABA_PRIVATE_KEY (base58, 64 bytes) of a funded wallet
  - the corresponding env var BABA_PUBLIC_KEY (base58)

Usage:
    BABA_PRIVATE_KEY=... BABA_PUBLIC_KEY=... \\
    BABA_RECEIVER=...                          \\
    python3 scripts/mcp_onchain_smoke.py
"""
from __future__ import annotations
import os, asyncio, json, base58
import nacl.signing
from baba_mcp.server import load_config, build_server

PK   = os.environ["BABA_PUBLIC_KEY"]
SK   = os.environ["BABA_PRIVATE_KEY"]
RCV  = os.environ["BABA_RECEIVER"]


def sign_packaged(b58: str) -> str:
    raw = base58.b58decode(b58)
    sk  = nacl.signing.SigningKey(base58.b58decode(SK)[:32])
    return base58.b58encode(sk.sign(raw).signature).decode()


async def call(server, name: str, args: dict):
    handlers = server._call_tool_handlers  # type: ignore[attr-defined]
    last_err = None
    for h in handlers:
        try:
            res = await h(name, args)
            return json.loads(res[0].text)
        except ValueError as e:
            last_err = e
    raise last_err  # tool not found in any registrar


async def main():
    cfg = load_config()
    server = build_server(cfg)

    # Read-only checks
    bal = await call(server, "monitor_get_balance", {"PublicKey": PK})
    print("balance:", bal["balance"])
    supply = await call(server, "diag_get_supply", {})
    print("supply:", supply)

    # Transfer 0.001 CS PK → RCV
    pack = await call(server, "transaction_pack", {
        "PublicKey": PK, "ReceiverPublicKey": RCV,
        "amountAsString": "0.001", "feeAsString": "0", "UserData": "",
    })
    pkg = pack["dataResponse"]["transactionPackagedStr"]
    print("pack ok, recommendedFee:", pack["dataResponse"]["recommendedFee"])

    sig = sign_packaged(pkg)
    exe = await call(server, "transaction_execute", {
        "PublicKey": PK, "ReceiverPublicKey": RCV,
        "amountAsString": "0.001", "feeAsString": "0", "UserData": "",
        "TransactionSignature": sig,
    })
    print("execute:", exe.get("transactionId"), exe.get("success"))
    assert exe["success"], exe.get("messageError")

    # Confirmation
    info = await call(server, "transaction_get_info",
                      {"transactionId": exe["transactionId"]})
    print("status:", info.get("status"))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Aggiungi `MANUAL_QA.md`**

`scripts/MANUAL_QA.md`:

```markdown
# baba-credits MCP — Manual QA checklist

Run before tagging a release.

1. `pytest -v` → all green.
2. `python3 -m baba_mcp.server` (stdio) handshake con `mcp-inspector`:
   - `npx @modelcontextprotocol/inspector python3 -m baba_mcp.server`
   - Verifica che `list_tools` ritorni 29 tools con annotations corrette.
3. `pm2 start ecosystem.config.js && pm2 logs baba-mcp-http` — entrambi up,
   no error logs nei primi 30s.
4. Smoke on-chain (richiede wallet funded sul nodo configurato):
   ```
   BABA_PUBLIC_KEY=... BABA_PRIVATE_KEY=... BABA_RECEIVER=... \
       python3 scripts/mcp_onchain_smoke.py
   ```
   Verifica: transfer 0.001 CS sealed in `<10s` con `status="Success"`.
```

- [ ] **Step 3: Commit `chore(qa): mcp on-chain smoke + manual checklist`.**

---

## Self-Review checklist (per l'engineer dopo aver completato il piano)

- Tutti i 29 tools esistono in `baba_mcp/tools/*.py` con dispatch dict + tool def + test unit.
- `tests/test_mcp_full_listing.py` passa (asserzione 29 tools).
- `tests/test_skill_drift.py` passa (no drift skill ↔ codice).
- CI estesa, verde.
- README aggiornato con sezione MCP.
- `ecosystem.config.js` + `.env.mcp.example` committati.
- Skill completa: SKILL + tools-reference + 6 recipes + 2 signing + troubleshooting.
- Smoke on-chain manuale eseguito con successo (almeno una volta) — annota la `transactionId` su un file di QA log o CHANGELOG.
