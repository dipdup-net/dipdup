from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic import Field
from pydantic.dataclasses import dataclass

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class CoinbaseDatasourceConfig(DatasourceConfig):
    """Coinbase datasource config

    :param kind: always 'coinbase'
    :param api_key: API key
    :param secret_key: API secret key
    :param passphrase: API passphrase
    :param http: HTTP client configuration
    """

    kind: Literal['coinbase'] = 'coinbase'
    api_key: str | None = None
    secret_key: str | None = Field(default=None, repr=False)
    passphrase: str | None = Field(default=None, repr=False)

    http: HttpConfig | None = None

    @property
    def url(self) -> str:  # type: ignore[override]
        return 'https://api.pro.coinbase.com'
