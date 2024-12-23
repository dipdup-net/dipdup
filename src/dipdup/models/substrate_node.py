from abc import ABC
from typing import Literal

from pydantic.dataclasses import dataclass

from dipdup.subscriptions import Subscription


class SubstrateNodeSubscription(ABC, Subscription):
    method: str


@dataclass(frozen=True)
class SubstrateNodeHeadSubscription(SubstrateNodeSubscription):
    method: Literal['chain_subscribeFinalisedHeads'] = 'chain_subscribeFinalisedHeads'
    # NOTE: used to determine which objects index require, since we can only subscribe to head
    fetch_events: bool = False
