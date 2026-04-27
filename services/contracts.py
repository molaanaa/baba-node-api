"""Smart Contract response mappers and Deploy/Execute transaction builder.

Reference (CREDITSCOM/node):
    SmartContractCompile   -> apihandler.cpp:2548
    SmartContractGet       -> apihandler.hpp:111
    getContractMethods     -> apihandler.cpp:2571 (executor)
    SmartContractDataGet   -> apihandler.hpp:150 / apihandler.cpp:2611
    SmartContractsListGet  -> apihandler.hpp:113
    Deploy/Execute         -> built locally as Transaction + TransactionFlow

The node does not expose dedicated Deploy/Execute RPCs; the gateway shapes a
``Transaction`` struct with the right type/smartContract fields and forwards
it via ``TransactionFlow`` exactly as the existing /Transaction/Execute path
does.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

import base58


# Credits transaction type field. Matches the type_defs table already used in
# gateway.py for /api/Transaction/GetTransactionInfo.
TT_NORMAL = 0
TT_SMART_DEPLOY = 1
TT_SMART_EXECUTE = 2
TT_SMART_STATE = 3
TT_CONTRACT_REPLENISH = 4


def _b58(value: Optional[bytes]) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        return value
    try:
        return base58.b58encode(value).decode("utf-8")
    except Exception:
        return None


def _b64_to_bytes(name: str, value) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a base64 string")
    import base64

    try:
        return base64.b64decode(value, validate=False)
    except Exception as exc:
        raise ValueError(f"{name} is not valid base64") from exc


def _status(obj: Any) -> dict:
    """Extract a normalised {code,message} from a node response.

    Most result structs nest an APIResponse under ``status``, but a few
    (notably ``ContractAllMethodsGetResult``) inline ``code`` and ``message``
    on the result struct itself. Accept both shapes.
    """
    status = getattr(obj, "status", None)
    if status is not None:
        code = getattr(status, "code", 0)
        message = getattr(status, "message", "")
    else:
        code = getattr(obj, "code", 0)
        message = getattr(obj, "message", "")
    return {"code": int(code or 0), "message": message or ""}


def _format_tx_id(tx_id: Any) -> Optional[str]:
    if tx_id is None:
        return None
    pool_seq = getattr(tx_id, "poolSeq", None)
    index = getattr(tx_id, "index", None)
    if pool_seq is None or index is None:
        return None
    return f"{pool_seq}.{int(index) + 1}"


def map_byte_code_object(bco: Any) -> dict:
    bc = getattr(bco, "byteCode", b"") or b""
    if isinstance(bc, str):
        # Already encoded by the upstream layer.
        bc_str = bc
    else:
        import base64

        bc_str = base64.b64encode(bytes(bc)).decode("ascii")
    return {"name": getattr(bco, "name", None), "byteCode": bc_str}


def build_byte_code_objects(types_ns: Any, items: Iterable[dict]) -> list:
    """Construct Thrift ByteCodeObject instances from JSON-friendly dicts."""
    BCOClass = getattr(types_ns, "ByteCodeObject")
    out = []
    for raw in items or []:
        name = raw.get("name") if isinstance(raw, dict) else None
        bc = raw.get("byteCode") if isinstance(raw, dict) else None
        if not name:
            raise ValueError("byteCodeObjects entries require a 'name'")
        if bc is None:
            raise ValueError("byteCodeObjects entries require a 'byteCode'")
        bco = BCOClass()
        bco.name = name
        bco.byteCode = _b64_to_bytes(f"byteCodeObjects[{name}].byteCode", bc)
        out.append(bco)
    return out


def build_smart_invocation(
    types_ns: Any,
    *,
    source_code: str = "",
    byte_code_objects: Iterable[dict] = (),
    method: str = "",
    params: Iterable[dict] = (),
    forget_new_state: bool = False,
):
    """Shape a SmartContractInvocation.

    In the real Thrift schema, ``sourceCode`` and ``byteCodeObjects`` live on
    the nested ``SmartContractDeploy`` struct (field ``smartContractDeploy``
    of ``SmartContractInvocation``); this builder routes Deploy-only fields
    there. ``method/params/forgetNewState`` stay on the invocation itself.
    A flat-stub fallback is kept so unit tests with simplified namespaces
    keep working.
    """
    SCInvClass = getattr(types_ns, "SmartContractInvocation")
    sc = SCInvClass()
    if hasattr(sc, "method"):
        sc.method = method or ""
    if hasattr(sc, "params"):
        sc.params = list(params or [])
    if hasattr(sc, "forgetNewState"):
        sc.forgetNewState = bool(forget_new_state)

    has_deploy_payload = bool(source_code) or bool(list(byte_code_objects or []))
    if not has_deploy_payload:
        return sc

    SCDeployClass = getattr(types_ns, "SmartContractDeploy", None)
    if SCDeployClass is not None and hasattr(sc, "smartContractDeploy"):
        deploy = SCDeployClass()
        if hasattr(deploy, "sourceCode"):
            deploy.sourceCode = source_code or ""
        if hasattr(deploy, "byteCodeObjects"):
            deploy.byteCodeObjects = build_byte_code_objects(types_ns, byte_code_objects)
        sc.smartContractDeploy = deploy
    else:
        # Flat fallback for legacy / stub schemas without SmartContractDeploy.
        if hasattr(sc, "sourceCode"):
            sc.sourceCode = source_code or ""
        if hasattr(sc, "byteCodeObjects"):
            sc.byteCodeObjects = build_byte_code_objects(types_ns, byte_code_objects)
    return sc


def build_deploy_transaction(
    types_ns: Any,
    *,
    deployer_bytes: bytes,
    target_bytes: bytes,
    byte_code_objects: Iterable[dict],
    source_code: str,
    fee_bits: int,
    signature_bytes: bytes,
    inner_id: int,
    user_fields: bytes = b"",
):
    Transaction = getattr(types_ns, "Transaction")
    Amount = getattr(types_ns, "Amount")
    AmountCommission = getattr(types_ns, "AmountCommission")

    tx = Transaction()
    tx.id = inner_id
    tx.source = deployer_bytes
    tx.target = target_bytes or b""
    tx.amount = Amount(0, 0)
    tx.balance = Amount(0, 0)
    tx.currency = 1
    tx.fee = AmountCommission(commission=int(fee_bits))
    tx.signature = signature_bytes or b""
    tx.userFields = user_fields or b""
    tx.smartContract = build_smart_invocation(
        types_ns,
        source_code=source_code,
        byte_code_objects=byte_code_objects,
    )
    if hasattr(tx, "type"):
        tx.type = TT_SMART_DEPLOY
    return tx


def build_execute_transaction(
    types_ns: Any,
    *,
    sender_bytes: bytes,
    contract_bytes: bytes,
    method: str,
    params: Iterable[dict],
    fee_bits: int,
    signature_bytes: bytes,
    inner_id: int,
    user_fields: bytes = b"",
    forget_new_state: bool = False,
):
    Transaction = getattr(types_ns, "Transaction")
    Amount = getattr(types_ns, "Amount")
    AmountCommission = getattr(types_ns, "AmountCommission")

    if not method:
        raise ValueError("method is required for Execute")
    tx = Transaction()
    tx.id = inner_id
    tx.source = sender_bytes
    tx.target = contract_bytes
    tx.amount = Amount(0, 0)
    tx.balance = Amount(0, 0)
    tx.currency = 1
    tx.fee = AmountCommission(commission=int(fee_bits))
    tx.signature = signature_bytes or b""
    tx.userFields = user_fields or b""
    tx.smartContract = build_smart_invocation(
        types_ns,
        method=method,
        params=params,
        forget_new_state=forget_new_state,
    )
    if hasattr(tx, "type"):
        tx.type = TT_SMART_EXECUTE
    return tx


def map_compile_result(res: Any) -> dict:
    s = _status(res)
    bcos = getattr(res, "byteCodeObjects", None) or []
    ts_supported = getattr(res, "tokenStandard", None)
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "byteCodeObjects": [map_byte_code_object(b) for b in bcos],
        "tokenStandard": ts_supported,
    }


def map_smart_contract(sc: Any) -> Optional[dict]:
    if sc is None:
        return None
    # Real Thrift SmartContract nests sourceCode/byteCodeObjects in
    # `smartContractDeploy` (SmartContractDeploy struct). Test fixtures using
    # SimpleNamespace tend to flatten them on `sc` directly — accept both.
    deploy = getattr(sc, "smartContractDeploy", None)
    src_code = getattr(sc, "sourceCode", None)
    bcos = getattr(sc, "byteCodeObjects", None)
    if deploy is not None:
        if src_code is None:
            src_code = getattr(deploy, "sourceCode", None)
        if not bcos:
            bcos = getattr(deploy, "byteCodeObjects", None)
    bcos = bcos or []
    return {
        "address": _b58(getattr(sc, "address", b"")),
        "deployer": _b58(getattr(sc, "deployer", b"")),
        "sourceCode": src_code,
        "byteCodeObjects": [map_byte_code_object(b) for b in bcos],
        "transactionId": _format_tx_id(getattr(sc, "transactionId", None)),
        "createTime": getattr(sc, "createTime", None),
        "transactionsCount": getattr(sc, "transactionsCount", None),
    }


def map_get(res: Any) -> dict:
    s = _status(res)
    sc = getattr(res, "smartContract", None) or getattr(res, "contract", None)
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "contract": map_smart_contract(sc),
    }


def map_methods(res: Any) -> dict:
    s = _status(res)
    methods_raw = getattr(res, "methods", None) or []
    methods = []
    for m in methods_raw:
        params_raw = getattr(m, "arguments", None) or getattr(m, "params", None) or []
        methods.append(
            {
                "name": getattr(m, "name", None),
                "returnType": getattr(m, "returnType", None) or getattr(m, "returnsType", None),
                "arguments": [
                    {"name": getattr(p, "name", None), "type": getattr(p, "type", None)}
                    for p in params_raw
                ],
            }
        )
    return {"success": s["code"] == 0, "message": s["message"] or None, "methods": methods}


def map_state(res: Any) -> dict:
    s = _status(res)
    contract_state = getattr(res, "contractState", None) or getattr(res, "state", None)
    variables_raw = getattr(res, "variables", None) or []
    variables = []
    for v in variables_raw:
        variables.append(
            {
                "name": getattr(v, "name", None),
                "type": getattr(v, "type", None),
                "value": getattr(v, "value", None),
            }
        )
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "state": contract_state,
        "variables": variables,
    }


def map_list_by_wallet(res: Any) -> dict:
    s = _status(res)
    items = getattr(res, "smartContractsList", None) or getattr(res, "contracts", None) or []
    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "contracts": [map_smart_contract(x) for x in items],
    }
