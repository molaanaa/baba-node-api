import base58
import pytest

from services import userfields as uf


def test_encode_magic_and_version():
    out = uf.encode({})
    assert out[:4] == b"ARTV"
    assert out[4] == 0x01


def test_roundtrip_full_payload():
    payload = {
        "contentHashAlgo": "sha-256",
        "contentHash": "00112233445566778899aabbccddeeff" * 2,
        "contentCid": "bafybeigdyrabc",
        "demoCid": "bafkreidemo",
        "mime": "image/png",
        "sizeBytes": 1234567890123,
        "contractAddress": base58.b58encode(b"\x01" * 32).decode("ascii"),
    }
    encoded = uf.encode(payload)
    decoded = uf.decode(encoded)
    assert decoded["version"] == 0x01
    for k, v in payload.items():
        assert decoded[k] == v


def test_skips_empty_values():
    encoded = uf.encode({"contentCid": "", "mime": None, "contentHashAlgo": "blake3"})
    decoded = uf.decode(encoded)
    assert decoded == {"version": 0x01, "contentHashAlgo": "blake3"}


def test_decode_rejects_bad_magic():
    with pytest.raises(uf.UserFieldsError):
        uf.decode(b"XXXX" + b"\x01")


def test_decode_rejects_unknown_version():
    with pytest.raises(uf.UserFieldsError):
        uf.decode(b"ARTV" + b"\x02")


def test_decode_rejects_truncated_tlv_header():
    with pytest.raises(uf.UserFieldsError):
        uf.decode(b"ARTV" + b"\x01" + b"\x01\x00")  # missing third length byte


def test_decode_rejects_truncated_tlv_value():
    payload = bytearray(b"ARTV\x01")
    payload.append(uf.T_MIME)
    payload.extend((10).to_bytes(2, "big"))
    payload.extend(b"abc")  # claims 10 bytes, only 3 supplied
    with pytest.raises(uf.UserFieldsError):
        uf.decode(bytes(payload))


def test_size_bytes_must_be_8_bytes():
    payload = bytearray(b"ARTV\x01")
    payload.append(uf.T_SIZE_BYTES)
    payload.extend((4).to_bytes(2, "big"))
    payload.extend(b"\x00\x00\x00\x10")
    with pytest.raises(uf.UserFieldsError):
        uf.decode(bytes(payload))


def test_invalid_hex_rejected():
    with pytest.raises(uf.UserFieldsError):
        uf.encode({"contentHash": "not-hex!"})


def test_invalid_base58_rejected():
    with pytest.raises(uf.UserFieldsError):
        uf.encode({"contractAddress": "0OIl"})  # contains chars not in base58 alphabet


def test_value_too_large_rejected():
    big = "x" * (uf.MAX_TLV_LEN + 1)
    with pytest.raises(uf.UserFieldsError):
        uf.encode({"contentCid": big})


def test_unknown_tlv_preserved_in_extra():
    payload = bytearray(b"ARTV\x01")
    payload.append(0x42)  # unknown type
    payload.extend((3).to_bytes(2, "big"))
    payload.extend(b"abc")
    decoded = uf.decode(bytes(payload))
    assert decoded["extra"] == [{"type": 0x42, "value": b"abc".hex()}]


def test_uint64_overflow_rejected():
    with pytest.raises(uf.UserFieldsError):
        uf.encode({"sizeBytes": 2**64})
