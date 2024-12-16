from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import cast

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from pydantic.fields import Field

from dipdup.config import Alias
from dipdup.config import HandlerConfig
from dipdup.config._mixin import CodegenMixin
from dipdup.config._mixin import SubgroupIndexMixin
from dipdup.config.tezos import TezosContractConfig
from dipdup.config.tezos import TezosIndexConfig
from dipdup.config.tezos_tzkt import TezosTzktDatasourceConfig
from dipdup.exceptions import ConfigInitializationException
from dipdup.exceptions import ConfigurationError
from dipdup.models.tezos import TezosOperationType
from dipdup.models.tezos_tzkt import OriginationSubscription
from dipdup.models.tezos_tzkt import SmartRollupCementSubscription
from dipdup.models.tezos_tzkt import SmartRollupExecuteSubscription
from dipdup.models.tezos_tzkt import TransactionSubscription
from dipdup.utils import pascal_to_snake
from dipdup.utils import snake_to_pascal

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dipdup.subscriptions import Subscription


class TezosOperationsPatternConfig(CodegenMixin):
    """Base class for pattern config items.

    Contains methods for import and method signature generation during handler callbacks codegen.
    """

    @classmethod
    def format_storage_import(
        cls,
        package: str,
        module_name: str,
    ) -> tuple[str, str]:
        storage_cls = f'{snake_to_pascal(module_name)}Storage'
        return f'{package}.types.{module_name}.tezos_storage', storage_cls

    @classmethod
    def format_parameter_import(
        cls,
        package: str,
        module_name: str,
        entrypoint: str,
        alias: str | None,
    ) -> tuple[str, str]:
        entrypoint = entrypoint.lstrip('_')
        parameter_module = pascal_to_snake(entrypoint)
        parameter_cls = f'{snake_to_pascal(entrypoint)}Parameter'
        if alias:
            parameter_cls += f' as {snake_to_pascal(alias)}Parameter'

        return f'{package}.types.{module_name}.tezos_parameters.{parameter_module}', parameter_cls

    @classmethod
    def format_untyped_operation_import(cls) -> tuple[str, str]:
        return 'dipdup.models.tezos', 'TezosOperationData'

    @classmethod
    def format_origination_argument(
        cls,
        module_name: str,
        optional: bool,
        alias: str | None,
    ) -> tuple[str, str]:
        arg_name = pascal_to_snake(alias or f'{module_name}_origination')
        storage_cls = f'{snake_to_pascal(module_name)}Storage'
        if optional:
            return arg_name, f'TezosOrigination[{storage_cls}] | None'
        return arg_name, f'TezosOrigination[{storage_cls}]'

    @classmethod
    def format_operation_argument(
        cls,
        module_name: str,
        entrypoint: str,
        optional: bool,
        alias: str | None,
    ) -> tuple[str, str]:
        arg_name = alias or entrypoint
        entrypoint = entrypoint.lstrip('_')
        parameter_cls = f'{snake_to_pascal(arg_name)}Parameter'
        storage_cls = f'{snake_to_pascal(module_name)}Storage'
        if optional:
            return pascal_to_snake(arg_name), f'TezosTransaction[{parameter_cls}, {storage_cls}] | None'
        return pascal_to_snake(arg_name), f'TezosTransaction[{parameter_cls}, {storage_cls}]'

    @classmethod
    def format_untyped_operation_argument(
        cls,
        type_: str,
        subgroup_index: int,
        optional: bool,
        alias: str | None,
    ) -> tuple[str, str]:
        arg_name = pascal_to_snake(alias or f'{type_}_{subgroup_index}')
        if optional:
            return arg_name, 'TezosOperationData | None'
        return arg_name, 'TezosOperationData'


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosOperationsHandlerTransactionPatternConfig(TezosOperationsPatternConfig, SubgroupIndexMixin):
    """Transaction handler pattern config

    :param type: always 'transaction'
    :param source: Match operations by source contract alias
    :param destination: Match operations by destination contract alias
    :param entrypoint: Match operations by contract entrypoint
    :param optional: Whether can operation be missing in operation group
    :param alias: Alias for operation (helps to avoid duplicates)
    """

    type: Literal['transaction'] = 'transaction'
    source: Alias[TezosContractConfig] | None = None
    destination: Alias[TezosContractConfig] | None = None
    entrypoint: str | None = None
    optional: bool = False
    alias: str | None = None

    def __post_init__(self) -> None:
        SubgroupIndexMixin.__post_init__(self)

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        if self.typed_contract:
            module_name = self.typed_contract.module_name
            yield 'dipdup.models.tezos', 'TezosTransaction'
            yield self.format_parameter_import(
                package,
                module_name,
                cast(str, self.entrypoint),
                self.alias,
            )
            yield self.format_storage_import(package, module_name)
        else:
            yield self.format_untyped_operation_import()

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        if self.typed_contract:
            module_name = self.typed_contract.module_name
            yield self.format_operation_argument(
                module_name,
                cast(str, self.entrypoint),
                self.optional,
                self.alias,
            )
        else:
            yield self.format_untyped_operation_argument(
                'transaction',
                self.subgroup_index,
                self.optional,
                self.alias,
            )

    @property
    def typed_contract(self) -> TezosContractConfig | None:
        if self.entrypoint and self.destination:
            return self.destination
        return None


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosOperationsHandlerOriginationPatternConfig(TezosOperationsPatternConfig, SubgroupIndexMixin):
    """Origination handler pattern config

    :param type: always 'origination'
    :param source: Match operations by source contract alias
    :param originated_contract: Match origination of exact contract
    :param optional: Whether can operation be missing in operation group
    :param strict: Match operations by storage only or by the whole code
    :param alias: Alias for operation (helps to avoid duplicates)
    """

    type: Literal['origination'] = 'origination'
    source: Alias[TezosContractConfig] | None = None
    originated_contract: Alias[TezosContractConfig] | None = None
    optional: bool = False
    strict: bool = False
    alias: str | None = None

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        if self.typed_contract:
            module_name = self.typed_contract.module_name
            yield 'dipdup.models.tezos', 'TezosOrigination'
            yield self.format_storage_import(package, module_name)
        else:
            yield 'dipdup.models.tezos', 'TezosOperationData'

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        if self.typed_contract:
            yield self.format_origination_argument(
                self.typed_contract.module_name,
                self.optional,
                self.alias,
            )
        else:
            yield self.format_untyped_operation_argument(
                'origination',
                self.subgroup_index,
                self.optional,
                self.alias,
            )

    @property
    def typed_contract(self) -> TezosContractConfig | None:
        if self.originated_contract:
            return self.originated_contract
        return None


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosOperationsHandlerSmartRollupExecutePatternConfig(TezosOperationsPatternConfig, SubgroupIndexMixin):
    """Operation handler pattern config

    :param type: always 'sr_execute'
    :param source: Match operations by source contract alias
    :param destination: Match operations by destination contract alias
    :param optional: Whether can operation be missing in operation group
    :param alias: Alias for operation (helps to avoid duplicates)
    """

    type: Literal['sr_execute'] = 'sr_execute'
    source: Alias[TezosContractConfig] | None = None
    destination: Alias[TezosContractConfig] | None = None
    optional: bool = False
    alias: str | None = None

    def __post_init__(self) -> None:
        SubgroupIndexMixin.__post_init__(self)

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.models.tezos', 'TezosSmartRollupExecute'

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        arg_name = pascal_to_snake(self.alias or f'sr_execute_{self.subgroup_index}')
        if self.optional:
            yield arg_name, 'TezosSmartRollupExecute | None'
        else:
            yield arg_name, 'TezosSmartRollupExecute'

    @property
    def typed_contract(self) -> TezosContractConfig | None:
        if self.destination:
            return self.destination
        return None


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosOperationsHandlerSmartRollupCementPatternConfig(TezosOperationsPatternConfig, SubgroupIndexMixin):
    """Operation handler pattern config

    :param type: always 'sr_cement'
    :param source: Match operations by source contract alias
    :param destination: Match operations by destination contract alias
    :param optional: Whether can operation be missing in operation group
    :param alias: Alias for operation (helps to avoid duplicates)
    """

    type: Literal['sr_cement'] = 'sr_cement'
    source: Alias[TezosContractConfig] | None = None
    destination: Alias[TezosContractConfig] | None = None
    optional: bool = False
    alias: str | None = None

    def __post_init__(self) -> None:
        SubgroupIndexMixin.__post_init__(self)

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.models.tezos', 'TezosSmartRollupCement'

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        arg_name = pascal_to_snake(self.alias or f'sr_cement_{self.subgroup_index}')
        if self.optional:
            yield arg_name, 'TezosSmartRollupCement | None'
        else:
            yield arg_name, 'TezosSmartRollupCement'

    @property
    def typed_contract(self) -> TezosContractConfig | None:
        if self.destination:
            return self.destination
        return None


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosOperationsIndexConfig(TezosIndexConfig):
    """Operation index config

    :param kind: always 'tezos.operations'
    :param datasources: `tezos` datasources to use
    :param handlers: List of indexer handlers
    :param types: Types of transaction to fetch
    :param contracts: Aliases of contracts being indexed in `contracts` section
    :param first_level: Level to start indexing from
    :param last_level: Level to stop indexing at
    """

    kind: Literal['tezos.operations']
    datasources: tuple[Alias[TezosTzktDatasourceConfig], ...]
    handlers: tuple[TezosOperationsHandlerConfig, ...]
    contracts: list[Alias[TezosContractConfig]] = Field(default_factory=list)
    types: tuple[TezosOperationType, ...] = (TezosOperationType.transaction,)

    first_level: int = 0
    last_level: int = 0

    def get_subscriptions(self) -> set[Subscription]:
        subs = super().get_subscriptions()

        if TezosOperationType.transaction in self.types:
            if self.merge_subscriptions:
                subs.add(TransactionSubscription())
            else:
                for contract_config in self.contracts:
                    if not isinstance(contract_config, TezosContractConfig):
                        raise ConfigInitializationException
                    subs.add(TransactionSubscription(address=contract_config.address))

        if TezosOperationType.origination in self.types:
            subs.add(OriginationSubscription())

        if TezosOperationType.sr_execute in self.types:
            if self.merge_subscriptions:
                subs.add(SmartRollupExecuteSubscription())
            else:
                for contract_config in self.contracts:
                    if not isinstance(contract_config, TezosContractConfig):
                        raise ConfigInitializationException
                    if contract_config.address and contract_config.address.startswith('sr1'):
                        subs.add(SmartRollupExecuteSubscription(address=contract_config.address))

        if TezosOperationType.sr_cement in self.types:
            if self.merge_subscriptions:
                subs.add(SmartRollupCementSubscription())
            else:
                for contract_config in self.contracts:
                    if not isinstance(contract_config, TezosContractConfig):
                        raise ConfigInitializationException
                    if contract_config.address and contract_config.address.startswith('sr1'):
                        subs.add(SmartRollupCementSubscription(address=contract_config.address))

        return subs

    @classmethod
    def strip(cls, config_dict: dict[str, Any]) -> None:
        super().strip(config_dict)
        for handler in config_dict['handlers']:
            for item in handler['pattern']:
                item.pop('alias', None)


