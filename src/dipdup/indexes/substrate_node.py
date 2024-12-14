import logging
import random
from abc import ABC
from typing import Generic

from dipdup.datasources.substrate_node import SubstrateNodeDatasource
from dipdup.exceptions import FrameworkException
from dipdup.fetcher import BufferT
from dipdup.fetcher import DataFetcher

SUBSTRATE_NODE_READAHEAD_LIMIT = 2500


_logger = logging.getLogger(__name__)


class SubstrateNodeFetcher(Generic[BufferT], DataFetcher[BufferT, SubstrateNodeDatasource], ABC):
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
            readahead_limit=SUBSTRATE_NODE_READAHEAD_LIMIT,
        )

    def get_random_node(self) -> SubstrateNodeDatasource:
        if not self._datasources:
            raise FrameworkException('A node datasource requested, but none attached to this index')
        return random.choice(self._datasources)
