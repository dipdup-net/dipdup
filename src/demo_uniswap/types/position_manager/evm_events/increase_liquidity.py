# generated by datamodel-codegen:
#   filename:  IncreaseLiquidity.json

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class IncreaseLiquidity(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    tokenId: int
    liquidity: int
    amount0: int
    amount1: int
