from collections import deque
from collections.abc import Iterable
from typing import Any

from dipdup.config.evm_events import EvmEventsHandlerConfig
from dipdup.config.evm_events import EvmEventsIndexConfig
from dipdup.datasources.evm_node import EvmNodeDatasource
from dipdup.datasources.evm_subsquid import EvmSubsquidDatasource
from dipdup.exceptions import FrameworkException
from dipdup.indexes.evm import EvmIndex
from dipdup.indexes.evm_events.fetcher import EvmNodeEventFetcher
from dipdup.indexes.evm_events.fetcher import EvmSubsquidEventFetcher
from dipdup.indexes.evm_events.matcher import match_events
from dipdup.models import RollbackMessage
from dipdup.models._subsquid import SubsquidMessageType
from dipdup.models.evm import EvmEventData
from dipdup.performance import metrics

QueueItem = tuple[EvmEventData, ...] | RollbackMessage
EvmDatasource = EvmSubsquidDatasource | EvmNodeDatasource


class EvmEventsIndex(
    EvmIndex[EvmEventsIndexConfig, QueueItem, EvmDatasource],
    message_type=SubsquidMessageType.evm_logs,
):

    async def _synchronize_subsquid(self, sync_level: int) -> None:
        first_level = self.state.level + 1
        fetcher = self._create_subsquid_fetcher(first_level, sync_level)

        async for _level, logs in fetcher.fetch_by_level():
            await self._process_level_data(logs, sync_level)
            metrics._sqd_processor_last_block = _level

    async def _synchronize_node(self, sync_level: int) -> None:
        first_level = self.state.level + 1
        fetcher = self._create_node_fetcher(first_level, sync_level)

        async for _level, logs in fetcher.fetch_by_level():
            await self._process_level_data(logs, sync_level)
            metrics._sqd_processor_last_block = _level

    def _create_subsquid_fetcher(self, first_level: int, last_level: int) -> EvmSubsquidEventFetcher:
        addresses = set()
        topics: deque[tuple[str | None, str]] = deque()

        for handler_config in self._config.handlers:
            address = handler_config.contract.address
            if address is not None:
                addresses.add(address)
            elif handler_config.contract.abi is None:
                raise NotImplementedError('Either contract address or ABI must be specified')

            event_abi = self._abis.get_event_abi(
                typename=handler_config.contract.module_name,
                name=handler_config.name,
            )
            topics.append((address, event_abi['topic0']))

        if not self.subsquid_datasources:
            raise FrameworkException('Creating EvmSubsquidEventFetcher, but no `evm.subsquid` datasources available')

        return EvmSubsquidEventFetcher(
            name=self.name,
            datasources=self.subsquid_datasources,
            first_level=first_level,
            last_level=last_level,
            topics=tuple(topics),
        )

    def _create_node_fetcher(self, first_level: int, last_level: int) -> EvmNodeEventFetcher:
        if not self.node_datasources:
            raise FrameworkException('Creating EvmNodeEventFetcher, but no `evm.node` datasources available')

        addresses = set()
        for handler_config in self._config.handlers:
            if handler_config.contract.address:
                addresses.add(handler_config.contract.address)
            else:
                addresses.clear()
                break

        return EvmNodeEventFetcher(
            name=self.name,
            datasources=self.node_datasources,
            first_level=first_level,
            last_level=last_level,
            addresses=addresses,
        )

    def _match_level_data(
        self,
        handlers: tuple[EvmEventsHandlerConfig, ...],
        level_data: Iterable[EvmEventData],
    ) -> deque[Any]:
        return match_events(
            package=self._ctx.package,
            handlers=handlers,
            events=level_data,
        )
