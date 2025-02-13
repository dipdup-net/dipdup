from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import Alias
from dipdup.config import HandlerConfig
from dipdup.config.tezos import TezosIndexConfig
from dipdup.config.tezos_tzkt import TezosTzktDatasourceConfig

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosTzktHeadHandlerConfig(HandlerConfig):
    """Head block handler config

    :param callback: Callback name
    """

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.context', 'HandlerContext'
        yield 'dipdup.models.tezos', 'TezosHeadBlockData'
        yield package, 'models as models'

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        yield 'ctx', 'HandlerContext'
        yield 'head', 'TezosHeadBlockData'


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosHeadIndexConfig(TezosIndexConfig):
    """Head block index config

    :param kind: always 'tezos.head'
    :param callback: Callback name
    :param datasources: `tezos` datasources to use
    """

    kind: Literal['tezos.head'] = 'tezos.head'
    datasources: tuple[Alias[TezosTzktDatasourceConfig], ...]
    callback: str

    @property
    def first_level(self) -> int:
        return 0

    @property
    def last_level(self) -> int:
        return 0

    def __post_init__(self) -> None:
        super().__post_init__()
        self.handlers = (TezosTzktHeadHandlerConfig(callback=self.callback),)
