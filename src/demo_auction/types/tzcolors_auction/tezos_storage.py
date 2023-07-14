# generated by datamodel-codegen:
#   filename:  tezos_storage.json

from __future__ import annotations

from typing import Dict
from typing import Optional

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import RootModel


class TzcolorsAuctionStorage1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    token_address: str
    token_id: str
    token_amount: str
    end_timestamp: str
    seller: str
    bid_amount: str
    bidder: str


class TzcolorsAuctionStorage(RootModel):
    root: Optional[Dict[str, TzcolorsAuctionStorage1]] = None
