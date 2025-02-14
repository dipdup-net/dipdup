from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig
from dipdup.config import Url
from dipdup.config import WsUrl


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SubstrateNodeDatasourceConfig(DatasourceConfig):
    """Substrate node datasource config

    :param kind: Always 'substrate.node'
    :param url: Substrate node URL
    :param ws_url: Substrate node WebSocket URL
    :param http: HTTP client configuration
    """

    kind: Literal['substrate.node'] = 'substrate.node'
    url: Url
    ws_url: WsUrl | None = None
    http: HttpConfig | None = None

    @property
    def merge_subscriptions(self) -> bool:
        return False

    @property
    def rollback_depth(self) -> int:
        # NOTE: We use only finalzed heads
        return 0
