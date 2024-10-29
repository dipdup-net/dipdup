from abc import ABC
from functools import cache
from typing import TYPE_CHECKING
from typing import Any
from typing import Generic
from typing import TypeVar

from dipdup.config.evm import EvmContractConfig
from dipdup.datasources.evm_node import EvmNodeDatasource
from dipdup.datasources.evm_subsquid import EvmSubsquidDatasource
from dipdup.exceptions import ConfigurationError
from dipdup.index import IndexQueueItemT
from dipdup.indexes._subsquid import SubsquidIndex
from dipdup.package import DipDupPackage

if TYPE_CHECKING:
    from dipdup.context import DipDupContext


@cache
def get_sighash(
    package: DipDupPackage,
    method: str | None = None,
    signature: str | None = None,
    to: EvmContractConfig | None = None,
) -> str:
    """Method in config is either a full signature or a method name. We need to convert it to a sighash first."""

    if to and (method or signature):
        return package._evm_abis.get_method_abi(
            typename=to.module_name,
            name=method,
            signature=signature,
        )['sighash']

    if (not to) and signature:
        from web3 import Web3

        return '0x' + Web3.keccak(text=signature).hex()[:8]

    raise ConfigurationError('Either `to` or `signature` filters are expected')


IndexConfigT = TypeVar('IndexConfigT', bound=Any)
DatasourceT = TypeVar('DatasourceT', bound=Any)


class EvmIndex(
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
        self.subsquid_datasources = tuple(d for d in datasources if isinstance(d, EvmSubsquidDatasource))
        self.node_datasources = tuple(d for d in datasources if isinstance(d, EvmNodeDatasource))
        self._abis = ctx.package._evm_abis
