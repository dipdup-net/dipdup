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
from dipdup.models.tezos_tzkt import TokenTransferSubscription

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dipdup.subscriptions import Subscription


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosTokenTransfersHandlerConfig(HandlerConfig):
    """Token transfer handler config

    :param callback: Callback name
    :param contract: Filter by contract
    :param token_id: Filter by token ID
    :param from_: Filter by sender
    :param to: Filter by recipient
    """

    contract: Alias[TezosContractConfig] | None = None
    token_id: int | None = None
    # FIXME: Can't use `from_` field alias in dataclasses
    from_: Alias[TezosContractConfig] | None = None
    to: Alias[TezosContractConfig] | None = None

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.context', 'HandlerContext'
        yield 'dipdup.models.tezos', 'TezosTokenTransferData'
        yield package, 'models as models'

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        yield 'ctx', 'HandlerContext'
        yield 'token_transfer', 'TezosTokenTransferData'


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosTokenTransfersIndexConfig(TezosIndexConfig):
    """Token transfer index config

    :param kind: always 'tezos.token_transfers'
    :param datasources: `tezos` datasources to use
    :param handlers: Mapping of token transfer handlers

    :param first_level: Level to start indexing from
    :param last_level: Level to stop indexing at
    """

    kind: Literal['tezos.token_transfers'] = 'tezos.token_transfers'
    datasources: tuple[Alias[TezosTzktDatasourceConfig], ...]
    handlers: tuple[TezosTokenTransfersHandlerConfig, ...]

    first_level: int = 0
    last_level: int = 0

    def get_subscriptions(self) -> set[Subscription]:
        subs = super().get_subscriptions()
        if self.merge_subscriptions:
            subs.add(TokenTransferSubscription())  # type: ignore[call-arg]
        else:
            for handler_config in self.handlers:
                contract = (
                    handler_config.contract.address if isinstance(handler_config.contract, ContractConfig) else None
                )
                from_ = handler_config.from_.address if isinstance(handler_config.from_, ContractConfig) else None
                to = handler_config.to.address if isinstance(handler_config.to, ContractConfig) else None
                subs.add(
                    TokenTransferSubscription(
                        contract=contract,
                        from_=from_,
                        to=to,
                        token_id=handler_config.token_id,
                    )
                )
        return subs
