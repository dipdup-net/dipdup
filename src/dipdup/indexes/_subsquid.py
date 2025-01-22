import random
from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Any
from typing import Generic
from typing import TypeVar

if TYPE_CHECKING:
    from dipdup.context import DipDupContext
from dipdup.datasources import JsonRpcDatasource
from dipdup.index import Index
from dipdup.index import IndexQueueItemT
from dipdup.performance import metrics

IndexConfigT = TypeVar('IndexConfigT', bound=Any)
DatasourceT = TypeVar('DatasourceT', bound=Any)


class SubsquidIndex(
    Generic[IndexConfigT, IndexQueueItemT, DatasourceT],
    Index[IndexConfigT, IndexQueueItemT, DatasourceT],
    ABC,
):
    subsquid_datasources: tuple[Any, ...]
    node_datasources: tuple[Any, ...]

    def __init__(self, ctx: 'DipDupContext', config: IndexConfigT, datasources: tuple[DatasourceT, ...]) -> None:
        super().__init__(ctx, config, datasources)
        self._subsquid_started: bool = False

    @abstractmethod
    async def _synchronize_subsquid(self, sync_level: int) -> None: ...

    @abstractmethod
    async def _synchronize_node(self, sync_level: int) -> None: ...

    async def _get_node_sync_level(
        self,
        subsquid_level: int,
        index_level: int,
        node: JsonRpcDatasource[Any] | None = None,
    ) -> int | None:
        if not self.node_datasources:
            return None
        node = node or random.choice(self.node_datasources)

        node_sync_level = await node.get_head_level()
        node._logger.info('current head is %s', node_sync_level)

        subsquid_lag = abs(node_sync_level - subsquid_level)
        subsquid_available = subsquid_level - index_level
        self._logger.info('Subsquid is %s levels behind; %s available', subsquid_lag, subsquid_available)
        if subsquid_available <= node.NODE_LAST_MILE:
            return node_sync_level
        return None

    async def _synchronize(self, sync_level: int) -> None:
        """Fetch event logs via Fetcher and pass to message callback"""
        index_level = await self._enter_sync_state(sync_level)
        if index_level is None:
            return

        levels_left = sync_level - index_level
        if levels_left <= 0:
            return

        if self.subsquid_datasources:
            datasource = self.subsquid_datasources[0]
            subsquid_sync_level = await datasource.get_head_level()
            datasource._logger.info('current head is %s', subsquid_sync_level)
            metrics._sqd_processor_chain_height = subsquid_sync_level
        else:
            subsquid_sync_level = 0

        node_sync_level = await self._get_node_sync_level(subsquid_sync_level, index_level)

        # NOTE: Fetch last blocks from node if there are not enough realtime messages in queue
        if node_sync_level:
            sync_level = min(sync_level, node_sync_level)
            self._logger.info('Synchronizing with node: %s -> %s', index_level, sync_level)
            await self._synchronize_node(sync_level)
        else:
            sync_level = min(sync_level, subsquid_sync_level)
            self._logger.info('Synchronizing with Subsquid: %s -> %s', index_level, sync_level)
            await self._synchronize_subsquid(sync_level)

        if not self.node_datasources and not self._subsquid_started:
            self._subsquid_started = True
            self._logger.info('No node datasources available; polling Subsquid')
            for datasource in self.subsquid_datasources:
                await datasource.start()

        await self._exit_sync_state(sync_level)
