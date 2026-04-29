import pytest
from pydantic import ValidationError
from baba_mcp.schemas import PublicKeyInput, PaginatedInput


def test_public_key_required():
    with pytest.raises(ValidationError):
        PublicKeyInput()

def test_public_key_accepts_alias():
    m = PublicKeyInput.model_validate({"PublicKey": "abc"})
    assert m.public_key == "abc"

def test_paginated_defaults():
    m = PaginatedInput.model_validate({"PublicKey": "abc"})
    assert m.offset == 0
    assert m.limit == 10
