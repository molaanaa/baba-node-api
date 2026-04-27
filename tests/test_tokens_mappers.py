from types import SimpleNamespace as NS

import base58

from services import tokens as t


OK = NS(code=0, message="")
ERR = NS(code=1, message="boom")
ADDR = b"\x07" * 32
ADDR_B58 = base58.b58encode(ADDR).decode("ascii")


def test_map_balances_success():
    res = NS(
        status=OK,
        balances=[
            NS(token=ADDR, code="MYT", balance="1000"),
            NS(token=ADDR, code="OTH", balance="42"),
        ],
    )
    out = t.map_balances(res)
    assert out["success"] is True
    assert out["balances"] == [
        {"token": ADDR_B58, "code": "MYT", "balance": "1000"},
        {"token": ADDR_B58, "code": "OTH", "balance": "42"},
    ]


def test_map_balances_empty():
    out = t.map_balances(NS(status=OK, balances=None))
    assert out["balances"] == []


def test_map_balances_propagates_error():
    out = t.map_balances(NS(status=ERR, balances=[]))
    assert out["success"] is False
    assert out["message"] == "boom"


def test_map_transfers_formats_tx_id_and_addresses():
    sender = b"\x01" * 32
    receiver = b"\x02" * 32
    res = NS(
        status=OK,
        count=1,
        transfers=[
            NS(
                token=ADDR,
                code="MYT",
                sender=sender,
                receiver=receiver,
                amount="100",
                transaction=NS(poolSeq=10, index=4),
                time=1700000000,
            )
        ],
    )
    out = t.map_transfers(res)
    assert out["count"] == 1
    item = out["transfers"][0]
    assert item["sender"] == base58.b58encode(sender).decode("ascii")
    assert item["receiver"] == base58.b58encode(receiver).decode("ascii")
    assert item["transaction"] == "10.5"
    assert item["amount"] == "100"


def test_map_transfers_count_falls_back_to_list_length():
    res = NS(status=OK, transfers=[NS(), NS(), NS()])
    out = t.map_transfers(res)
    assert out["count"] == 3


def test_map_info_full_token():
    owner = b"\x05" * 32
    token = NS(
        address=ADDR,
        code="MYT",
        name="MyToken",
        totalSupply="1000000",
        owner=owner,
        transfersCount=12,
        transactionsCount=20,
        holdersCount=7,
        transferFee="0.01",
    )
    out = t.map_info(NS(status=OK, token=token))
    assert out["token"]["address"] == ADDR_B58
    assert out["token"]["owner"] == base58.b58encode(owner).decode("ascii")
    assert out["token"]["holdersCount"] == 7
    assert out["token"]["totalSupply"] == "1000000"


def test_map_info_missing_token():
    out = t.map_info(NS(status=ERR, token=None))
    assert out["success"] is False
    assert out["token"] is None


def test_map_holders():
    holders = [
        NS(holder=b"\x0a" * 32, balance="500", transfersCount=3),
        NS(holder=b"\x0b" * 32, balance="250", transfersCount=1),
    ]
    out = t.map_holders(NS(status=OK, count=2, holders=holders))
    assert out["count"] == 2
    assert out["holders"][0]["holder"] == base58.b58encode(b"\x0a" * 32).decode("ascii")
    assert out["holders"][1]["transfersCount"] == 1


def test_map_token_transactions():
    res = NS(
        status=OK,
        count=1,
        transactions=[
            NS(
                transaction=NS(poolSeq=99, index=0),
                time=1700000000,
                initiator=b"\xaa" * 32,
                method="transfer",
                params="[a,b,100]",
                state="Success",
            )
        ],
    )
    out = t.map_token_transactions(res)
    assert out["count"] == 1
    tx = out["transactions"][0]
    assert tx["transaction"] == "99.1"
    assert tx["method"] == "transfer"
    assert tx["state"] == "Success"
