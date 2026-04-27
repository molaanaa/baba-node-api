from types import SimpleNamespace as NS

from services import monitor as m


def _ok():
    return NS(code=0, message="")


def _err(msg):
    return NS(code=1, message=msg)


def test_map_block_response_returns_new_hash_b58():
    # Real node returns raw bytes (PoolHash typedef). Mapper must base58-encode it.
    import base58
    new = b"\x01" * 32
    obsolete = b"\x02" * 32
    out = m.map_block_response(new, obsolete_hash=obsolete)
    assert out["success"] is True
    assert out["message"] is None
    assert out["hash"] == base58.b58encode(new).decode()
    assert out["obsoleteHash"] == base58.b58encode(obsolete).decode()
    assert out["changed"] is True


def test_map_block_response_changed_false_when_same_hash():
    same = b"\x03" * 32
    out = m.map_block_response(same, obsolete_hash=same)
    assert out["changed"] is False


def test_map_block_response_empty_bytes_is_failure():
    out = m.map_block_response(b"", obsolete_hash=b"\x04" * 32)
    assert out["success"] is False
    assert out["hash"] is None


def test_map_block_response_object_with_hash_attr():
    # Legacy/test fixture: response wrapped in a struct with status + hash.
    import base58
    res = NS(status=_ok(), hash=b"\x05" * 32)
    out = m.map_block_response(res, obsolete_hash=b"")
    assert out["success"] is True
    assert out["hash"] == base58.b58encode(b"\x05" * 32).decode()
    assert out["obsoleteHash"] is None


def test_map_block_response_object_propagates_node_error():
    res = NS(status=_err("backend timeout"), hash=b"")
    out = m.map_block_response(res, obsolete_hash=b"")
    assert out["success"] is False
    assert out["message"] == "backend timeout"
    assert out["hash"] is None


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


def test_map_tx_result_extracts_variant_boolean():
    # Real Thrift Variant uses v_boolean (and v_boolean_box). Older drafts
    # used v_bool; both must round-trip.
    assert m.map_tx_result(NS(status=_ok(), found=True, ret_val=NS(v_boolean=True)))["result"] is True
    assert m.map_tx_result(NS(status=_ok(), found=True, ret_val=NS(v_bool=False)))["result"] is False


def test_map_tx_result_extracts_variant_byte_array():
    payload = b"\x01\x02\x03"
    out = m.map_tx_result(NS(status=_ok(), found=True, ret_val=NS(v_byte_array=payload)))
    import base64
    assert out["result"] == base64.b64encode(payload).decode("ascii")


def test_map_tx_result_extracts_variant_amount():
    amt = NS(integral=12, fraction=345)
    out = m.map_tx_result(NS(status=_ok(), found=True, ret_val=NS(v_amount=amt)))
    assert out["result"] == {"integral": 12, "fraction": 345}
