from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig
from dipdup.models.tzip_metadata import TzipMetadataNetwork

DEFAULT_TZIP_METADATA_URL = 'https://metadata.dipdup.net'


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TzipMetadataDatasourceConfig(DatasourceConfig):
    """DipDup Metadata datasource config

    :param kind: always 'tzip_metadata'
    :param network: Network name, e.g. mainnet, ghostnet, etc.
    :param url: GraphQL API URL, e.g. https://metadata.dipdup.net
    :param http: HTTP client configuration
    """

    kind: Literal['tzip_metadata']
    network: TzipMetadataNetwork
    url: str = DEFAULT_TZIP_METADATA_URL
    http: HttpConfig | None = None
