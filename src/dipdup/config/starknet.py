from __future__ import annotations

import re
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
from dipdup.config.starknet_node import StarknetNodeDatasourceConfig
from dipdup.config.starknet_subsquid import StarknetSubsquidDatasourceConfig
from dipdup.exceptions import ConfigurationError

StarknetDatasourceConfigU: TypeAlias = StarknetSubsquidDatasourceConfig | StarknetNodeDatasourceConfig

_HEX_ADDRESS_REGEXP = re.compile(r'(0x)?[0-9a-f]{1,64}', re.IGNORECASE | re.ASCII)


def _validate_starknet_address(v: str) -> str:
    """
    Checks if the given value is a valid StarkNet address within the range [0, 2**251).
    """
    # NOTE: It's a `config export` call with environment variable substitution disabled
    if '${' in v:
        return v

    if _HEX_ADDRESS_REGEXP.fullmatch(v) is None:
        raise ValueError(f'{v} is not a valid Starknet contract address')

    # Convert hex to decimal and check if it's less than 2**251
    numeric_value = int(v, 16)
    if not (numeric_value < 2**251):
        raise ValueError(f'{v} is not a valid Starknet contract address')

    # TODO: Probably needs to be to normalized as in EVM case
    return v


type StarknetAddress = Annotated[Hex, AfterValidator(_validate_starknet_address)]


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class StarknetContractConfig(ContractConfig):
    """Starknet contract config

    :param kind: Always `starknet`
    :param address: Contract address
    :param abi: Contract ABI
    :param typename: Alias for the contract script
    """

    kind: Literal['starknet']
    address: StarknetAddress | None = None
    abi: StarknetAddress | None = None
    typename: str | None = None

    def get_address(self) -> str:
        if self.address is None:
            raise ConfigurationError(f'`contracts.{self.name}`: `address` field is required`')
        return self.address


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class StarknetIndexConfig(IndexConfig, ABC):
    """Starknet index that use Subsquid Network as a datasource

    :param datasources: `starknet` datasources to use
    :param first_level: Level to start indexing from
    :param last_level: Level to stop indexing and disable this index
    """

    datasources: tuple[Alias[StarknetDatasourceConfigU], ...]

    first_level: int = 0
    last_level: int = 0
