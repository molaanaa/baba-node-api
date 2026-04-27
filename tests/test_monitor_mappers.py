from types import SimpleNamespace as NS

from services import monitor as m


def _ok():
    return NS(code=0, message="")


def _err(msg):
    return NS(code=1, message=msg)


def test_map_block_response_success():
    res = NS(status=_ok(), poolNumber=42, transactions=[NS(), NS(), NS()])
    out = m.map_block_response(res, pool_number=42)
    assert out == {"success": True, "message": None, "poolSeq": 42, "transactionCount": 3}


def test_map_block_response_falls_back_to_input_pool_number():
    res = NS(status=_ok(), transactions=[])
    out = m.map_block_response(res, pool_number=7)
    assert out["poolSeq"] == 7
    assert out["transactionCount"] == 0


def test_map_block_response_propagates_node_error():
    res = NS(status=_err("backend timeout"), transactions=None)
    out = m.map_block_response(res, pool_number=1)
    assert out["success"] is False
    assert out["message"] == "backend timeout"


def test_map_smart_tx_response_formats_tx_id():
    res = NS(status=_ok(), id=NS(poolSeq=100, index=2))
    out = m.map_smart_tx_response(res)
    assert out == {"success": True, "message": None, "transactionId": "100.3"}


def test_map_smart_tx_response_handles_missing_id():
    res = NS(status=_ok(), id=None)
    out = m.map_smart_tx_response(res)
    assert out["transactionId"] is None


def test_map_tx_result_extracts_variant_string():
    res = NS(status=_ok(), found=True, ret_val=NS(v_string="hello"))
    out = m.map_tx_result(res)
    assert out["success"] is True
    assert out["result"] == "hello"
    assert out["found"] is True


def test_map_tx_result_extracts_variant_int():
    res = NS(status=_ok(), found=True, ret_val=NS(v_int=42))
    assert m.map_tx_result(res)["result"] == 42


def test_map_tx_result_extracts_variant_array():
    res = NS(
        status=_ok(),
        found=True,
        ret_val=NS(v_array=[NS(v_int=1), NS(v_string="x")]),
    )
    assert m.map_tx_result(res)["result"] == [1, "x"]


def test_map_tx_result_when_node_says_not_found():
    res = NS(status=_err("not found"), found=False, ret_val=None)
    out = m.map_tx_result(res)
    assert out["success"] is False
    assert out["found"] is False
    assert out["message"] == "not found"
    assert out["result"] is None
