# generated by datamodel-codegen:
#   filename:  tezos_storage.json

from __future__ import annotations

from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel
from pydantic import ConfigDict


class Records(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    address: Optional[str] = None
    data: Dict[str, str]
    expiry_key: Optional[str] = None
    internal_data: Dict[str, str]
    level: str
    owner: str
    tzip12_token_id: Optional[str] = None


class ReverseRecords(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    internal_data: Dict[str, str]
    name: Optional[str] = None
    owner: str


class Store(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    data: Dict[str, str]
    expiry_map: Dict[str, str]
    metadata: Dict[str, str]
    next_tzip12_token_id: str
    owner: str
    records: Dict[str, Records]
    reverse_records: Dict[str, ReverseRecords]
    tzip12_tokens: Dict[str, str]


class NameRegistryStorage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    actions: Dict[str, str]
    store: Store
    trusted_senders: List[str]
