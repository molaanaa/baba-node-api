"""Unit tests for the Smart Contract builder + mappers.

The Thrift-generated classes are stubbed via :class:`StubTypes` so we can
exercise the builder without pulling in ``gen-py``.
"""

import base64
from types import SimpleNamespace as NS

import base58
import pytest

from services import contracts as c


class _Field:
    pass


class StubTypes:
    """Minimal namespace mimicking the relevant Thrift classes."""

    class Amount:
        def __init__(self, integral=0, fraction=0):
            self.integral = integral
            self.fraction = fraction

    class AmountCommission:
        def __init__(self, commission=0):
            self.commission = commission

    class ByteCodeObject:
        def __init__(self):
            self.name = None
            self.byteCode = b""

    class SmartContractDeploy:
        def __init__(self):
            self.sourceCode = ""
            self.byteCodeObjects = []

    class SmartContractInvocation:
        def __init__(self):
            self.method = ""
            self.params = []
            self.forgetNewState = False
            self.smartContractDeploy = None

    class Variant:
        pass

    class Transaction:
        def __init__(self):
            self.id = 0
            self.source = b""
            self.target = b""
            self.amount = None
            self.balance = None
            self.currency = 1
            self.fee = None
            self.signature = b""
            self.userFields = b""
            self.smartContract = None
            self.type = 0

OK = NS(code=0, message="")
ERR = NS(code=1, message="boom")
DEPLOYER = b"\x01" * 32
DEPLOYER_B58 = base58.b58encode(DEPLOYER).decode()
CONTRACT = b"\x02" * 32
CONTRACT_B58 = base58.b58encode(CONTRACT).decode()


def test_build_deploy_transaction_shape():
    bytecode = b"deadbeef"
    tx = c.build_deploy_transaction(
        StubTypes,
        deployer_bytes=DEPLOYER,
        target_bytes=b"",
        byte_code_objects=[
            {"name": "AccessRights", "byteCode": base64.b64encode(bytecode).decode()}
        ],
        source_code="class AccessRights {}",
        fee_bits=12345,
        signature_bytes=b"sig",
        inner_id=42,
        user_fields=b"\x00",
    )
    assert tx.id == 42
    assert tx.source == DEPLOYER
    assert tx.target == b""
    assert tx.amount.integral == 0 and tx.amount.fraction == 0
    assert tx.fee.commission == 12345
    assert tx.signature == b"sig"
    assert tx.userFields == b"\x00"
    assert tx.type == c.TT_SMART_DEPLOY
    assert tx.smartContract is not None
    deploy = tx.smartContract.smartContractDeploy
    assert deploy is not None, "Deploy must populate the nested SmartContractDeploy"
    assert deploy.sourceCode == "class AccessRights {}"
    assert len(deploy.byteCodeObjects) == 1
    bco = deploy.byteCodeObjects[0]
    assert bco.name == "AccessRights"
    assert bco.byteCode == bytecode  # decoded from base64
    # Execute-only fields stay empty on a Deploy invocation.
    assert tx.smartContract.method == ""
    assert tx.smartContract.params == []


def test_build_execute_transaction_shape():
    tx = c.build_execute_transaction(
        StubTypes,
        sender_bytes=DEPLOYER,
        contract_bytes=CONTRACT,
        method="transfer",
        params=[{"K_TYPE": "STRING", "V_STRING": "abc"}, {"K_TYPE": "INT", "V_INT": 100}],
        fee_bits=999,
        signature_bytes=b"sig",
        inner_id=7,
        user_fields=b"",
        forget_new_state=False,
    )
    assert tx.type == c.TT_SMART_EXECUTE
    assert tx.target == CONTRACT
    assert tx.smartContract.method == "transfer"
    assert len(tx.smartContract.params) == 2
    assert tx.fee.commission == 999
    # Execute must NOT carry a Deploy payload.
    assert tx.smartContract.smartContractDeploy is None


def test_build_execute_requires_method():
    with pytest.raises(ValueError):
        c.build_execute_transaction(
            StubTypes,
            sender_bytes=DEPLOYER,
            contract_bytes=CONTRACT,
            method="",
            params=[],
            fee_bits=1,
            signature_bytes=b"",
            inner_id=1,
        )


