"""Unit tests for the canonical SmartContract signing payload (packer).

These tests exercise :func:`services.contracts.pack_smart_transaction`,
:func:`services.contracts.derive_contract_address`, and the high-level
``build_pack_*_payload`` helpers against the real Thrift-generated
classes in ``gen-py/`` so we catch any drift between the Pack endpoint
and the Deploy/Execute path that has to rebuild the same bytes.
"""

from __future__ import annotations

import base64
import os
import struct
import sys
from pathlib import Path

import pytest

# gen-py lives at the repo root; mirror gateway.py's sys.path tweak.
ROOT = Path(__file__).resolve().parent.parent
GEN_PY = ROOT / "gen-py"
if GEN_PY.is_dir() and str(GEN_PY) not in sys.path:
    sys.path.insert(0, str(GEN_PY))

# Skip the whole module if the runtime Thrift stack is not installed; pytest
# stays green on environments that only run the AST/mapper-level checks.
pytestmark = pytest.mark.skipif(
    not GEN_PY.is_dir(),
    reason="gen-py not available (Thrift stubs not generated)",
)

try:  # pragma: no cover - guard for non-Thrift envs
    import api.ttypes as api_types
    import general.ttypes as general_types
    import types as _py_types
    from services import contracts as c
except Exception as _e:  # pragma: no cover
    pytest.skip(f"Thrift stack not available: {_e}", allow_module_level=True)


@pytest.fixture(scope="module")
def thrift_ns():
    ns = _py_types.SimpleNamespace()
    for src in (general_types, api_types):
        for name in dir(src):
            if not name.startswith("_"):
                setattr(ns, name, getattr(src, name))
    return ns


DEPLOYER = b"\x11" * 32
CONTRACT = b"\x22" * 32


def test_inner_id_to_bytes6_matches_struct_pack():
    assert c._inner_id_to_bytes6(1) == struct.pack("<Q", 1)[:6]
    assert c._inner_id_to_bytes6(0) == b"\x00" * 6
    assert c._inner_id_to_bytes6(0xABCDEF) == bytes([0xEF, 0xCD, 0xAB, 0, 0, 0])


def test_derive_contract_address_blake2s_matches_sdk(thrift_ns):
    """Mirror cssdk.createContractAddress: blake2s(source||innerId6||code)."""
    import hashlib

    bcos = c.build_byte_code_objects(
        thrift_ns,
        [{"name": "X", "byteCode": base64.b64encode(b"\xCA\xFE\xBA\xBE").decode()}],
    )
    derived = c.derive_contract_address(DEPLOYER, 7, bcos)

    expected = hashlib.blake2s()
    expected.update(DEPLOYER)
    expected.update(struct.pack("<Q", 7)[:6])
    expected.update(b"\xCA\xFE\xBA\xBE")
    assert derived == expected.digest()
    assert len(derived) == 32


def test_pack_execute_payload_has_canonical_prefix(thrift_ns):
    """The first 54 bytes are the transfer-prefix and the marker byte."""
    inner_id = 99
    fee_bits = 1234
    payload = c.build_pack_execute_payload(
        thrift_ns,
        sender_bytes=DEPLOYER,
        contract_bytes=CONTRACT,
        inner_id=inner_id,
        fee_bits=fee_bits,
        method="getCounter",
        params=[],
    )

    # Prefix layout: 6 (id) + 32 (src) + 32 (target) + 4 (i) + 8 (q) + 2 (h)
    #              + 1 (currency) + 1 (uf marker) + 4 (sc len) = 90
    assert payload[:6] == struct.pack("<Q", inner_id)[:6]
    assert payload[6:38] == DEPLOYER
    assert payload[38:70] == CONTRACT
    assert payload[70:74] == struct.pack("<i", 0)
    assert payload[74:82] == struct.pack("<q", 0)
    assert payload[82:84] == struct.pack("<H", fee_bits)
    assert payload[84:85] == b"\x01"  # currency = 1 (CS)
    assert payload[85:86] == b"\x01"  # uf marker = 1 (smart-contract)
    sc_len = struct.unpack("<I", payload[86:90])[0]
    assert sc_len > 0
    assert len(payload) == 90 + sc_len


