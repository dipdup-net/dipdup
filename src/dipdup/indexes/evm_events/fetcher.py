import time
from collections.abc import AsyncIterator

from dipdup.datasources.evm_node import EvmNodeDatasource
from dipdup.datasources.evm_subsquid import EvmSubsquidDatasource
from dipdup.indexes.evm_node import MIN_BATCH_SIZE
from dipdup.indexes.evm_node import EvmNodeFetcher
from dipdup.indexes.evm_subsquid import EvmSubsquidFetcher
from dipdup.models.evm import EvmEventData


class EvmSubsquidEventFetcher(EvmSubsquidFetcher[EvmEventData]):
    def __init__(
        self,
        name: str,
        datasources: tuple[EvmSubsquidDatasource, ...],
        first_level: int,
        last_level: int,
        topics: tuple[tuple[str | None, str], ...],
    ) -> None:
        super().__init__(
            name=name,
            datasources=datasources,
            first_level=first_level,
            last_level=last_level,
        )
        self._topics = topics

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[EvmEventData, ...]]]:
        event_iter = self.random_datasource.iter_events(
            self._topics,
            self._first_level,
            self._last_level,
        )
        async for level, batch in self.readahead_by_level(event_iter):
            yield level, batch


class EvmNodeEventFetcher(EvmNodeFetcher[EvmEventData]):

    def __init__(
        self,
        name: str,
        datasources: tuple[EvmNodeDatasource, ...],
        first_level: int,
        last_level: int,
        addresses: set[str],
    ) -> None:
        super().__init__(
            name=name,
            datasources=datasources,
            first_level=first_level,
            last_level=last_level,
        )
        self._addresses = addresses

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[EvmEventData, ...]]]:
        event_iter = self._fetch_by_level()
        async for level, batch in self.readahead_by_level(event_iter):
            yield level, batch

    async def _fetch_by_level(self) -> AsyncIterator[tuple[EvmEventData, ...]]:
        batch_size = MIN_BATCH_SIZE
        batch_first_level = self._first_level
        ratelimited: bool = False

        while batch_first_level <= self._last_level:
            node = self.random_datasource
            batch_size = self.get_next_batch_size(batch_size, ratelimited)
            ratelimited = False

            started = time.time()

            batch_last_level = min(
                batch_first_level + batch_size,
                self._last_level,
            )
            event_batch = await self.get_events_batch(
                first_level=batch_first_level,
                last_level=batch_last_level,
                addresses=self._addresses,
                node=node,
            )

            finished = time.time()
            if finished - started >= node._http_config.ratelimit_sleep:
                ratelimited = True

            timestamps: dict[int, int] = {}
            event_levels = list(event_batch.keys())

            # NOTE: Split event_levels to chunks of batch_size
            event_level_batches = [
                set(event_levels[i : i + batch_size]) for i in range(0, len(event_levels), batch_size)
            ]

            for event_level_batch in event_level_batches:

                started = time.time()

                block_batch = await self.get_blocks_batch(event_level_batch)
                for level, block in block_batch.items():
                    timestamps[level] = int(block['timestamp'], 16)

                finished = time.time()
                if finished - started >= node._http_config.ratelimit_sleep:
                    ratelimited = True

            for level, level_events in event_batch.items():
                if not level_events:
                    continue

                parsed_level_events = tuple(
                    EvmEventData.from_node_json(event, timestamps[level]) for event in level_events
                )

                yield parsed_level_events

            batch_first_level = batch_last_level + 1
