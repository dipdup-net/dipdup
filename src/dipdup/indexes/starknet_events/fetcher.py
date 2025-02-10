import logging
import random
from collections.abc import AsyncIterator
from typing import Any

from dipdup.datasources.starknet_node import StarknetNodeDatasource
from dipdup.datasources.starknet_subsquid import StarknetSubsquidDatasource
from dipdup.exceptions import FrameworkException
from dipdup.fetcher import FetcherChannel
from dipdup.indexes.starknet_node import StarknetNodeFetcher
from dipdup.indexes.starknet_subsquid import StarknetSubsquidFetcher
from dipdup.models.starknet import StarknetEventData
from dipdup.models.starknet_subsquid import EventRequest

_logger = logging.getLogger(__name__)


class StarknetSubsquidEventFetcher(StarknetSubsquidFetcher[StarknetEventData]):
    def __init__(
        self,
        name: str,
        datasources: tuple[StarknetSubsquidDatasource, ...],
        first_level: int,
        last_level: int,
        event_ids: dict[str, set[str]],
    ) -> None:
        super().__init__(
            name=name,
            datasources=datasources,
            first_level=first_level,
            last_level=last_level,
        )
        self._event_ids = event_ids

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[StarknetEventData, ...]]]:
        filters: tuple[EventRequest, ...] = tuple(
            {
                'key0': list(ids),
                'fromAddress': [address],
            }
            for address, ids in self._event_ids.items()
        )
        event_iter = self.random_datasource.iter_events(
            first_level=self._first_level,
            last_level=self._last_level,
            filters=filters,
        )
        async for level, batch in self.readahead_by_level(event_iter):
            yield level, batch


class EventFetcherChannel(FetcherChannel[StarknetEventData, StarknetNodeDatasource, tuple[str, tuple[str, ...]]]):

    _offset: str | None

    async def fetch(self) -> None:
        address, key0s = next(iter(self._filter))
        
        datasource = self._datasources[0]

        events_chunk = await datasource.get_events(
            address=address,
            keys=[list(key0s), [], []],
            first_level=self._first_level,
            last_level=self._last_level,
            continuation_token=self._offset or None,
        )

        for event in events_chunk.events:
            # NOTE: 
            if event.block_hash is None or event.transaction_hash is None:
                _logger.info("Skipping event. No block_hash or transaction_hash found in %s", event)
                continue

            block = await datasource.get_block_with_tx_hashes(
                block_hash=event.block_hash,
            )

            if block is None:
                _logger.info("Skipping event. No block exists for block_hash. BlackHash=%s", event.block_hash)
                continue

            timestamp = block.timestamp
            transaction_idx = block.transactions.index(event.transaction_hash)

            # NOTE: This event is corrupt, possibly due to old age.
            if transaction_idx < 0:
                _logger.info("Skipping event. No transaction_hash exists in block. TxHash=%s", event.transaction_hash)
                continue

            self._buffer[event.block_number].append(  # type: ignore[index]
                StarknetEventData.from_starknetpy(
                    event=event,
                    transaction_index=transaction_idx,
                    timestamp=timestamp,
                )
            )

        if events_chunk.continuation_token:
            self._offset = events_chunk.continuation_token
            if events_chunk.events:
                self._head = events_chunk.events[-1].block_number  # type: ignore[assignment]
        else:
            self._head = self._last_level
            self._offset = None


class StarknetNodeEventFetcher(StarknetNodeFetcher[StarknetEventData]):
    def __init__(
        self,
        name: str,
        datasources: tuple[StarknetNodeDatasource, ...],
        first_level: int,
        last_level: int,
        event_ids: dict[str, set[str]],
    ) -> None:
        super().__init__(name, datasources, first_level, last_level)
        self._event_ids = event_ids

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[StarknetEventData, ...]]]:
        channels: set[FetcherChannel[Any, Any, Any]] = set()
        for address, key0s in self._event_ids.items():
            filter = set()
            filter.add((address, tuple(key0s)))
            channel = EventFetcherChannel(
                buffer=self._buffer,
                filter=filter,
                first_level=self._first_level,
                last_level=self._last_level,
                # NOTE: Fixed datasource to use continuation token
                datasources=(self.get_random_node(),),
            )
            channels.add(channel)

        events_iter = self._merged_iter(
            channels, lambda i: tuple(sorted(i, key=lambda x: f'{x.block_number}_{x.transaction_index}'))
        )
        async for level, batch in self.readahead_by_level(events_iter):
            yield level, batch

    def get_random_node(self) -> StarknetNodeDatasource:
        if not self._datasources:
            raise FrameworkException('A node datasource requested, but none attached to this index')
        return random.choice(self._datasources)
