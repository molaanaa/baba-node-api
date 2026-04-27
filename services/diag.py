"""Mappers for the Diagnostic Thrift service (``API_DIAG``).

Reference (CREDITSCOM/node):
    apidiaghandler.hpp -> GetActiveNodes / GetActiveTransactionsCount /
                          GetNodeInfo / GetSupply
"""

from __future__ import annotations

from typing import Any

import base58


def _b58(value):
    if not value:
        return None
    if isinstance(value, str):
        return value
    try:
        return base58.b58encode(value).decode("utf-8")
    except Exception:
        return None


def _status(obj: Any) -> dict:
    status = getattr(obj, "status", None)
    code = getattr(status, "code", 0) if status else 0
    message = getattr(status, "message", "") if status else ""
    return {"code": int(code or 0), "message": message or ""}


def map_active_node(item: Any) -> dict:
    return {
        "key": _b58(getattr(item, "key", None) or getattr(item, "publicKey", None)),
        "version": getattr(item, "version", None),
        "ip": getattr(item, "ip", None),
        "lastBlock": getattr(item, "lastBlock", None) or getattr(item, "round", None),
        "trustLevel": getattr(item, "trustLevel", None),
    }


def map_active_nodes(res: Any) -> dict:
    s = _status(res)
    items = getattr(res, "nodes", None) or []
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "count": int(getattr(res, "count", len(items)) or 0),
        "nodes": [map_active_node(x) for x in items],
    }


def map_active_transactions_count(res: Any) -> dict:
    s = _status(res)
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "count": int(getattr(res, "count", 0) or 0),
    }


def map_node_info(res: Any) -> dict:
    s = _status(res)
    info = getattr(res, "info", None) or getattr(res, "nodeInfo", None) or res
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "info": {
            "version": getattr(info, "version", None),
            "publicKey": _b58(getattr(info, "publicKey", None)),
            "ip": getattr(info, "ip", None),
            "lastBlock": getattr(info, "lastBlock", None),
            "uptimeSeconds": getattr(info, "uptimeSeconds", None) or getattr(info, "uptime", None),
            "trustLevel": getattr(info, "trustLevel", None),
        },
    }


def _amount(value):
    if value is None:
        return None
    integral = getattr(value, "integral", None)
    fraction = getattr(value, "fraction", None)
    if integral is None and fraction is None:
        return str(value)
    return f"{int(integral or 0)}.{int(fraction or 0):018d}"


def map_supply(res: Any) -> dict:
    s = _status(res)
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "initial": _amount(getattr(res, "initial", None)),
        "mined": _amount(getattr(res, "mined", None)),
        "currentSupply": _amount(getattr(res, "currentSupply", None) or getattr(res, "current", None)),
    }
