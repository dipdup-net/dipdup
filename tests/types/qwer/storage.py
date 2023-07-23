# generated by datamodel-codegen:
#   filename:  storage.json

from __future__ import annotations

from typing import Dict
from typing import List
from typing import Union

from pydantic import BaseModel
from pydantic import ConfigDict


class QwerStorageItem(BaseModel):
    model_config = ConfigDict(extra='forbid')

    L: str


class QwerStorageItem1(BaseModel):
    model_config = ConfigDict(extra='forbid')

    R: Dict[str, str]


class QwerStorage(BaseModel):
    root: List[List[Union[QwerStorageItem, QwerStorageItem1]]]
