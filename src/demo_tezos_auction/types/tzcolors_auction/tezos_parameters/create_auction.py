# generated by DipDup 8.0.0

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class CreateAuctionParameter(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    auction_id: str
    bid_amount: str
    end_timestamp: str
    token_address: str
    token_amount: str
    token_id: str