def test_pack_deploy_payload_uses_derived_target(thrift_ns):
    bcos_raw = [
        {"name": "BasicCounter",
         "byteCode": base64.b64encode(b"\x01\x02\x03\x04").decode()}
    ]
    payload, contract_addr = c.build_pack_deploy_payload(
        thrift_ns,
        deployer_bytes=DEPLOYER,
        inner_id=42,
        fee_bits=4096,
        byte_code_objects=bcos_raw,
        source_code="class BasicCounter {}",
    )
    # The target slot of the canonical payload must equal the derived address.
    assert len(contract_addr) == 32
    assert payload[38:70] == contract_addr

    # And the derivation matches a manual blake2s of the same inputs.
    import hashlib
    h = hashlib.blake2s()
    h.update(DEPLOYER)
    h.update(struct.pack("<Q", 42)[:6])
    h.update(b"\x01\x02\x03\x04")
    assert contract_addr == h.digest()


def test_pack_and_rebuilt_invocation_serialize_to_same_bytes(thrift_ns):
    """The Pack endpoint and the Deploy endpoint MUST produce identical
    SmartContractInvocation bytes — otherwise the node rejects the signature
    even though the rest of the payload matches.
    """
    bcos_raw = [
        {"name": "X",
         "byteCode": base64.b64encode(b"\xDE\xAD\xBE\xEF").decode()}
    ]

    payload, _ = c.build_pack_deploy_payload(
        thrift_ns,
        deployer_bytes=DEPLOYER,
        inner_id=5,
        fee_bits=99,
        byte_code_objects=bcos_raw,
        source_code="src",
    )

    tx = c.build_deploy_transaction(
        thrift_ns,
        deployer_bytes=DEPLOYER,
        target_bytes=b"",  # actual target is computed by Pack; for rebuild
        byte_code_objects=bcos_raw,
        source_code="src",
        fee_bits=99,
        signature_bytes=b"",
        inner_id=5,
    )
    rebuilt_bytes = c._serialize_invocation_thrift(tx.smartContract)

    sc_len_in_payload = struct.unpack("<I", payload[86:90])[0]
    sc_bytes_in_payload = payload[90:90 + sc_len_in_payload]
    assert rebuilt_bytes == sc_bytes_in_payload, (
        "Pack and Deploy must produce identical Thrift binary for "
        "SmartContractInvocation; otherwise the signature won't verify"
    )


def test_pack_and_rebuilt_execute_invocation_match(thrift_ns):
    payload = c.build_pack_execute_payload(
        thrift_ns,
        sender_bytes=DEPLOYER,
        contract_bytes=CONTRACT,
        inner_id=11,
        fee_bits=64,
        method="increment",
        params=[],
        forget_new_state=False,
    )
    tx = c.build_execute_transaction(
        thrift_ns,
        sender_bytes=DEPLOYER,
        contract_bytes=CONTRACT,
        method="increment",
        params=[],
        fee_bits=64,
        signature_bytes=b"",
        inner_id=11,
        forget_new_state=False,
    )
    rebuilt_bytes = c._serialize_invocation_thrift(tx.smartContract)
    sc_len = struct.unpack("<I", payload[86:90])[0]
    assert payload[90:90 + sc_len] == rebuilt_bytes


def test_pack_rejects_bad_source_length(thrift_ns):
    with pytest.raises(ValueError):
        c.pack_smart_transaction(
            thrift_ns,
            inner_id=1,
            source_bytes=b"\x00" * 31,  # 31 bytes — invalid
            target_bytes=b"\x00" * 32,
            fee_bits=0,
            invocation=thrift_ns.SmartContractInvocation(),
        )


def test_pack_rejects_bad_target_length(thrift_ns):
    with pytest.raises(ValueError):
        c.pack_smart_transaction(
            thrift_ns,
            inner_id=1,
            source_bytes=b"\x00" * 32,
            target_bytes=b"\x00" * 31,
            fee_bits=0,
            invocation=thrift_ns.SmartContractInvocation(),
        )
