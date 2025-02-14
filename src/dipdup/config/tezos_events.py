from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import Alias
from dipdup.config import HandlerConfig
from dipdup.config.tezos import TezosContractConfig
from dipdup.config.tezos import TezosIndexConfig
from dipdup.config.tezos_tzkt import TezosTzktDatasourceConfig
from dipdup.models.tezos_tzkt import EventSubscription
from dipdup.utils import pascal_to_snake
from dipdup.utils import snake_to_pascal

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dipdup.subscriptions import Subscription


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosEventsHandlerConfig(HandlerConfig):
    """Event handler config

    :param callback: Callback name
    :param contract: Contract which emits event
    :param tag: Event tag
    """

    contract: Alias[TezosContractConfig]
    tag: str

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.context', 'HandlerContext'
        yield 'dipdup.models.tezos', 'TezosEvent'
        yield package, 'models as models'

        event_cls = snake_to_pascal(self.tag + '_payload')
        event_module = pascal_to_snake(self.tag)
        module_name = self.contract.module_name
        yield f'{package}.types.{module_name}.tezos_events.{event_module}', event_cls

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        event_cls = snake_to_pascal(self.tag + '_payload')
        yield 'ctx', 'HandlerContext'
        yield 'event', f'TezosEvent[{event_cls}]'


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosEventsUnknownEventHandlerConfig(HandlerConfig):
    """Unknown event handler config

    :param callback: Callback name
    :param contract: Contract which emits event
    """

    contract: Alias[TezosContractConfig]

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.context', 'HandlerContext'
        yield 'dipdup.models.tezos', 'TezosUnknownEvent'
        yield package, 'models as models'

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        yield 'ctx', 'HandlerContext'
        yield 'event', 'TezosUnknownEvent'


TezosEventsHandlerConfigU = TezosEventsHandlerConfig | TezosEventsUnknownEventHandlerConfig


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosEventsIndexConfig(TezosIndexConfig):
    """Event index config

    :param kind: always 'tezos.events'
    :param datasources: `evm` datasources to use
    :param handlers: Event handlers
    :param first_level: First block level to index
    :param last_level: Last block level to index
    """

    kind: Literal['tezos.events'] = 'tezos.events'
    datasources: tuple[Alias[TezosTzktDatasourceConfig], ...]
    handlers: tuple[TezosEventsHandlerConfigU, ...]

    first_level: int = 0
    last_level: int = 0

    def get_subscriptions(self) -> set[Subscription]:
        subs = super().get_subscriptions()
        if self.merge_subscriptions:
            subs.add(EventSubscription())
        else:
            for handler_config in self.handlers:
                address = handler_config.contract.address
                subs.add(EventSubscription(address=address))
        return subs
