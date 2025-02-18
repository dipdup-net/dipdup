from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig
from dipdup.config import Url


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SubstrateSubsquidDatasourceConfig(DatasourceConfig):
    """Subsquid datasource config

    :param kind: always 'substrate.subsquid'
    :param url: URL of Subsquid Network API
    :param http: HTTP client configuration
    """

    kind: Literal['substrate.subsquid'] = 'substrate.subsquid'
    url: Url
    http: HttpConfig | None = None

    @property
    def merge_subscriptions(self) -> bool:
        return False

    @property
    def rollback_depth(self) -> int:
        # NOTE: Subsquid data is always finalized
        return 0
