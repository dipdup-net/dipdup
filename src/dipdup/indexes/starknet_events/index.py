from collections import deque
from collections.abc import Iterable
from typing import TYPE_CHECKING
from typing import Any

from dipdup.config.starknet_events import StarknetEventsHandlerConfig
from dipdup.config.starknet_events import StarknetEventsIndexConfig
from dipdup.exceptions import ConfigInitializationException
from dipdup.exceptions import FrameworkException
from dipdup.indexes.starknet import StarknetDatasource
from dipdup.indexes.starknet import StarknetIndex
from dipdup.indexes.starknet_events.fetcher import StarknetNodeEventFetcher
from dipdup.indexes.starknet_events.fetcher import StarknetSubsquidEventFetcher
from dipdup.indexes.starknet_events.matcher import match_events
from dipdup.models import RollbackMessage
from dipdup.models._subsquid import SubsquidMessageType
from dipdup.models.starknet import StarknetEventData
from dipdup.performance import metrics

QueueItem = tuple[StarknetEventData, ...] | RollbackMessage

if TYPE_CHECKING:
    from dipdup.context import DipDupContext


class StarknetEventsIndex(
    StarknetIndex[StarknetEventsIndexConfig, QueueItem, StarknetDatasource],
    message_type=SubsquidMessageType.starknet_events,
):
    def __init__(
        self,
        ctx: 'DipDupContext',
        config: StarknetEventsIndexConfig,
        datasources: tuple[StarknetDatasource, ...],
    ) -> None:
        super().__init__(ctx, config, datasources)
        self._event_identifiers: dict[str, dict[str, str]] | None = None

    @property
    def event_identifiers(self) -> dict[str, dict[str, str]]:
        if self._event_identifiers is None:
            self._event_identifiers = {}
            for handler_config in self._config.handlers:
                typename = handler_config.contract.module_name
                event_abi = self._cairo_abis.get_event_abi(
                    typename=typename,
                    name=handler_config.name,
                )
                if typename not in self._event_identifiers:
                    self._event_identifiers[typename] = {}
                self._event_identifiers[typename][handler_config.name] = event_abi['event_identifier']
        return self._event_identifiers

    async def _synchronize_subsquid(self, sync_level: int) -> None:
        first_level = self.state.level + 1
        fetcher = self._create_subsquid_fetcher(first_level, sync_level)

        async for _level, events in fetcher.fetch_by_level():
            await self._process_level_data(events, sync_level)
            metrics._sqd_processor_last_block = _level

    async def _synchronize_node(self, sync_level: int) -> None:
        first_level = self.state.level + 1
        fetcher = self._create_node_fetcher(first_level, sync_level)

        async for _level, events in fetcher.fetch_by_level():
            await self._process_level_data(events, sync_level)
            metrics._sqd_processor_last_block = _level

    def _create_subsquid_fetcher(self, first_level: int, last_level: int) -> StarknetSubsquidEventFetcher:
        event_ids: dict[str, set[str]] = {}
        for handler_config in self._config.handlers:
            if not handler_config.contract.address:
                raise ConfigInitializationException
            typename = handler_config.contract.module_name
            event_abi = self._cairo_abis.get_event_abi(
                typename=typename,
                name=handler_config.name,
            )

            if handler_config.contract.address not in event_ids:
                event_ids[handler_config.contract.address] = set()
            event_ids[handler_config.contract.address].add(event_abi['event_identifier'])

        return StarknetSubsquidEventFetcher(
            name=self.name,
            datasources=self.subsquid_datasources,
            first_level=first_level,
            last_level=last_level,
            event_ids=event_ids,
        )

    def _create_node_fetcher(self, first_level: int, last_level: int) -> StarknetNodeEventFetcher:
        if not self.node_datasources:
            raise FrameworkException('Creating StarknetNodeEventFetcher, but no `starknet.node` datasources available')

        event_ids: dict[str, set[str]] = {}
        for handler_config in self._config.handlers:
            if not handler_config.contract.address:
                raise ConfigInitializationException
            typename = handler_config.contract.module_name
            event_abi = self._cairo_abis.get_event_abi(
                typename=typename,
                name=handler_config.name,
            )

            if handler_config.contract.address not in event_ids:
                event_ids[handler_config.contract.address] = set()
            event_ids[handler_config.contract.address].add(event_abi['event_identifier'])

        return StarknetNodeEventFetcher(
            name=self.name,
            datasources=self.node_datasources,
            first_level=first_level,
            last_level=last_level,
            event_ids=event_ids,
        )

    def _match_level_data(
        self,
        handlers: tuple[StarknetEventsHandlerConfig, ...],
        level_data: Iterable[StarknetEventData],
    ) -> deque[Any]:
        return match_events(
            package=self._ctx.package,
            handlers=handlers,
            events=level_data,
            event_identifiers=self.event_identifiers,
        )
