"""AST-level smoke test: the gateway must register every planned route under
both ``/<path>`` and ``/api/<path>``. Importing gateway.py is avoided here
because gevent/thrift/redis are runtime-only dependencies.
"""

import ast
import os
from pathlib import Path

GATEWAY = Path(__file__).resolve().parent.parent / "gateway.py"

EXPECTED_ROUTES = {
    # Section 3 - wait helpers / long-poll
    "/Monitor/WaitForBlock",
    "/Monitor/WaitForSmartTransaction",
    "/Transaction/Result",
    # Section 4 - userFields v1
    "/UserFields/Encode",
    "/UserFields/Decode",
}


def _routes_in_gateway() -> set[str]:
    tree = ast.parse(GATEWAY.read_text())
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


def test_userfields_routes_registered_dual():
    routes = _routes_in_gateway()
    for r in EXPECTED_ROUTES:
        assert r in routes, f"missing bare route {r}"
        assert f"/api{r}" in routes, f"missing /api-prefixed route /api{r}"


def test_node_ip_default_points_to_managed_node():
    env_example = (Path(GATEWAY).parent / ".env.example").read_text()
    assert "NODE_IP=38.242.234.47" in env_example
