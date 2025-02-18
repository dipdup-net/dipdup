from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig
from dipdup.config import Url


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SubstrateSubscanDatasourceConfig(DatasourceConfig):
    """Subscan datasource config

    :param kind: always 'substrate.subscan'
    :param url: API URL
    :param api_key: API key
    :param http: HTTP client configuration
    """

    kind: Literal['substrate.subscan'] = 'substrate.subscan'
    url: Url
    api_key: str | None = None

    http: HttpConfig | None = None
