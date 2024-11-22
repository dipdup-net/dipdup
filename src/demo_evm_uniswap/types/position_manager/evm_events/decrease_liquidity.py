# generated by DipDup 8.1.2

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class DecreaseLiquidityPayload(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    tokenId: int
    liquidity: int
    amount0: int
    amount1: int
