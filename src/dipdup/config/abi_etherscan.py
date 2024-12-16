from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class AbiEtherscanDatasourceConfig(DatasourceConfig):
    """Etherscan datasource config

    :param kind: always 'abi.etherscan'
    :param url: API URL
    :param api_key: API key
    :param http: HTTP client configuration
    """

    kind: Literal['abi.etherscan']
    url: str
    api_key: str | None = None

    http: HttpConfig | None = None
