from collections.abc import AsyncIterator

from dipdup.datasources.substrate_node import SubstrateNodeDatasource
from dipdup.datasources.substrate_subsquid import SubstrateSubsquidDatasource
from dipdup.indexes.substrate_node import SubstrateNodeFetcher
from dipdup.indexes.substrate_subsquid import SubstrateSubsquidFetcher
from dipdup.models.substrate import SubstrateEventData
from dipdup.runtimes import SubstrateRuntime


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
        event_iter = self.random_datasource.iter_events(
            first_level=self._first_level,
            last_level=self._last_level,
            names=self._names,
        )
        async for level, batch in self.readahead_by_level(event_iter):
            yield level, batch


class SubstrateNodeEventFetcher(SubstrateNodeFetcher[SubstrateEventData]):
    def __init__(
        self,
        name: str,
        datasources: tuple[SubstrateNodeDatasource, ...],
        runtime: SubstrateRuntime,
        first_level: int,
        last_level: int,
    ) -> None:
        super().__init__(
            name=name,
            datasources=datasources,
            first_level=first_level,
            last_level=last_level,
        )
        # FIXME: ensure decoder is set for correct runtime scope
        self.decoder = runtime

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[SubstrateEventData, ...]]]:
        # TODO: add event type from runtime to fetchevent
        async for level, event in self.readahead_by_level(self.fetch_events()):
            # TODO: convert block to event data
            yield level, event

    async def fetch_events(self) -> AsyncIterator[tuple[int, tuple[SubstrateEventData, ...]]]:
        for level in range(self._first_level, self._last_level):
            yield level, await self.get_random_node().get_events(level, self.decoder)
