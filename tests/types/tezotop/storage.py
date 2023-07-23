# generated by datamodel-codegen:
#   filename:  storage.json

from __future__ import annotations

from typing import Dict
from typing import List
from typing import Optional

from pydantic import ConfigDict, BaseModel


class ResourceMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    rate: str


class ResourceCollectorStorage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    administrator: str
    current_user: Optional[str]
    default_start_time: str
    generation_rate: str
    managers: List[str]
    metadata: Dict[str, str]
    nft_registry: str
    paused: bool
    resource_map: Dict[str, ResourceMap]
    resource_registry: str
    tezotop_collection: Dict[str, str]
