"""Mappers for the Token Thrift family.

Reference (CREDITSCOM/node):
    TokenBalancesGet      -> apihandler.hpp:153
    TokenTransfersGet     -> apihandler.cpp:2687
    TokenInfoGet          -> apihandler.cpp:2847
    TokenHoldersGet       -> apihandler.cpp:2888
    TokenTransactionsGet  -> apihandler.cpp:2843
"""

from __future__ import annotations

from typing import Any, Optional

import base58


def _b58(value: Optional[bytes]) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        return value
    try:
        return base58.b58encode(value).decode("utf-8")
    except Exception:
        return None


def _str(v: Any) -> Optional[str]:
    return None if v is None else str(v)


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


def map_balance_item(item: Any) -> dict:
    return {
        "token": _b58(getattr(item, "token", b"")),
        "code": _str(getattr(item, "code", None)),
        "balance": _str(getattr(item, "balance", "0")),
    }


def map_balances(res: Any) -> dict:
    s = _status(res)
    items = getattr(res, "balances", None) or []
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "balances": [map_balance_item(x) for x in items],
    }


def map_transfer_item(item: Any) -> dict:
    return {
        "token": _b58(getattr(item, "token", b"")),
        "code": _str(getattr(item, "code", None)),
        "sender": _b58(getattr(item, "sender", b"")),
        "receiver": _b58(getattr(item, "receiver", b"")),
        "amount": _str(getattr(item, "amount", "0")),
        "transaction": _format_tx_id(getattr(item, "transaction", None)),
        "time": getattr(item, "time", None),
    }


def map_transfers(res: Any) -> dict:
    s = _status(res)
    items = getattr(res, "transfers", None) or []
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "count": int(getattr(res, "count", len(items)) or 0),
        "transfers": [map_transfer_item(x) for x in items],
    }


def map_token_info(token: Any) -> dict:
    return {
        "address": _b58(getattr(token, "address", b"")),
        "code": _str(getattr(token, "code", None)),
        "name": _str(getattr(token, "name", None)),
        "totalSupply": _str(getattr(token, "totalSupply", "0")),
        "owner": _b58(getattr(token, "owner", b"")),
        "transfersCount": int(getattr(token, "transfersCount", 0) or 0),
        "transactionsCount": int(getattr(token, "transactionsCount", 0) or 0),
        "holdersCount": int(getattr(token, "holdersCount", 0) or 0),
        "transferFee": _str(getattr(token, "transferFee", None)),
    }


def map_info(res: Any) -> dict:
    s = _status(res)
    token = getattr(res, "token", None) or getattr(res, "info", None)
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "token": map_token_info(token) if token is not None else None,
    }


def map_holder_item(item: Any) -> dict:
    return {
        "holder": _b58(getattr(item, "holder", b"")),
        "balance": _str(getattr(item, "balance", "0")),
        "transfersCount": int(getattr(item, "transfersCount", 0) or 0),
    }


def map_holders(res: Any) -> dict:
    s = _status(res)
    items = getattr(res, "holders", None) or []
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "count": int(getattr(res, "count", len(items)) or 0),
        "holders": [map_holder_item(x) for x in items],
    }


def map_token_transaction_item(item: Any) -> dict:
    return {
        "transaction": _format_tx_id(getattr(item, "transaction", None)),
        "time": getattr(item, "time", None),
        "initiator": _b58(getattr(item, "initiator", b"")),
        "method": _str(getattr(item, "method", None)),
        "params": _str(getattr(item, "params", None)),
        "state": _str(getattr(item, "state", None)),
    }


def map_token_transactions(res: Any) -> dict:
    s = _status(res)
    items = getattr(res, "transactions", None) or []
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "count": int(getattr(res, "count", len(items)) or 0),
        "transactions": [map_token_transaction_item(x) for x in items],
    }
