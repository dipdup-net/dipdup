from __future__ import annotations

from abc import ABC
from typing import Literal
from typing import TypeAlias

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import Alias
from dipdup.config import IndexConfig
from dipdup.config import RuntimeConfig
from dipdup.config.substrate_node import SubstrateNodeDatasourceConfig
from dipdup.config.substrate_subscan import SubstrateSubscanDatasourceConfig
from dipdup.config.substrate_subsquid import SubstrateSubsquidDatasourceConfig

SubstrateDatasourceConfigU: TypeAlias = (
    SubstrateSubsquidDatasourceConfig | SubstrateSubscanDatasourceConfig | SubstrateNodeDatasourceConfig
)


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SubstrateRuntimeConfig(RuntimeConfig):
    """Substrate runtime config

    :param kind: Always 'substrate'
    :param type_registry: Path to type registry or its alias
    """

    kind: Literal['substrate'] = 'substrate'
    type_registry: str | None = None


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SubstrateIndexConfig(IndexConfig, ABC):
    """EVM index that use Subsquid Network as a datasource

    :param kind: starts with 'substrate'
    :param datasources: `substrate` datasources to use
    :param runtime: Substrate runtime
    """

    datasources: tuple[Alias[SubstrateDatasourceConfigU], ...]
    runtime: Alias[SubstrateRuntimeConfig]
