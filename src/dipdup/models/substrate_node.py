from abc import ABC
from typing import Any
from typing import Literal

from pydantic.dataclasses import dataclass

from dipdup.subscriptions import Subscription


class SubstrateNodeSubscription(ABC, Subscription):
    name: str

    def get_params(self) -> list[Any]:
        return [self.name]


@dataclass(frozen=True)
class SubstrateNodeHeadSubscription(SubstrateNodeSubscription):
    name: Literal['finalisedHeads'] = 'finalisedHeads'
    method: Literal['chain_subscribeFinalisedHeads'] = 'chain_subscribeFinalisedHeads'
