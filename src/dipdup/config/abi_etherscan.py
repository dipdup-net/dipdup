from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import AbiDatasourceConfig
from dipdup.config import HttpConfig

DEFAULT_ETHERSCAN_URL = 'https://api.etherscan.io/api'


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class AbiEtherscanDatasourceConfig(AbiDatasourceConfig):
    """Etherscan datasource config

    :param kind: always 'abi.etherscan'
    :param url: API URL
    :param api_key: API key
    :param http: HTTP client configuration
    """

    kind: Literal['abi.etherscan']
    url: str = DEFAULT_ETHERSCAN_URL
    api_key: str | None = None

    http: HttpConfig | None = None
