from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig
from dipdup.config import Url

DEFAULT_IPFS_URL = 'https://ipfs.io/ipfs'


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class IpfsDatasourceConfig(DatasourceConfig):
    """IPFS datasource config

    :param kind: always 'ipfs'
    :param url: IPFS node URL, e.g. https://ipfs.io/ipfs/
    :param http: HTTP client configuration
    """

    kind: Literal['ipfs'] = 'ipfs'
    url: Url = DEFAULT_IPFS_URL
    http: HttpConfig | None = None
