"""Pydantic models riusabili per i payload MCP <-> gateway.

Il gateway accetta sia camelCase (`publicKey`) sia PascalCase (`PublicKey`).
Manteniamo lo stesso comportamento con `populate_by_name` + alias.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class PublicKeyInput(_Base):
    public_key: str = Field(alias="PublicKey", description="Base58-encoded wallet public key")


class PaginatedInput(PublicKeyInput):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=500)


class TokenAddressInput(_Base):
    token: str = Field(description="Base58-encoded token contract address")


class TransactionIdInput(_Base):
    transaction_id: str = Field(
        alias="transactionId",
        pattern=r"^\d+\.\d+$",
        description="Format: <poolSeq>.<index1>",
    )


class TransferIntent(_Base):
    """Campi comuni a Transaction/Pack e Transaction/Execute."""
    public_key: str = Field(alias="PublicKey")
    receiver_public_key: str = Field(alias="ReceiverPublicKey")
    amount_as_string: str = Field(alias="amountAsString", default="0")
    fee_as_string: str = Field(alias="feeAsString", default="0")
    user_data: str = Field(alias="UserData", default="")
    delegate_enable: Optional[bool] = Field(alias="DelegateEnable", default=False)
    delegate_disable: Optional[bool] = Field(alias="DelegateDisable", default=False)
    date_expired_utc: Optional[str] = Field(alias="DateExpiredUtc", default="")
