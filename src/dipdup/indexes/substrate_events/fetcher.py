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
        for level in range(self._first_level, self._last_level):
            block_hash = await self.get_random_node().get_block_hash(level)
            event_dicts = await self.get_random_node().get_events(block_hash)
            block_header = await self.get_random_node().get_block_header(block_hash)
            yield tuple(SubstrateEventData.from_node(event_dict, block_header) for event_dict in event_dicts)