def test_build_byte_code_objects_rejects_invalid_base64():
    with pytest.raises(ValueError):
        c.build_byte_code_objects(StubTypes, [{"name": "X", "byteCode": object()}])


def test_build_byte_code_objects_requires_name_and_bytecode():
    with pytest.raises(ValueError):
        c.build_byte_code_objects(StubTypes, [{"name": "", "byteCode": "AAAA"}])
    with pytest.raises(ValueError):
        c.build_byte_code_objects(StubTypes, [{"name": "X"}])


def test_map_compile_result_serialises_byte_code_objects():
    bytecode = b"\xca\xfe\xba\xbe"
    bco = NS(name="AccessRights", byteCode=bytecode)
    res = NS(status=OK, byteCodeObjects=[bco], tokenStandard=0)
    out = c.map_compile_result(res)
    assert out["success"] is True
    assert out["byteCodeObjects"][0]["name"] == "AccessRights"
    assert out["byteCodeObjects"][0]["byteCode"] == base64.b64encode(bytecode).decode()


def test_map_compile_result_propagates_error():
    out = c.map_compile_result(NS(status=ERR, byteCodeObjects=[]))
    assert out["success"] is False
    assert out["message"] == "boom"


def test_map_get_returns_contract_metadata():
    sc = NS(
        address=CONTRACT,
        deployer=DEPLOYER,
        sourceCode="src",
        byteCodeObjects=[NS(name="X", byteCode=b"\x01\x02")],
        transactionId=NS(poolSeq=10, index=2),
    )
    out = c.map_get(NS(status=OK, smartContract=sc))
    assert out["contract"]["address"] == CONTRACT_B58
    assert out["contract"]["deployer"] == DEPLOYER_B58
    assert out["contract"]["sourceCode"] == "src"
    assert out["contract"]["transactionId"] == "10.3"


def test_map_methods_includes_arguments():
    res = NS(
        status=OK,
        methods=[
            NS(
                name="transfer",
                returnType="void",
                arguments=[NS(name="to", type="String"), NS(name="amount", type="long")],
            )
        ],
    )
    out = c.map_methods(res)
    assert out["methods"][0]["name"] == "transfer"
    assert out["methods"][0]["arguments"] == [
        {"name": "to", "type": "String"},
        {"name": "amount", "type": "long"},
    ]


def test_map_state_includes_variables():
    # Legacy list-of-objects shape kept for backwards compatibility with
    # forks that pre-date the proper map<string, Variant> Thrift schema.
    res = NS(
        status=OK,
        variables=[NS(name="counter", type="int", value="42")],
    )
    out = c.map_state(res)
    assert out["variables"] == [{"name": "counter", "type": "int", "value": "42"}]


def test_map_state_handles_thrift_map_variables():
    # Real Thrift schema: variables: map<string, Variant>. Each Variant is
    # decoded so the JSON-facing client gets a primitive instead of an
    # opaque Thrift struct.
    counter = NS(v_long=42)
    name    = NS(v_string="EBB")
    res = NS(status=OK, variables={"counter": counter, "name": name})
    out = c.map_state(res)
    decoded = {v["name"]: v["value"] for v in out["variables"]}
    assert decoded == {"counter": 42, "name": "EBB"}


def test_map_state_includes_methods_from_data_get():
    # SmartContractDataResult also carries the contract's public methods.
    method = NS(
        name="transfer",
        returnType="boolean",
        arguments=[NS(name="to", type="String"), NS(name="amount", type="String")],
    )
    res = NS(status=OK, methods=[method], variables={})
    out = c.map_state(res)
    assert out["methods"][0]["name"] == "transfer"
    assert out["methods"][0]["returnType"] == "boolean"
    assert out["methods"][0]["arguments"] == [
        {"name": "to", "type": "String"},
        {"name": "amount", "type": "String"},
    ]


def test_map_list_by_wallet_serialises_contracts():
    contracts = [
        NS(
            address=CONTRACT,
            deployer=DEPLOYER,
            sourceCode="",
            byteCodeObjects=[],
            transactionId=NS(poolSeq=1, index=0),
        )
    ]
    out = c.map_list_by_wallet(NS(status=OK, smartContractsList=contracts))
    assert len(out["contracts"]) == 1
    assert out["contracts"][0]["address"] == CONTRACT_B58
    assert out["contracts"][0]["transactionId"] == "1.1"
