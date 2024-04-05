# generated by DipDup 7.5.3

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class Collect(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    owner: str
    recipient: str
    tickLower: int
    tickUpper: int
    amount0: int
    amount1: int
