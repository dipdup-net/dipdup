from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig
from dipdup.config import Url
from dipdup.config import WsUrl


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class EvmNodeDatasourceConfig(DatasourceConfig):
    """EVM node datasource config

    :param kind: Always 'evm.node'
    :param url: EVM node URL
    :param ws_url: EVM node WebSocket URL
    :param http: HTTP client configuration
    :param rollback_depth: A number of blocks to store in database for rollback
    """

    kind: Literal['evm.node'] = 'evm.node'
    url: Url
    ws_url: WsUrl | None = None
    http: HttpConfig | None = None
    rollback_depth: int = 32

    @property
    def merge_subscriptions(self) -> bool:
        return False
