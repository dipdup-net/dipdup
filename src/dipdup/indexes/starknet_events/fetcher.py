from collections.abc import AsyncIterator

from dipdup.datasources.starknet_subsquid import StarknetSubsquidDatasource
from dipdup.fetcher import readahead_by_level
from dipdup.indexes.starknet_subsquid import StarknetSubsquidFetcher
from dipdup.models.starknet import StarknetEventData

STARKNET_SUBSQUID_READAHEAD_LIMIT = 10000


class StarknetSubsquidEventFetcher(StarknetSubsquidFetcher[StarknetEventData]):
    def __init__(
        self,
        datasources: tuple[StarknetSubsquidDatasource, ...],
        first_level: int,
        last_level: int,
    ) -> None:
        super().__init__(datasources, first_level, last_level)

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[StarknetEventData, ...]]]:
        # TODO: filter events for optimisation
        event_iter = self.random_datasource.iter_events(
            self._first_level,
            self._last_level,
            ()
        )
        async for level, batch in readahead_by_level(event_iter, limit=STARKNET_SUBSQUID_READAHEAD_LIMIT):
            yield level, batch
