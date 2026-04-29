"""Sanity check globale: il server registra esattamente 29 tools.

Il fix architetturale (single list_tools/call_tool registration) significa che
il vero handler `request_handlers[ListToolsRequest]` deve restituire TUTTI i 29
tool: lo invochiamo direttamente, come farebbe un client MCP.
"""
import asyncio
import httpx
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListToolsRequest,
)

from baba_mcp.client import GatewayClient
from baba_mcp.server import build_server, load_config


def test_server_lists_all_29_tools(monkeypatch):
    monkeypatch.delenv("BABA_GATEWAY_URL", raising=False)
    cfg = load_config()
    server = build_server(cfg)

    handler = server.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest(method="tools/list")))
    names = {t.name for t in result.root.tools}

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
    assert names == expected
    assert len(names) == 29


def _fake_balance_handler(req):
    return httpx.Response(
        200,
        json={
            "balance": "1.0",
            "tokens": [],
            "delegatedOut": 0,
            "delegatedIn": 0,
            "success": True,
            "message": None,
        },
    )


def _fake_tx_handler(req):
    return httpx.Response(
        200,
        json={
            "id": "1.1",
            "found": True,
            "success": True,
            "message": None,
        },
    )


def test_server_dispatches_tools_from_multiple_modules(monkeypatch):
    """Verifica che il dispatch unico raggiunga tool da moduli diversi.

    Prova un tool del modulo `monitor` e uno del modulo `transaction`: con il
    bug pre-fix uno dei due fallirebbe con `ValueError("Unknown tool: ...")`
    perché solo l'ultimo modulo registrato (diag) era reachable via MCP.
    """
    monkeypatch.delenv("BABA_GATEWAY_URL", raising=False)
    cfg = load_config()
    server = build_server(cfg)

    # Replace gateway client with one using MockTransport (no real HTTP)
    server.gateway = GatewayClient(  # type: ignore[attr-defined]
        base_url="http://gw.test",
        transport=httpx.MockTransport(_fake_balance_handler),
        timeout_ms=2000,
        max_retries=1,
    )

    handler = server.request_handlers[CallToolRequest]

    # Monitor tool
    req_mon = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="monitor_get_balance",
            arguments={"PublicKey": "abc"},
        ),
    )
    result_mon = asyncio.run(handler(req_mon))
    text_mon = result_mon.root.content[0].text
    assert "balance" in text_mon

    # Transaction tool — swap gateway to a tx-shaped fake
    server.gateway = GatewayClient(  # type: ignore[attr-defined]
        base_url="http://gw.test",
        transport=httpx.MockTransport(_fake_tx_handler),
        timeout_ms=2000,
        max_retries=1,
    )
    req_tx = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="transaction_get_info",
            arguments={"transactionId": "1.1"},
        ),
    )
    result_tx = asyncio.run(handler(req_tx))
    text_tx = result_tx.root.content[0].text
    assert "found" in text_tx
