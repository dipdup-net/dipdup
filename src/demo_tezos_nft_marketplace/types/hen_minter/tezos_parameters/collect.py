# generated by DipDup 8.2.0rc1

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class CollectParameter(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    objkt_amount: str
    swap_id: str
