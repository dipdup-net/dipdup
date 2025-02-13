from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import Alias
from dipdup.config import ContractConfig
from dipdup.config import HandlerConfig
from dipdup.config.tezos import TezosContractConfig
from dipdup.config.tezos import TezosIndexConfig
from dipdup.config.tezos_tzkt import TezosTzktDatasourceConfig
from dipdup.models.tezos_tzkt import TokenBalanceSubscription

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dipdup.subscriptions import Subscription


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosTokenBalancesHandlerConfig(HandlerConfig):
    """Token balance handler config

    :param callback: Callback name
    :param contract: Filter by contract
    :param token_id: Filter by token ID
    """

    contract: Alias[TezosContractConfig] | None = None
    token_id: int | None = None

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        """This iterator result will be used in codegen to generate handler(s) template"""
        yield 'dipdup.context', 'HandlerContext'
        yield 'dipdup.models.tezos', 'TezosTokenBalanceData'
        yield package, 'models as models'

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        """This iterator result will be used in codegen to generate handler(s) template"""
        yield 'ctx', 'HandlerContext'
        yield 'token_balance', 'TezosTokenBalanceData'


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosTokenBalancesIndexConfig(TezosIndexConfig):
    """Token balance index config

    :param kind: always 'tezos.token_balances'
    :param datasources: `tezos` datasources to use
    :param handlers: Mapping of token transfer handlers

    :param first_level: Level to start indexing from
    :param last_level: Level to stop indexing at
    """

    kind: Literal['tezos.token_balances'] = 'tezos.token_balances'
    datasources: tuple[Alias[TezosTzktDatasourceConfig], ...]
    handlers: tuple[TezosTokenBalancesHandlerConfig, ...]

    first_level: int = 0
    last_level: int = 0

    def get_subscriptions(self) -> set[Subscription]:
        subs = super().get_subscriptions()
        if self.merge_subscriptions:
            subs.add(TokenBalanceSubscription())
        else:
            for handler_config in self.handlers:
                contract = (
                    handler_config.contract.address if isinstance(handler_config.contract, ContractConfig) else None
                )
                subs.add(
                    TokenBalanceSubscription(
                        contract=contract,
                        token_id=handler_config.token_id,
                    )
                )
        return subs
