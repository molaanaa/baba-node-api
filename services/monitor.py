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


def map_block_response(res: Any, obsolete_hash: bytes = b"") -> dict:
    """Shape the ``WaitForBlock`` response.

    The Thrift schema for ``WaitForBlock`` is::

        PoolHash WaitForBlock(1: PoolHash obsolete)

    where ``PoolHash`` is ``typedef binary``. The node blocks until a new
    pool is sealed after the one identified by ``obsolete``, then returns
    the new pool's hash (raw bytes). For legacy reasons we also accept a
    response object exposing a ``hash`` attribute.
    """
    status = _status(res)
    raw = res if isinstance(res, (bytes, bytearray)) else (
        getattr(res, "hash", None) or getattr(res, "poolHash", None) or b""
    )
    new_hash_b58 = _b58(raw)
    same = bool(raw) and bool(obsolete_hash) and bytes(raw) == bytes(obsolete_hash)
    if isinstance(res, (bytes, bytearray)):
        # Plain typedef return: success iff we got non-empty bytes.
        ok = bool(raw)
        message = None
    else:
        ok = status["code"] == 0
        message = status["message"] or None
    return {
        "success": ok,
        "message": message,
        "hash": new_hash_b58,
        "obsoleteHash": _b58(bytes(obsolete_hash)) if obsolete_hash else None,
        "changed": (not same) if raw else False,
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
    """Best-effort mapping of a Thrift ``Variant`` to a JSON-serialisable value.

    Field names follow the real ``general.thrift`` Variant union: scalar
    primitives are ``v_boolean/v_byte/v_short/v_int/v_long/v_float/v_double``
    (with autoboxed ``*_box`` twins), strings are ``v_string``, raw bytes are
    ``v_byte_array``, and ``v_amount`` carries an Amount{integral, fraction}.
    Older drafts used ``v_bool``; we accept it as an alias.
    """
    if variant is None:
        return None
    for attr in (
        "v_string",
        "v_int",
        "v_int_box",
        "v_long",
        "v_long_box",
        "v_short",
        "v_short_box",
        "v_byte",
        "v_byte_box",
        "v_boolean",
        "v_boolean_box",
        "v_bool",  # alias for older nodes
        "v_double",
        "v_double_box",
        "v_float",
        "v_float_box",
        "v_void",
        "v_big_decimal",
    ):
        v = getattr(variant, attr, None)
        if v is not None:
            return v

    bytes_val = getattr(variant, "v_byte_array", None)
    if bytes_val is not None:
        try:
            import base64
            return base64.b64encode(bytes(bytes_val)).decode("ascii")
        except Exception:
            return None

    amount = getattr(variant, "v_amount", None)
    if amount is not None:
        return {
            "integral": getattr(amount, "integral", None),
            "fraction": getattr(amount, "fraction", None),
        }

    for attr in ("v_array", "v_list", "v_set"):
        arr = getattr(variant, attr, None)
        if arr is not None:
            return [_variant_to_python(x) for x in arr]

    mp = getattr(variant, "v_map", None)
    if mp is not None:
        try:
            return {str(_variant_to_python(k)): _variant_to_python(v) for k, v in mp.items()}
        except Exception:
            return None

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
