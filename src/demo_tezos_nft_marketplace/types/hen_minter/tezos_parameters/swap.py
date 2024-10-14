# generated by DipDup 8.0.0

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class SwapParameter(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    objkt_amount: str
    objkt_id: str
    xtz_per_objkt: str
