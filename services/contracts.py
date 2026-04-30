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

Canonical signing payload for Deploy/Execute transactions
---------------------------------------------------------

The node validates the ed25519 signature against the following little-endian
byte stream (mirrors CREDITSCOM/sdk_python `cssdk.py:deployContract` /
`executeContract`)::

    inner_id   : 6 bytes  little-endian (truncated u64)
    source     : 32 bytes (sender public key)
    target     : 32 bytes (deploy: blake2s(source||innerId(6)||concat(byteCode));
                            execute: contract address)
    amount.int : 4 bytes  little-endian signed (i32)
    amount.frac: 8 bytes  little-endian signed (i64)
    fee.bits   : 2 bytes  little-endian unsigned (u16)
    currency   : 1 byte   (0x01 for CS)
    uf_marker  : 1 byte   (0x01 — one user-field, the SmartContract)
    sc_len     : 4 bytes  little-endian (u32) length of sc_bytes
    sc_bytes   : Thrift TBinaryProtocol serialisation of SmartContractInvocation

Helper :func:`pack_smart_transaction` produces this stream and
:func:`derive_contract_address` computes the Deploy target address.
"""

from __future__ import annotations

import hashlib
import struct
from typing import Any, Iterable, Optional

import base58
from thrift.protocol import TBinaryProtocol
from thrift.transport import TTransport


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

def _dict_to_variant(types_ns, item):
    """Convert a JSON-friendly dict into a Thrift Variant."""
    Variant = getattr(types_ns, "Variant")
    v = Variant()
    if not isinstance(item, dict):
        return item
    if 'v_string' in item or 'valString' in item:
        v.v_string = item.get('v_string') or item.get('valString')
    elif 'v_int' in item or 'valInt' in item:
        v.v_int = int(item.get('v_int') or item.get('valInt'))
    elif 'v_bool' in item or 'valBool' in item:
        v.v_bool = bool(item.get('v_bool') or item.get('valBool'))
    elif 'v_byte_array' in item or 'valByteArray' in item:
        raw = item.get('v_byte_array') or item.get('valByteArray')
        v.v_byte_array = bytes(raw) if isinstance(raw, (bytes, bytearray)) else bytes(raw, 'utf-8')
    else:
        for key, val in item.items():
            if hasattr(v, key):
                setattr(v, key, val)
                break
    return v


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
        sc.params = [_dict_to_variant(types_ns, p) for p in (params or [])]
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


def _apply_invocation_defaults(invocation: Any) -> None:
    """Populate optional Thrift fields with the same defaults as the SDKs.

    The signed payload includes the TBinaryProtocol serialization of this
    struct, so the Deploy/Execute path on the gateway MUST set the same
    defaults the Pack endpoint set, or the rebuilt invocation will hash
    differently and the node will reject the signature.
    """
    if hasattr(invocation, "method") and getattr(invocation, "method", None) is None:
        invocation.method = ""
    if hasattr(invocation, "params") and getattr(invocation, "params", None) is None:
        invocation.params = []
    if hasattr(invocation, "usedContracts") and getattr(invocation, "usedContracts", None) is None:
        invocation.usedContracts = []
    if hasattr(invocation, "forgetNewState") and getattr(invocation, "forgetNewState", None) is None:
        invocation.forgetNewState = False
    if hasattr(invocation, "version") and getattr(invocation, "version", None) is None:
        invocation.version = 1
    deploy = getattr(invocation, "smartContractDeploy", None)
    if deploy is not None:
        if hasattr(deploy, "hashState") and getattr(deploy, "hashState", None) is None:
            deploy.hashState = ""
        if hasattr(deploy, "tokenStandard") and getattr(deploy, "tokenStandard", None) is None:
            deploy.tokenStandard = 0
        if hasattr(deploy, "lang") and getattr(deploy, "lang", None) is None:
            deploy.lang = 0
        if hasattr(deploy, "methods") and getattr(deploy, "methods", None) is None:
            deploy.methods = []


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
    _apply_invocation_defaults(tx.smartContract)
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
    _apply_invocation_defaults(tx.smartContract)
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
    """Shape ``SmartContractDataResult`` (apihandler.cpp:2611) for the gateway.

    The Thrift schema is::

        struct SmartContractDataResult {
            1: APIResponse status
            2: list<SmartContractMethod> methods
            3: map<string, Variant> variables
        }

    Both ``methods`` and ``variables`` are exposed: this is the most reliable
    way to read a deployed contract's public surface plus its instance fields,
    even when ``ContractMethodsGet(address)`` returns an empty list because
    the executor hasn't cached the contract yet. ``variables`` is decoded
    Variant-by-Variant so the client receives plain JSON values
    (strings/ints/booleans) instead of opaque Thrift Variant blobs.
    """
    # Reuse the shared Variant decoder from services.monitor to avoid duplication.
    from services.monitor import _variant_to_python  # local import — circular safe

    s = _status(res)
    # variables: schema is map<string, Variant>; older / fork shapes may use
    # a list<{name, type, value}> too — accept both for defensiveness.
    variables_raw = getattr(res, "variables", None)
    variables: list = []
    if isinstance(variables_raw, dict):
        for name, variant in variables_raw.items():
            variables.append({
                "name": name,
                "value": _variant_to_python(variant),
            })
    elif variables_raw:
        for v in variables_raw:
            if isinstance(v, dict):
                variables.append(v)
            else:
                raw_val = getattr(v, "value", None)
                # If value is a Thrift Variant (has v_string/v_int/...), decode it.
                # Otherwise pass through as-is so plain primitives stay plain.
                decoded = _variant_to_python(raw_val) if any(
                    hasattr(raw_val, a) for a in (
                        "v_string", "v_int", "v_long", "v_boolean", "v_byte_array",
                        "v_amount", "v_array", "v_map",
                    )
                ) else raw_val
                variables.append({
                    "name": getattr(v, "name", None),
                    "type": getattr(v, "type", None),
                    "value": decoded,
                })

    methods_raw = getattr(res, "methods", None) or []
    methods = []
    for m in methods_raw:
        args_raw = getattr(m, "arguments", None) or []
        methods.append({
            "name": getattr(m, "name", None),
            "returnType": getattr(m, "returnType", None),
            "arguments": [
                {"name": getattr(a, "name", None), "type": getattr(a, "type", None)}
                for a in args_raw
            ],
        })

    return {
        "success": s["code"] == 0,
        "message": s["message"] or None,
        "methods": methods,
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


# ---------------------------------------------------------------------------
# Canonical signing payload for SmartContract Deploy / Execute
# ---------------------------------------------------------------------------

def _inner_id_to_bytes6(inner_id: int) -> bytes:
    """Encode the 64-bit inner id as 6 little-endian bytes (per Credits scheme)."""
    if inner_id < 0:
        raise ValueError("inner_id must be non-negative")
    return struct.pack("<Q", int(inner_id))[:6]


def derive_contract_address(deployer_bytes: bytes, inner_id: int,
                            byte_code_objects: Iterable[Any]) -> bytes:
    """Mirror cssdk.createContractAddress: blake2s(source || innerId(6 bytes LE)
    || concat(byteCode for each ByteCodeObject)). Returns 32 raw bytes.

    ``byte_code_objects`` may contain Thrift ``ByteCodeObject`` instances or
    JSON-friendly dicts ``{'name': ..., 'byteCode': '<base64>' or bytes}``.
    """
    h = hashlib.blake2s()
    h.update(bytes(deployer_bytes))
    h.update(_inner_id_to_bytes6(inner_id))
    for bco in byte_code_objects or []:
        if isinstance(bco, dict):
            raw = bco.get("byteCode") or b""
            if isinstance(raw, str):
                import base64
                raw = base64.b64decode(raw, validate=False)
            h.update(bytes(raw))
        else:
            raw = getattr(bco, "byteCode", b"") or b""
            if isinstance(raw, str):
                import base64
                raw = base64.b64decode(raw, validate=False)
            h.update(bytes(raw))
    return h.digest()


def _serialize_invocation_thrift(invocation: Any) -> bytes:
    """Serialise a SmartContractInvocation through TBinaryProtocol.

    Matches `cssdk.deployContract`: ``contract.write(protocol)`` against a
    TMemoryBuffer; the resulting bytes are what the node expects in the
    signed payload (and what its own deserializer rebuilds to validate the
    signature).
    """
    buf = TTransport.TMemoryBuffer()
    proto = TBinaryProtocol.TBinaryProtocol(buf)
    invocation.write(proto)
    return buf.getvalue()


def pack_smart_transaction(
    types_ns: Any,
    *,
    inner_id: int,
    source_bytes: bytes,
    target_bytes: bytes,
    fee_bits: int,
    invocation: Any,
    amount_integral: int = 0,
    amount_fraction: int = 0,
    currency: int = 1,
    user_fields_marker: bytes = b"\x01",
) -> bytes:
    """Build the canonical signing payload for a SmartContract Deploy/Execute.

    See module docstring for the byte-level layout. Pass a fully-populated
    ``invocation`` (SmartContractInvocation Thrift instance); for a fresh
    Execute payload use :func:`build_smart_invocation`.

    ``types_ns`` is accepted for parity with the builder API and to allow
    future enrichment (e.g. defaulting missing optional fields) without a
    signature change.
    """
    sc_bytes = _serialize_invocation_thrift(invocation)
    out = bytearray()
    out += _inner_id_to_bytes6(inner_id)
    if len(source_bytes) != 32:
        raise ValueError(f"source must be 32 bytes, got {len(source_bytes)}")
    out += bytes(source_bytes)
    if target_bytes is None:
        target_bytes = b""
    if len(target_bytes) not in (0, 32):
        raise ValueError(f"target must be 32 or 0 bytes, got {len(target_bytes)}")
    # Pad an empty target to 32 bytes of zeros — the canonical scheme always
    # consumes 32 bytes here (Deploy uses the derived address; we still
    # accept an empty target for callers that want to compute it themselves).
    out += bytes(target_bytes).ljust(32, b"\x00")
    out += struct.pack("<i", int(amount_integral))
    out += struct.pack("<q", int(amount_fraction))
    out += struct.pack("<H", int(fee_bits) & 0xFFFF)
    out += struct.pack("<b", int(currency))
    if not user_fields_marker:
        user_fields_marker = b"\x01"
    out += bytes(user_fields_marker[:1])
    out += struct.pack("<I", len(sc_bytes))
    out += sc_bytes
    return bytes(out)


def build_pack_deploy_payload(
    types_ns: Any,
    *,
    deployer_bytes: bytes,
    inner_id: int,
    fee_bits: int,
    byte_code_objects: Iterable[dict],
    source_code: str,
    user_fields: bytes = b"",
) -> "tuple[bytes, bytes]":
    """High-level helper: build invocation + canonical payload for Deploy.

    Returns ``(payload_bytes, contract_address_bytes)``. The caller signs
    ``payload_bytes`` with ed25519 and calls ``/SmartContract/Deploy`` with
    the signature plus the same source/byteCode payload (so the gateway
    rebuilds an identical Transaction on the way to TransactionFlow).
    """
    bcos_thrift = build_byte_code_objects(types_ns, byte_code_objects)
    contract_addr = derive_contract_address(deployer_bytes, inner_id, bcos_thrift)
    invocation = build_smart_invocation(
        types_ns,
        source_code=source_code,
        byte_code_objects=byte_code_objects,
    )
    _apply_invocation_defaults(invocation)
    payload = pack_smart_transaction(
        types_ns,
        inner_id=inner_id,
        source_bytes=deployer_bytes,
        target_bytes=contract_addr,
        fee_bits=fee_bits,
        invocation=invocation,
    )
    return payload, contract_addr


def build_pack_execute_payload(
    types_ns: Any,
    *,
    sender_bytes: bytes,
    contract_bytes: bytes,
    inner_id: int,
    fee_bits: int,
    method: str,
    params: Iterable[dict] = (),
    forget_new_state: bool = False,
    user_fields: bytes = b"",
) -> bytes:
    """High-level helper: build invocation + canonical payload for Execute."""
    if not method:
        raise ValueError("method is required for Execute")
    invocation = build_smart_invocation(
        types_ns,
        method=method,
        params=params,
        forget_new_state=forget_new_state,
    )
    _apply_invocation_defaults(invocation)
    return pack_smart_transaction(
        types_ns,
        inner_id=inner_id,
        source_bytes=sender_bytes,
        target_bytes=contract_bytes,
        fee_bits=fee_bits,
        invocation=invocation,
    )
