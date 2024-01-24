# generated by datamodel-codegen:
#   filename:  tezos_storage.json

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import Extra


class Key(BaseModel):
    class Config:
        extra = Extra.forbid

    address: str
    nat: str


class LedgerItem(BaseModel):
    class Config:
        extra = Extra.forbid

    key: Key
    value: str


class Key1(BaseModel):
    class Config:
        extra = Extra.forbid

    owner: str
    operator: str
    token_id: str


class Operator(BaseModel):
    class Config:
        extra = Extra.forbid

    key: Key1
    value: dict[str, Any]


class TokenMetadata(BaseModel):
    class Config:
        extra = Extra.forbid

    token_id: str
    token_info: dict[str, str]


class TokenStorage(BaseModel):
    class Config:
        extra = Extra.forbid

    administrator: str
    all_tokens: str
    isMinter1Locked: bool
    isMinter2Locked: bool
    ledger: list[LedgerItem]
    metadata: dict[str, str]
    minter1: str
    minter2: str
    operators: list[Operator]
    paused: bool
    token_metadata: dict[str, TokenMetadata]
