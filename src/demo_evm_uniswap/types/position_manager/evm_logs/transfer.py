# generated by DipDup 8.0.0a1

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class TransferPayload(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    from_: str = Field(..., alias='from')
    to: str
    tokenId: int
