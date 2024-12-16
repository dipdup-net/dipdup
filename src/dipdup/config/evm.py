from __future__ import annotations

from abc import ABC
from typing import Annotated
from typing import Literal
from typing import TypeAlias

from pydantic import AfterValidator
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import Alias
from dipdup.config import ContractConfig
from dipdup.config import Hex
from dipdup.config import IndexConfig
from dipdup.config.abi_etherscan import AbiEtherscanDatasourceConfig
from dipdup.config.evm_node import EvmNodeDatasourceConfig
from dipdup.config.evm_subsquid import EvmSubsquidDatasourceConfig
from dipdup.exceptions import ConfigurationError

EVM_ADDRESS_PREFIXES = ('0x',)
EVM_ADDRESS_LENGTH = 42

EvmDatasourceConfigU: TypeAlias = EvmSubsquidDatasourceConfig | EvmNodeDatasourceConfig | AbiEtherscanDatasourceConfig


def _validate_evm_address(v: str) -> str:
    """
    Checks if the given value is a valid StarkNet address within the range [0, 2**251).
    """
    # NOTE: It's a `config export` call with environment variable substitution disabled
    if '${' in v:
        return v

    from eth_utils.address import is_address
    from eth_utils.address import to_normalized_address

    if not is_address(v):
        raise ValueError(f'{v} is not a valid EVM contract address')
    # NOTE: Normalizing is converting address to a non-checksum form.
    # See https://coincodex.com/article/2078/ethereum-address-checksum-explained/
    return to_normalized_address(v)


type EvmAddress = Annotated[Hex, AfterValidator(_validate_evm_address)]


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class EvmContractConfig(ContractConfig):
    """EVM contract config

    :param kind: Always `evm`
    :param address: Contract address
    :param abi: Contract ABI
    :param typename: Alias for the contract script
    """

    kind: Literal['evm']
    address: EvmAddress | None = None
    abi: EvmAddress | None = None
    typename: str | None = None

    def __hash__(self) -> int:
        return hash(self.module_name)

    def get_address(self) -> str:
        if self.address is None:
            raise ConfigurationError(f'`contracts.{self.name}`: `address` field is required`')
        return self.address


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class EvmIndexConfig(IndexConfig, ABC):
    """EVM index that use Subsquid Network as a datasource

    :param kind: starts with 'evm'
    :param datasources: `evm` datasources to use
    """

    datasources: tuple[Alias[EvmDatasourceConfigU], ...]
