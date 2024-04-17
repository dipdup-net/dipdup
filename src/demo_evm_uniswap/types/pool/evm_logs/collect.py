# generated by DipDup 8.0.0a1

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class CollectPayload(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    owner: str
    recipient: str
    tickLower: int
    tickUpper: int
    amount0: int
    amount1: int
