from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Literal
from typing import cast

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import Alias
from dipdup.config import HandlerConfig
from dipdup.config.substrate import SubstrateDatasourceConfigU
from dipdup.config.substrate import SubstrateIndexConfig
from dipdup.config.substrate import SubstrateRuntimeConfig
from dipdup.models.substrate_node import SubstrateNodeHeadSubscription
from dipdup.utils import pascal_to_snake
from dipdup.utils import snake_to_pascal

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dipdup.subscriptions import Subscription


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SubstrateEventsHandlerConfig(HandlerConfig):
    """Subsquid event handler

    :param callback: Callback name
    :param name: Event name (pallet.event)
    """

    name: str

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.context', 'HandlerContext'
        yield 'dipdup.models.substrate', 'SubstrateEvent'
        yield package, 'models as models'

        event_cls = snake_to_pascal(self.name) + 'Payload'
        event_module = pascal_to_snake(self.name.replace('.', ''))

        parent = cast(SubstrateIndexConfig, self.parent)
        yield f'{package}.types.{parent.runtime.name}.substrate_events.{event_module}', event_cls

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        event_cls = snake_to_pascal(self.name) + 'Payload'
        yield 'ctx', 'HandlerContext'
        yield 'event', f'SubstrateEvent[{event_cls}]'


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SubstrateEventsIndexConfig(SubstrateIndexConfig):
    """Subsquid datasource config

    :param kind: Always 'substrate.events'
    :param datasources: `substrate` datasources to use
    :param handlers: Event handlers
    :param first_level: Level to start indexing from
    :param last_level: Level to stop indexing and disable this index
    :param typename: Alias for pallet interface
    :param runtime: Substrate runtime
    """

    kind: Literal['substrate.events']
    datasources: tuple[Alias[SubstrateDatasourceConfigU], ...]
    handlers: tuple[SubstrateEventsHandlerConfig, ...]
    runtime: Alias[SubstrateRuntimeConfig]

    first_level: int = 0
    last_level: int = 0

    def get_subscriptions(self) -> set[Subscription]:
        return {SubstrateNodeHeadSubscription(fetch_events=True)}