TezosOperationsHandlerPatternConfigU = (
    TezosOperationsHandlerTransactionPatternConfig
    | TezosOperationsHandlerOriginationPatternConfig
    | TezosOperationsHandlerSmartRollupCementPatternConfig
    | TezosOperationsHandlerSmartRollupExecutePatternConfig
)


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosOperationsHandlerConfig(HandlerConfig):
    """Operation handler config

    :param callback: Callback name
    :param pattern: Filters to match operation groups
    """

    pattern: tuple[TezosOperationsHandlerPatternConfigU, ...]

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.context', 'HandlerContext'
        yield package, 'models as models'
        for pattern in self.pattern:
            yield from pattern.iter_imports(package)

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        yield 'ctx', 'HandlerContext'

        arg_names: set[str] = set()
        for pattern in self.pattern:
            arg, arg_type = next(pattern.iter_arguments())
            if arg in arg_names:
                raise ConfigurationError(
                    (
                        'Pattern item is not unique. Set `alias` field to avoid duplicates.\n\n              handler:'
                        f' `{self.callback}`\n              entrypoint: `{arg}`'
                    ),
                )
            arg_names.add(arg)
            yield arg, arg_type


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosOperationsUnfilteredHandlerConfig(HandlerConfig):
    """Handler of unfiltered operation index

    :param callback: Callback name
    """

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.context', 'HandlerContext'
        yield 'dipdup.models.tezos', 'TezosOperationData'
        yield package, 'models as models'

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        yield 'ctx', 'HandlerContext'
        yield 'operation', 'TezosOperationData'


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosOperationsUnfilteredIndexConfig(TezosIndexConfig):
    """Operation index config

    :param kind: always 'tezos.operations_unfiltered'
    :param datasources: `tezos` datasources to use
    :param callback: Callback name
    :param types: Types of transaction to fetch

    :param first_level: Level to start indexing from
    :param last_level: Level to stop indexing at
    """

    kind: Literal['tezos.operations_unfiltered']
    datasources: tuple[Alias[TezosTzktDatasourceConfig], ...]
    callback: str
    types: tuple[TezosOperationType, ...] = (TezosOperationType.transaction,)

    first_level: int = 0
    last_level: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        self.handlers = (TezosOperationsUnfilteredHandlerConfig(callback=self.callback),)

    def get_subscriptions(self) -> set[Subscription]:
        subs = super().get_subscriptions()
        subs.add(TransactionSubscription())
        return subs


TezosOperationsHandlerConfigU = TezosOperationsHandlerConfig | TezosOperationsUnfilteredHandlerConfig
TezosOperationsIndexConfigU = TezosOperationsIndexConfig | TezosOperationsUnfilteredIndexConfig
