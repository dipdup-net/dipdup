# generated by DipDup 8.1.2

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class InitializePayload(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    sqrtPriceX96: int
    tick: int
