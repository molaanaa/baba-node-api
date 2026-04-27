from types import SimpleNamespace as NS

import base58

from services import diag


OK = NS(code=0, message="")
ERR = NS(code=1, message="diag boom")
KEY = b"\xab" * 32
KEY_B58 = base58.b58encode(KEY).decode()


def test_map_active_nodes_success():
    res = NS(
        status=OK,
        count=2,
        nodes=[
            NS(key=KEY, version="5.0.1", ip="192.0.2.10", lastBlock=1234, trustLevel=3),
            NS(publicKey=KEY, version="5.0.0", ip="10.0.0.2", round=1233, trustLevel=2),
        ],
    )
    out = diag.map_active_nodes(res)
    assert out["success"] is True
    assert out["count"] == 2
    assert out["nodes"][0]["key"] == KEY_B58
    assert out["nodes"][0]["ip"] == "192.0.2.10"
    assert out["nodes"][1]["lastBlock"] == 1233


def test_map_active_nodes_count_falls_back_to_list():
    out = diag.map_active_nodes(NS(status=OK, nodes=[NS(), NS(), NS()]))
    assert out["count"] == 3


def test_map_active_nodes_propagates_error():
    out = diag.map_active_nodes(NS(status=ERR, nodes=None))
    assert out["success"] is False
    assert out["message"] == "diag boom"
    assert out["nodes"] == []


def test_map_active_transactions_count():
    out = diag.map_active_transactions_count(NS(status=OK, count=42))
    assert out == {"success": True, "message": None, "count": 42}


def test_map_node_info():
    info = NS(
        version="5.0.1",
        publicKey=KEY,
        ip="192.0.2.10",
        lastBlock=99999,
        uptimeSeconds=12345,
        trustLevel=4,
    )
    out = diag.map_node_info(NS(status=OK, info=info))
    assert out["success"] is True
    assert out["info"]["publicKey"] == KEY_B58
    assert out["info"]["ip"] == "192.0.2.10"
    assert out["info"]["uptimeSeconds"] == 12345


def test_map_supply_amounts():
    res = NS(
        status=OK,
        initial=NS(integral=250_000_000, fraction=0),
        mined=NS(integral=10_000_000, fraction=500_000_000_000_000_000),
        currentSupply=NS(integral=260_000_000, fraction=500_000_000_000_000_000),
    )
    out = diag.map_supply(res)
    assert out["success"] is True
    assert out["initial"] == "250000000.000000000000000000"
    assert out["mined"] == "10000000.500000000000000000"
    assert out["currentSupply"] == "260000000.500000000000000000"
