# generated by datamodel-codegen:
#   filename:  storage.json

from __future__ import annotations

from typing import Dict
from typing import List

from pydantic import ConfigDict, BaseModel


class Key(BaseModel):
    model_config = ConfigDict(extra="forbid")

    string: str
    nat: str


class AsdfStorageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Key
    value: str


class AsdfStorage(BaseModel):
    root: List[Dict[str, List[AsdfStorageItem]]]
