# generated by DipDup 8.2.0

from __future__ import annotations

from pydantic import BaseModel


class CollectPayload(BaseModel):
    tokenId: int
    recipient: str
    amount0: int
    amount1: int
