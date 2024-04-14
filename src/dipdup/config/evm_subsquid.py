from __future__ import annotations

import random
from abc import ABC
from typing import Literal

from pydantic import ConfigDict
from pydantic import field_validator
from pydantic.dataclasses import dataclass

from dipdup.config import HttpConfig
from dipdup.config import IndexConfig
from dipdup.config import IndexDatasourceConfig
from dipdup.config.evm_node import EvmNodeDatasourceConfig
from dipdup.exceptions import ConfigurationError


@dataclass(config=ConfigDict(extra='forbid'), kw_only=True)
class EvmSubsquidDatasourceConfig(IndexDatasourceConfig):
    """Subsquid datasource config

    :param kind: always 'evm.subsquid'
    :param url: URL of Subsquid Network API
    :param node: One or more `evm.node` datasource(s) for the same network
    :param http: HTTP client configuration
    """

    kind: Literal['evm.subsquid']
    url: str
    node: EvmNodeDatasourceConfig | tuple[EvmNodeDatasourceConfig, ...] | None = None
    http: HttpConfig | None = None

    @property
    def random_node(self) -> EvmNodeDatasourceConfig | None:
        if not isinstance(self.node, tuple):
            return self.node
        return random.choice(self.node)

    @property
    def merge_subscriptions(self) -> bool:
        return False

    @property
    def rollback_depth(self) -> int:
        return 0

    @field_validator('url')
    @classmethod
    def _valid_url(cls, v: str) -> str:
        if not v.startswith(('http', 'https')):
            raise ConfigurationError('Subsquid Network URL must start with http(s)')
        return v
