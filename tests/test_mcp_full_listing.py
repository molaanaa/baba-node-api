"""Sanity check globale: il server registra esattamente 29 tools.

Nota tecnica: la `Server` del SDK MCP installato memorizza un solo handler per
`ListToolsRequest` (sovrascritto a ogni `@server.list_tools()`). Per enumerare
le tool definitions di TUTTI i moduli registrati, intercettiamo il decorator
`Server.list_tools` durante `build_server()` e collezioniamo ogni callback.
"""
import asyncio
from baba_mcp.server import build_server, load_config
from mcp.server import Server


def test_server_lists_all_29_tools(monkeypatch):
    monkeypatch.delenv("BABA_GATEWAY_URL", raising=False)

    captured: list = []
    orig_list_tools = Server.list_tools

    def patched_list_tools(self):
        decorator = orig_list_tools(self)

        def new_decorator(func):
            captured.append(func)
            return decorator(func)

        return new_decorator

    monkeypatch.setattr(Server, "list_tools", patched_list_tools)

    cfg = load_config()
    server = build_server(cfg)
    assert server is not None  # smoke

    names: list[str] = []
    for handler in captured:
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
