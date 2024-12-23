from abc import ABC
from typing import Generic

from dipdup.datasources.substrate_subsquid import SubstrateSubsquidDatasource
from dipdup.fetcher import BufferT
from dipdup.fetcher import DataFetcher

SUBSTRATE_SUBSQUID_READAHEAD_LIMIT = 10000


class SubstrateSubsquidFetcher(Generic[BufferT], DataFetcher[BufferT, SubstrateSubsquidDatasource], ABC):
    def __init__(
        self,
        name: str,
        datasources: tuple[SubstrateSubsquidDatasource, ...],
        first_level: int,
        last_level: int,
    ) -> None:
        super().__init__(
            name=name,
            datasources=datasources,
            first_level=first_level,
            last_level=last_level,
            readahead_limit=SUBSTRATE_SUBSQUID_READAHEAD_LIMIT,
        )
