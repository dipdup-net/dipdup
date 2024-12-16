from abc import ABC
from typing import TYPE_CHECKING
from typing import Generic
from typing import TypeVar

from dipdup.config import StarknetIndexConfigU
from dipdup.datasources.starknet_node import StarknetNodeDatasource
from dipdup.datasources.starknet_subsquid import StarknetSubsquidDatasource
from dipdup.index import IndexQueueItemT
from dipdup.indexes._subsquid import SubsquidIndex

StarknetDatasource = StarknetSubsquidDatasource | StarknetNodeDatasource

IndexConfigT = TypeVar('IndexConfigT', bound=StarknetIndexConfigU)
DatasourceT = TypeVar('DatasourceT', bound=StarknetDatasource)

if TYPE_CHECKING:
    from dipdup.context import DipDupContext


class StarknetIndex(
    Generic[IndexConfigT, IndexQueueItemT, DatasourceT],
    SubsquidIndex[IndexConfigT, IndexQueueItemT, DatasourceT],
    ABC,
):
    def __init__(
        self,
        ctx: 'DipDupContext',
        config: IndexConfigT,
        datasources: tuple[DatasourceT, ...],
    ) -> None:
        super().__init__(ctx, config, datasources)
        self._cairo_abis = ctx.package._cairo_abis
        self.subsquid_datasources = tuple(d for d in datasources if isinstance(d, StarknetSubsquidDatasource))
        self.node_datasources = tuple(d for d in datasources if isinstance(d, StarknetNodeDatasource))
