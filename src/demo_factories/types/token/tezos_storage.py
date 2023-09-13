# generated by datamodel-codegen:
#   filename:  tezos_storage.json

from __future__ import annotations

from typing import Dict
from typing import List

from pydantic import BaseModel
from pydantic import Extra


class TokenMetadata(BaseModel):
    class Config:
        extra = Extra.forbid

    token_id: str
    token_info: Dict[str, str]


class TokenStorage(BaseModel):
    class Config:
        extra = Extra.forbid

    ledger: Dict[str, str]
    operators: Dict[str, List[str]]
    total_supply: str
    metadata: Dict[str, str]
    token_metadata: Dict[str, TokenMetadata]
    admin: str
