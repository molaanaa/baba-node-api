"""AST-level smoke test: the gateway must register every planned route under
both ``/<path>`` and ``/api/<path>``. Importing gateway.py is avoided here
because gevent/thrift/redis are runtime-only dependencies.

Routes for the new endpoints live in ``routes/*.py`` (Flask Blueprints),
so the scan walks both ``gateway.py`` and every ``routes/*.py`` file.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GATEWAY = PROJECT_ROOT / "gateway.py"
ROUTES_DIR = PROJECT_ROOT / "routes"

EXPECTED_ROUTES = {
    # Section 6 - Diagnostic API (optional)
    "/Diag/GetActiveNodes",
    "/Diag/GetActiveTransactionsCount",
    "/Diag/GetNodeInfo",
    "/Diag/GetSupply",
    # Section 1 - Smart Contract API
    "/SmartContract/Compile",
    "/SmartContract/Deploy",
    "/SmartContract/Execute",
    "/SmartContract/Get",
    "/SmartContract/Methods",
    "/SmartContract/State",
    "/SmartContract/ListByWallet",
    # Section 2 - Token API
    "/Tokens/BalancesGet",
    "/Tokens/TransfersGet",
    "/Tokens/Info",
    "/Tokens/HoldersGet",
    "/Tokens/TransactionsGet",
    # Section 3 - wait helpers / long-poll
    "/Monitor/WaitForBlock",
    "/Monitor/WaitForSmartTransaction",
    "/Transaction/Result",
    # Section 4 - userFields v1
    "/UserFields/Encode",
    "/UserFields/Decode",
}


def _routes_in_file(path: Path) -> set[str]:
    """Collect string literals decorated with @<obj>.route(...) in a module."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            attr = dec.func
            if not (isinstance(attr, ast.Attribute) and attr.attr == "route"):
                continue
            if not dec.args:
                continue
            arg = dec.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value)
    return found


def _routes_in_project() -> set[str]:
    routes = _routes_in_file(GATEWAY)
    if ROUTES_DIR.is_dir():
        for py in sorted(ROUTES_DIR.glob("*.py")):
            if py.name == "__init__.py":
                continue
            routes |= _routes_in_file(py)
    return routes


def test_userfields_routes_registered_dual():
    routes = _routes_in_project()
    for r in EXPECTED_ROUTES:
        assert r in routes, f"missing bare route {r}"
        assert f"/api{r}" in routes, f"missing /api-prefixed route /api{r}"


def test_node_ip_default_in_env_example():
    env_example = (Path(GATEWAY).parent / ".env.example").read_text()
    assert "NODE_IP=127.0.0.1" in env_example
