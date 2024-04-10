# generated by DipDup 7.5.4

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class TzbtcStorage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    big_map: dict[str, str]
    lambda_: str = Field(..., alias='lambda')
    nat: str
    bool: bool
