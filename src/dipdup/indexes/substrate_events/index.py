from collections import deque
from collections.abc import Iterable
from typing import TYPE_CHECKING
from typing import Any

from dipdup.config.substrate_events import SubstrateEventsHandlerConfig
from dipdup.config.substrate_events import SubstrateEventsIndexConfig
from dipdup.datasources.substrate_node import SubstrateNodeDatasource
from dipdup.datasources.substrate_subsquid import SubstrateSubsquidDatasource
from dipdup.indexes.substrate import SubstrateDatasource
from dipdup.indexes.substrate import SubstrateIndex
from dipdup.indexes.substrate_events.fetcher import SubstrateNodeEventFetcher
from dipdup.indexes.substrate_events.fetcher import SubstrateSubsquidEventFetcher
from dipdup.models import RollbackMessage
from dipdup.models._subsquid import SubsquidMessageType
from dipdup.models.substrate import SubstrateEvent
from dipdup.models.substrate import SubstrateEventData
from dipdup.performance import metrics

QueueItem = tuple[SubstrateEventData, ...] | RollbackMessage
MatchedEventsT = tuple[SubstrateEventsHandlerConfig, SubstrateEvent[Any]]

if TYPE_CHECKING:
    from dipdup.context import DipDupContext


class SubstrateEventsIndex(
    SubstrateIndex[SubstrateEventsIndexConfig, QueueItem, SubstrateDatasource],
    message_type=SubsquidMessageType.substrate_events,
):
    def __init__(
        self,
        ctx: 'DipDupContext',
        config: SubstrateEventsIndexConfig,
        datasources: tuple[SubstrateDatasource, ...],
    ) -> None:
        super().__init__(ctx, config, datasources)
        self._names = tuple(c.name for c in self._config.handlers)
        self.subsquid_datasources = tuple(d for d in datasources if isinstance(d, SubstrateSubsquidDatasource))
        self.node_datasources = tuple(d for d in datasources if isinstance(d, SubstrateNodeDatasource))

    async def _synchronize_subsquid(self, sync_level: int) -> None:
        first_level = self.state.level + 1
        fetcher = self._create_subsquid_fetcher(first_level, sync_level)

        async for _level, events in fetcher.fetch_by_level():
            await self._process_level_data(tuple(events), sync_level)
            metrics._sqd_processor_last_block = int(_level)

    async def _synchronize_node(self, sync_level: int) -> None:
        first_level = self.state.level + 1
        fetcher = self._create_node_fetcher(first_level, sync_level)

        async for _level, events in fetcher.fetch_by_level():
            await self._process_level_data(events, sync_level)
            metrics._sqd_processor_last_block = _level

    def _create_subsquid_fetcher(self, first_level: int, last_level: int) -> SubstrateSubsquidEventFetcher:
        return SubstrateSubsquidEventFetcher(
            name=self.name,
            datasources=self.subsquid_datasources,
            first_level=first_level,
            last_level=last_level,
            names=self._names,
        )

    def _create_node_fetcher(self, first_level: int, last_level: int) -> SubstrateNodeEventFetcher:
        return SubstrateNodeEventFetcher(
            name=self.name,
            datasources=self.node_datasources,
            first_level=first_level,
            last_level=last_level,
        )

    def _match_level_data(
        self,
        handlers: tuple[SubstrateEventsHandlerConfig, ...],
        level_data: Iterable[SubstrateEventData],
    ) -> deque[Any]:
        """Try to match event events with all index handlers."""
        matched_handlers: deque[MatchedEventsT] = deque()

        for event in level_data:
            for handler_config in handlers:
                if handler_config.name != event.name:
                    continue

                arg: SubstrateEvent[Any] = SubstrateEvent(
                    data=event,
                    runtime=self.runtime,
                )

                matched_handlers.append((handler_config, arg))
                break

        return matched_handlers
