from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.config import Alias
from dipdup.config import ContractConfig
from dipdup.config import HandlerConfig
from dipdup.config.tezos import TezosContractConfig
from dipdup.config.tezos import TezosIndexConfig
from dipdup.config.tezos_tzkt import TezosTzktDatasourceConfig
from dipdup.models import SkipHistory
from dipdup.models.tezos_tzkt import BigMapSubscription
from dipdup.utils import pascal_to_snake
from dipdup.utils import snake_to_pascal

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dipdup.subscriptions import Subscription


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosBigMapsHandlerConfig(HandlerConfig):
    """Big map handler config

    :param callback: Callback name
    :param contract: Contract to fetch big map from
    :param path: Path to big map (alphanumeric string with dots)
    """

    contract: Alias[TezosContractConfig]
    path: str

    @classmethod
    def format_key_import(cls, package: str, module_name: str, path: str) -> tuple[str, str]:
        key_cls = f'{snake_to_pascal(path)}Key'
        key_module = f'{pascal_to_snake(path)}_key'
        return f'{package}.types.{module_name}.tezos_big_maps.{key_module}', key_cls

    @classmethod
    def format_value_import(cls, package: str, module_name: str, path: str) -> tuple[str, str]:
        value_cls = f'{snake_to_pascal(path)}Value'
        value_module = f'{pascal_to_snake(path)}_value'
        return f'{package}.types.{module_name}.tezos_big_maps.{value_module}', value_cls

    @classmethod
    def format_big_map_diff_argument(cls, path: str) -> tuple[str, str]:
        key_cls = f'{snake_to_pascal(path)}Key'
        value_cls = f'{snake_to_pascal(path)}Value'
        return pascal_to_snake(path), f'BigMapDiff[{key_cls}, {value_cls}]'

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.context', 'HandlerContext'
        yield 'dipdup.models.tezos', 'TezosBigMapDiff'
        yield package, 'models as models'

        yield self.format_key_import(package, self.contract.module_name, self.path)
        yield self.format_value_import(package, self.contract.module_name, self.path)

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        yield 'ctx', 'HandlerContext'
        yield self.format_big_map_diff_argument(self.path)


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosBigMapsIndexConfig(TezosIndexConfig):
    """Big map index config

    :param kind: always 'tezos.big_maps'
    :param datasources: Tezos datasources to use
    :param handlers: Mapping of big map diff handlers
    :param skip_history: Fetch only current big map keys ignoring historical changes
    :param first_level: Level to start indexing from
    :param last_level: Level to stop indexing at
    """

    kind: Literal['tezos.big_maps'] = 'tezos.big_maps'
    datasources: tuple[Alias[TezosTzktDatasourceConfig], ...]
    handlers: tuple[TezosBigMapsHandlerConfig, ...]

    skip_history: SkipHistory = SkipHistory.never

    first_level: int = 0
    last_level: int = 0

    @property
    def contracts(self) -> set[ContractConfig]:
        return {handler_config.contract for handler_config in self.handlers}

    def get_subscriptions(self) -> set[Subscription]:
        subs = super().get_subscriptions()
        if self.merge_subscriptions:
            subs.add(BigMapSubscription())
        else:
            for handler_config in self.handlers:
                address, path = handler_config.contract.address, handler_config.path
                subs.add(BigMapSubscription(address=address, path=path))
        return subs

    @classmethod
    def strip(cls, config_dict: dict[str, Any]) -> None:
        super().strip(config_dict)
        config_dict.pop('skip_history', None)
