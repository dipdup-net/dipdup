# generated by DipDup 8.2.0

from __future__ import annotations

from pydantic import BaseModel


class BurnPayload(BaseModel):
    owner: str
    tickLower: int
    tickUpper: int
    amount: int
    amount0: int
    amount1: int
