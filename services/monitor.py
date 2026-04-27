"""Mappers for the wait/long-poll endpoints.

These helpers convert the raw Thrift responses returned by the node
(``WaitForBlock``, ``WaitForSmartTransaction``, ``TransactionResultGet``) into
the JSON envelope used by the gateway. They are intentionally defensive on
attribute access — different node versions may add or rename fields — and
contain no network or Thrift dependency, so they can be unit tested in
isolation with ``types.SimpleNamespace`` fixtures.
"""

from __future__ import annotations

from typing import Any, Optional

import base58


def _b58(value: Optional[bytes]) -> Optional[str]:
    if not value:
        return None
    try:
        return base58.b58encode(value).decode("utf-8")
    except Exception:
        return None


def _format_tx_id(tx_id: Any) -> Optional[str]:
    if tx_id is None:
        return None
    pool_seq = getattr(tx_id, "poolSeq", None)
    index = getattr(tx_id, "index", None)
    if pool_seq is None or index is None:
        return None
    return f"{pool_seq}.{int(index) + 1}"


def _status(obj: Any) -> dict:
    status = getattr(obj, "status", None)
    code = getattr(status, "code", 0) if status else 0
    message = getattr(status, "message", "") if status else ""
    return {"code": int(code or 0), "message": message or ""}


def map_block_response(res: Any, pool_number: int) -> dict:
    """Shape the ``WaitForBlock`` response. ``pool_number`` is the request input
    used as a fallback when the node does not echo it back.
    """
    pool_seq = getattr(res, "poolNumber", None)
    if pool_seq is None:
        pool_seq = getattr(res, "poolSeq", pool_number)
    txs = getattr(res, "transactions", None) or []
    status = _status(res)
    return {
        "success": status["code"] == 0,
        "message": status["message"] or None,
        "poolSeq": int(pool_seq) if pool_seq is not None else None,
        "transactionCount": len(txs),
    }


def map_smart_tx_response(res: Any) -> dict:
    """Shape the ``WaitForSmartTransaction`` response."""
    status = _status(res)
    tx_id = getattr(res, "id", None) or getattr(res, "transactionId", None)
    return {
        "success": status["code"] == 0,
        "message": status["message"] or None,
        "transactionId": _format_tx_id(tx_id),
    }


def _variant_to_python(variant: Any) -> Any:
    """Best-effort mapping of a Thrift ``Variant`` to a JSON-serialisable value."""
    if variant is None:
        return None
    for attr in (
        "v_string",
        "v_int",
        "v_long",
        "v_short",
        "v_byte",
        "v_bool",
        "v_double",
        "v_float",
        "v_void",
    ):
        v = getattr(variant, attr, None)
        if v is not None:
            return v
    arr = getattr(variant, "v_array", None)
    if arr is not None:
        return [_variant_to_python(x) for x in arr]
    return None


def map_tx_result(res: Any) -> dict:
    """Shape the ``TransactionResultGet`` response."""
    status = _status(res)
    return {
        "success": status["code"] == 0,
        "message": status["message"] or None,
        "found": bool(getattr(res, "found", False)) or status["code"] == 0,
        "result": _variant_to_python(getattr(res, "ret_val", None) or getattr(res, "result", None)),
        "executor": getattr(res, "executor", None),
    }
