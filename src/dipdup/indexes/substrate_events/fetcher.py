import asyncio
from collections.abc import AsyncIterator

from dipdup.datasources.substrate_node import SubstrateNodeDatasource
from dipdup.datasources.substrate_subsquid import SubstrateSubsquidDatasource
from dipdup.indexes.substrate_node import SubstrateNodeFetcher
from dipdup.indexes.substrate_subsquid import SubstrateSubsquidFetcher
from dipdup.models.substrate import SubstrateEventData


class SubstrateSubsquidEventFetcher(SubstrateSubsquidFetcher[SubstrateEventData]):
    def __init__(
        self,
        name: str,
        datasources: tuple[SubstrateSubsquidDatasource, ...],
        first_level: int,
        last_level: int,
        names: tuple[str, ...],
    ) -> None:
        super().__init__(
            name=name,
            datasources=datasources,
            first_level=first_level,
            last_level=last_level,
        )
        self._names = names

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[SubstrateEventData, ...]]]:
        async for level, events in self.readahead_by_level(self.fetch_events()):
            yield level, events

    async def fetch_events(self) -> AsyncIterator[tuple[SubstrateEventData, ...]]:
        async for events in self.random_datasource.iter_events(
            first_level=self._first_level,
            last_level=self._last_level,
            names=self._names,
        ):
            yield tuple(SubstrateEventData.from_subsquid(event) for event in events)


class SubstrateNodeEventFetcher(SubstrateNodeFetcher[SubstrateEventData]):
    def __init__(
        self,
        name: str,
        datasources: tuple[SubstrateNodeDatasource, ...],
        first_level: int,
        last_level: int,
    ) -> None:
        super().__init__(
            name=name,
            datasources=datasources,
            first_level=first_level,
            last_level=last_level,
        )

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[SubstrateEventData, ...]]]:
        async for level, events in self.readahead_by_level(self.fetch_events()):
            yield level, events

    async def fetch_events(self) -> AsyncIterator[tuple[SubstrateEventData, ...]]:
        node = self.get_random_node()
        batch_size = node._http_config.batch_size

        for batch_start in range(self._first_level, self._last_level, batch_size):
            batch_end = min(batch_start + batch_size, self._last_level)

            block_hashes = await asyncio.gather(
                *(node.get_block_hash(level) for level in range(batch_start, batch_end)),
            )
            block_headers = await asyncio.gather(
                *(node.get_block_header(hash_) for hash_ in block_hashes),
            )
            for block_hash, block_header in zip(block_hashes, block_headers, strict=True):
                event_dicts = await self.get_random_node().get_events(block_hash)
                yield tuple(SubstrateEventData.from_node(event_dict, block_header) for event_dict in event_dicts)
