from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig
from dipdup.config import Url


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class HttpDatasourceConfig(DatasourceConfig):
    """Generic HTTP datasource config

    :param kind: always 'http'
    :param url: URL to fetch data from
    :param http: HTTP client configuration
    """

    kind: Literal['http'] = 'http'
    url: Url
    http: HttpConfig | None = None
