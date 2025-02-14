from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig
from dipdup.config import Url
from dipdup.exceptions import ConfigurationError

TZKT_API_URLS: dict[str, str] = {
    'https://api.tzkt.io': 'mainnet',
    'https://api.ghostnet.tzkt.io': 'ghostnet',
    'https://api.limanet.tzkt.io': 'limanet',
    'https://staging.api.tzkt.io': 'staging',
}


DEFAULT_TZKT_URL = next(iter(TZKT_API_URLS.keys()))
MAX_BATCH_SIZE = 10000


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosTzktDatasourceConfig(DatasourceConfig):
    """TzKT datasource config

    :param kind: always 'tezos.tzkt'
    :param url: Base API URL, e.g. https://api.tzkt.io/
    :param http: HTTP client configuration
    :param buffer_size: Number of levels to keep in FIFO buffer before processing
    :param merge_subscriptions: Whether to merge realtime subscriptions
    :param rollback_depth: Number of blocks to keep in the database to handle reorgs
    """

    kind: Literal['tezos.tzkt'] = 'tezos.tzkt'
    url: Url = DEFAULT_TZKT_URL
    http: HttpConfig | None = None
    buffer_size: int = 0
    merge_subscriptions: bool = False
    rollback_depth: int = 2

    def __post_init__(self) -> None:
        super().__post_init__()

        limit = MAX_BATCH_SIZE
        if self.http and self.http.batch_size and self.http.batch_size > limit:
            raise ConfigurationError(f'`batch_size` must be less than {limit}')
