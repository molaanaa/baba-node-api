"""userFields v1 codec — ordinals-style on-chain metadata for Credits.

Encodes a small structured payload (digest, IPFS CID, MIME, size, optional
TLV extensions) into a base58 blob suitable for the `UserData` field of a
Credits transaction, so the chain carries a verifiable reference to the
off-chain asset. Decoding round-trips the same fields.

Wire format (binary):

    userFields := MAGIC | VERSION | TLV_RECORDS

    MAGIC      = b"ARTV"      (4 bytes ASCII; legacy magic, retained for
                              backwards compatibility with existing inscribed
                              transactions and test vectors)
    VERSION    = 0x01         (1 byte)
    TLV_RECORDS = (TYPE | LEN | VALUE)*
        TYPE  = 1 byte
        LEN   = 2 bytes big-endian (max 65535)
        VALUE = byte[LEN]

Type registry (v1, frozen):
    0x01 contentHashAlgo   ascii
    0x02 contentHash       raw bytes (consumed/produced as hex string at JSON layer)
    0x03 contentCid        ascii
    0x04 demoCid           ascii
    0x05 mime              ascii
    0x06 sizeBytes         uint64 big-endian (8 bytes)
    0x07 contractAddress   base58 (decoded to raw bytes on the wire)
    0x08 reserved
"""

from __future__ import annotations

import base58


MAGIC = b"ARTV"
VERSION = 0x01

T_CONTENT_HASH_ALGO = 0x01
T_CONTENT_HASH = 0x02
T_CONTENT_CID = 0x03
T_DEMO_CID = 0x04
T_MIME = 0x05
T_SIZE_BYTES = 0x06
T_CONTRACT_ADDRESS = 0x07
T_RESERVED = 0x08

KNOWN_TYPES = {
    T_CONTENT_HASH_ALGO,
    T_CONTENT_HASH,
    T_CONTENT_CID,
    T_DEMO_CID,
    T_MIME,
    T_SIZE_BYTES,
    T_CONTRACT_ADDRESS,
    T_RESERVED,
}

MAX_TLV_LEN = 0xFFFF


class UserFieldsError(ValueError):
    """Raised on malformed userFields payloads or invalid input."""


def _ascii_bytes(name: str, value) -> bytes:
    if not isinstance(value, str):
        raise UserFieldsError(f"{name} must be a string")
    try:
        return value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise UserFieldsError(f"{name} must be ASCII") from exc


def _hex_to_bytes(name: str, value) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if not isinstance(value, str):
        raise UserFieldsError(f"{name} must be a hex string")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise UserFieldsError(f"{name} is not valid hex") from exc


def _u64(name: str, value) -> bytes:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise UserFieldsError(f"{name} must be an integer") from exc
    if n < 0 or n > 0xFFFFFFFFFFFFFFFF:
        raise UserFieldsError(f"{name} out of uint64 range")
    return n.to_bytes(8, "big")


def _b58_to_bytes(name: str, value) -> bytes:
    if not isinstance(value, str):
        raise UserFieldsError(f"{name} must be a base58 string")
    try:
        return base58.b58decode(value)
    except Exception as exc:
        raise UserFieldsError(f"{name} is not valid base58") from exc


def _emit_tlv(out: bytearray, type_byte: int, value: bytes) -> None:
    if len(value) > MAX_TLV_LEN:
        raise UserFieldsError(
            f"TLV value for type 0x{type_byte:02x} exceeds {MAX_TLV_LEN} bytes"
        )
    out.append(type_byte)
    out.extend(len(value).to_bytes(2, "big"))
    out.extend(value)


def encode(fields: dict) -> bytes:
    """Encode a fields dict into the binary userFields v1 payload.

    Unknown keys are ignored. Empty/None values are skipped. Order of TLV records
    follows the type id ordering for determinism.
    """
    if not isinstance(fields, dict):
        raise UserFieldsError("fields must be a dict")

    out = bytearray()
    out.extend(MAGIC)
    out.append(VERSION)

    encoders = [
        (T_CONTENT_HASH_ALGO, "contentHashAlgo", _ascii_bytes),
        (T_CONTENT_HASH, "contentHash", _hex_to_bytes),
        (T_CONTENT_CID, "contentCid", _ascii_bytes),
        (T_DEMO_CID, "demoCid", _ascii_bytes),
        (T_MIME, "mime", _ascii_bytes),
        (T_SIZE_BYTES, "sizeBytes", _u64),
        (T_CONTRACT_ADDRESS, "contractAddress", _b58_to_bytes),
    ]

    for type_byte, key, conv in encoders:
        if key not in fields:
            continue
        v = fields[key]
        if v is None or v == "":
            continue
        _emit_tlv(out, type_byte, conv(key, v))

    return bytes(out)


def decode(payload: bytes) -> dict:
    """Decode a binary userFields v1 payload into a fields dict.

    Unknown TLV types are preserved under ``extra`` as ``{type:int, value:hex}``.
    """
    if not isinstance(payload, (bytes, bytearray)):
        raise UserFieldsError("payload must be bytes")
    buf = bytes(payload)
    if len(buf) < len(MAGIC) + 1:
        raise UserFieldsError("payload too short")
    if buf[: len(MAGIC)] != MAGIC:
        raise UserFieldsError("magic mismatch")
    version = buf[len(MAGIC)]
    if version != VERSION:
        raise UserFieldsError(f"unsupported version 0x{version:02x}")

    out: dict = {"version": version}
    extra = []
    i = len(MAGIC) + 1
    while i < len(buf):
        if i + 3 > len(buf):
            raise UserFieldsError("truncated TLV header")
        t = buf[i]
        ln = int.from_bytes(buf[i + 1 : i + 3], "big")
        i += 3
        if i + ln > len(buf):
            raise UserFieldsError("truncated TLV value")
        v = buf[i : i + ln]
        i += ln

        if t == T_CONTENT_HASH_ALGO:
            out["contentHashAlgo"] = v.decode("ascii")
        elif t == T_CONTENT_HASH:
            out["contentHash"] = v.hex()
        elif t == T_CONTENT_CID:
            out["contentCid"] = v.decode("ascii")
        elif t == T_DEMO_CID:
            out["demoCid"] = v.decode("ascii")
        elif t == T_MIME:
            out["mime"] = v.decode("ascii")
        elif t == T_SIZE_BYTES:
            if ln != 8:
                raise UserFieldsError("sizeBytes must be 8 bytes")
            out["sizeBytes"] = int.from_bytes(v, "big")
        elif t == T_CONTRACT_ADDRESS:
            out["contractAddress"] = base58.b58encode(v).decode("ascii")
        else:
            extra.append({"type": t, "value": v.hex()})

    if extra:
        out["extra"] = extra
    return out
