from __future__ import annotations

import asyncio
import importlib
import os
import sys
from contextlib import AsyncExitStack
from contextlib import contextmanager
from contextlib import suppress
from logging import Logger
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypeVar

from tortoise.exceptions import OperationalError

import dipdup.database
from dipdup import env
from dipdup.codegen import BatchHandlerConfig
from dipdup.config import ContractConfigU
from dipdup.config import DipDupConfig
from dipdup.config import HandlerConfig
from dipdup.config import HookConfig
from dipdup.config.evm import EvmContractConfig
from dipdup.config.evm import EvmIndexConfig
from dipdup.config.evm_events import EvmEventsIndexConfig
from dipdup.config.evm_transactions import EvmTransactionsIndexConfig
from dipdup.config.starknet import StarknetContractConfig
from dipdup.config.starknet import StarknetIndexConfig
from dipdup.config.starknet_events import StarknetEventsIndexConfig
from dipdup.config.tezos import TezosContractConfig
from dipdup.config.tezos import TezosIndexConfig
from dipdup.config.tezos_big_maps import TezosBigMapsIndexConfig
from dipdup.config.tezos_events import TezosEventsIndexConfig
from dipdup.config.tezos_head import TezosHeadIndexConfig
from dipdup.config.tezos_operations import TezosOperationsIndexConfig
from dipdup.config.tezos_operations import TezosOperationsUnfilteredIndexConfig
from dipdup.config.tezos_token_balances import TezosTokenBalancesIndexConfig
from dipdup.config.tezos_token_transfers import TezosTokenTransfersIndexConfig
from dipdup.datasources import Datasource
from dipdup.datasources import IndexDatasource
from dipdup.datasources.abi_etherscan import AbiEtherscanDatasource
from dipdup.datasources.coinbase import CoinbaseDatasource
from dipdup.datasources.evm_node import EvmNodeDatasource
from dipdup.datasources.evm_subsquid import EvmSubsquidDatasource
from dipdup.datasources.http import HttpDatasource
from dipdup.datasources.ipfs import IpfsDatasource
from dipdup.datasources.starknet_node import StarknetNodeDatasource
from dipdup.datasources.starknet_subsquid import StarknetSubsquidDatasource
from dipdup.datasources.tezos_tzkt import TezosTzktDatasource
from dipdup.datasources.tzip_metadata import TzipMetadataDatasource
from dipdup.exceptions import ConfigurationError
from dipdup.exceptions import ContractAlreadyExistsError
from dipdup.exceptions import FrameworkException
from dipdup.exceptions import InitializationRequiredError
from dipdup.exceptions import ReindexingRequiredError
from dipdup.index import Index as IndexCls
from dipdup.index import MatchedHandler
from dipdup.indexes.evm import EvmIndex
from dipdup.indexes.evm_events.index import EvmEventsIndex
from dipdup.indexes.evm_transactions.index import EvmTransactionsIndex
from dipdup.indexes.starknet import StarknetIndex
from dipdup.indexes.starknet_events.index import StarknetEventsIndex
from dipdup.indexes.tezos_big_maps.index import TezosBigMapsIndex
from dipdup.indexes.tezos_events.index import TezosEventsIndex
from dipdup.indexes.tezos_head.index import TezosHeadIndex
from dipdup.indexes.tezos_operations.index import TezosOperationsIndex
from dipdup.indexes.tezos_token_balances.index import TezosTokenBalancesIndex
from dipdup.indexes.tezos_token_transfers.index import TezosTokenTransfersIndex
from dipdup.indexes.tezos_tzkt import TezosIndex
from dipdup.models import Contract
from dipdup.models import ContractMetadata
from dipdup.models import Head
from dipdup.models import Index
from dipdup.models import ModelUpdate
from dipdup.models import ReindexingAction
from dipdup.models import ReindexingReason
from dipdup.models import Schema
from dipdup.models import TokenMetadata
from dipdup.performance import _CacheManager
from dipdup.performance import _MetricManager
from dipdup.performance import _QueueManager
from dipdup.performance import caches
from dipdup.performance import metrics
from dipdup.performance import queues

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from collections.abc import Iterable
    from collections.abc import Iterator
    from types import ModuleType

    from dipdup.package import DipDupPackage
    from dipdup.transactions import TransactionManager


_logger = getLogger(__name__)

DatasourceT = TypeVar('DatasourceT', bound=Datasource[Any])


class MetadataCursor:
    _contract = 0
    _token = 0

    def __init__(self) -> None:
        raise FrameworkException('MetadataCursor is a singleton class')

    @classmethod
    async def initialize(cls) -> None:
        """Initialize metadata cursor from the database."""
        if last_contract := await ContractMetadata.filter().order_by('-update_id').first():
            cls._contract = last_contract.update_id
        if last_token := await TokenMetadata.filter().order_by('-update_id').first():
            cls._token = last_token.update_id

    @classmethod
    def contract(cls) -> int:
        """Increment the current contract update ID and return it."""
        cls._contract += 1
        return cls._contract

    @classmethod
    def token(cls) -> int:
        """Increment the current token update ID and return it."""
        cls._token += 1
        return cls._token


class DipDupContext:
    """Common execution context for handler and hook callbacks.

    :param config: DipDup configuration
    :param package: DipDup package
    :param datasources: Mapping of available datasources
    :param transactions: Transaction manager (don't use it directly)
    :param logger: Context-aware logger instance
    """

    database = dipdup.database

    def __init__(
        self,
        config: DipDupConfig,
        package: DipDupPackage,
        datasources: dict[str, Datasource[Any]],
        transactions: TransactionManager,
    ) -> None:
        self.config = config
        self.package = package
        self.datasources = datasources
        self.transactions = transactions

        self.logger = _logger
        self._pending_indexes: asyncio.Queue[Any] = asyncio.Queue()
        self._pending_hooks: asyncio.Queue[Awaitable[None]] = asyncio.Queue()
        self._rolled_back_indexes: set[str] = set()
        self._handlers: dict[tuple[str, str], HandlerConfig] = {}
        self._hooks: dict[str, HookConfig] = {}

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self.package.name})'

    # TODO: Process-global properties. Document later.
    @property
    def env(self) -> ModuleType:
        return env

    @property
    def caches(self) -> _CacheManager:
        return caches

    @property
    def metrics(self) -> _MetricManager:
        return metrics

    @property
    def queues(self) -> _QueueManager:
        return queues

    async def restart(self) -> None:
        """Restart process and continue indexing."""
        os.execl(sys.executable, sys.executable, *sys.argv)

    async def reindex(
        self,
        reason: str | ReindexingReason | None = None,
        **context: Any,
    ) -> None:
        """Drops the entire database and starts the indexing process from scratch.

        :param reason: Reason for reindexing in free-form string
        :param context: Additional information to include in exception message
        """
        if reason is None:
            reason = ReindexingReason.manual
        # NOTE: Do not check for `str`! Enum is inherited from it.
        elif not isinstance(reason, ReindexingReason):
            context['message'] = reason
            reason = ReindexingReason.manual

        action = self.config.advanced.reindex.get(reason, ReindexingAction.exception)
        self.logger.warning('Reindexing requested: reason `%s`, action `%s`', reason.value, action.value)

        # NOTE: Reset saved checksums; they will be recalculated on the next run
        if action == ReindexingAction.ignore:
            if reason == ReindexingReason.schema_modified:
                await Schema.filter(name=self.config.schema_name).update(hash=None)
            elif reason == ReindexingReason.config_modified:
                await Index.filter().update(config_hash=None)
            elif reason == ReindexingReason.rollback:
                await Head.filter().update(hash=None)

        elif action == ReindexingAction.exception:
            schema = await Schema.filter(name=self.config.schema_name).get()
            if not schema.reindex:
                schema.reindex = reason
                await schema.save()
            raise ReindexingRequiredError(schema.reindex, context)

        elif action == ReindexingAction.wipe:
            conn = self.database.get_connection()
            # FIXME: Define a global var or config option for "always immune tables"
            immune_tables = self.config.database.immune_tables | {'dipdup_meta', 'aerich'}
            await self.database.wipe_schema(
                conn=conn,
                schema_name=self.config.database.schema_name,
                immune_tables=immune_tables,
                migrations_dir=self.package.migrations,
            )
            await self.restart()

        else:
            raise NotImplementedError('Unknown reindexing action', action)

    async def add_contract(
        self,
        kind: Literal['tezos'] | Literal['evm'] | Literal['starknet'],
        name: str,
        address: str | None = None,
        typename: str | None = None,
        code_hash: str | int | None = None,
    ) -> None:
        """Adds contract to the inventory.

        :param kind: Either 'tezos' or 'evm' or 'starknet' allowed
        :param name: Contract name
        :param address: Contract address
        :param typename: Alias for the contract script
        :param code_hash: Contract code hash
        """
        self.logger.info('Creating %s contract `%s` with typename `%s`', kind, name, typename)

        if name in self.config.contracts:
            raise ContractAlreadyExistsError(name)

        contract_config: ContractConfigU
        if kind == 'tezos':
            contract_config = TezosContractConfig(
                kind=kind,
                address=address,
                code_hash=code_hash,
                typename=typename,
            )
        elif kind == 'evm':
            if address is None:
                raise ConfigurationError('EVM contract address is required')
            contract_config = EvmContractConfig(
                kind=kind,
                address=address,
                typename=typename,
            )
        elif kind == 'starknet':
            if address is None:
                raise ConfigurationError('Starknet contract address is required')
            contract_config = StarknetContractConfig(
                kind=kind,
                address=address,
                typename=typename,
            )
        else:
            raise NotImplementedError('Unknown contract kind', kind)

        contract_config._name = name
        self.config.contracts[name] = contract_config

        with suppress(OperationalError):
            await Contract(
                name=contract_config.name,
                address=contract_config.address,
                typename=contract_config.typename,
                code_hash=code_hash,
                kind=kind,
            ).save()

    async def add_index(
        self,
        name: str,
        template: str,
        values: dict[str, Any],
        first_level: int = 0,
        last_level: int = 0,
        state: Index | None = None,
    ) -> None:
        """Adds a new index from template.

        :param name: Index name
        :param template: Index template to use
        :param values: Mapping of values to fill template with
        :param first_level: First level to start indexing from
        :param last_level: Last level to index
        :param state: Initial index state (dev only)
        """
        self.config.add_index(name, template, values, first_level, last_level)
        await self._spawn_index(name, state)

    def _link(self, new_ctx: DipDupContext) -> None:
        new_ctx._pending_indexes = self._pending_indexes
        new_ctx._pending_hooks = self._pending_hooks
        new_ctx._rolled_back_indexes = self._rolled_back_indexes
        new_ctx._handlers = self._handlers
        new_ctx._hooks = self._hooks

    async def _spawn_index(
        self,
        name: str,
        state: Index | None = None,
    ) -> IndexCls[Any, Any, Any]:

        index_config = self.config.get_index(name)

        index: IndexCls[Any, Any, Any]
        if isinstance(index_config, EvmIndexConfig):
            index = self._create_evm_index(index_config)
        elif isinstance(index_config, TezosIndexConfig):
            index = self._create_tezos_index(index_config)
        elif isinstance(index_config, StarknetIndexConfig):
            index = self._create_starknet_index(index_config)
        else:
            raise NotImplementedError

        for handler_config in index_config.handlers:
            handler_config.parent = index_config
            self.register_handler(handler_config)

        batch_handler = BatchHandlerConfig()
        batch_handler.parent = index_config
        self.register_handler(batch_handler)

        await index.initialize_state(state)

        # NOTE: IndexDispatcher will handle further initialization when it's time
        self._pending_indexes.put_nowait(index)

        return index

    def _create_evm_index(self, index_config: EvmIndexConfig) -> EvmIndex[Any, Any, Any]:
        datasource_configs = index_config.datasources
        datasources = tuple(self.get_evm_datasource(c.name) for c in datasource_configs)
        index_datasources = tuple(d for d in datasources if isinstance(d, IndexDatasource))

        for datasource in index_datasources:
            datasource.attach_index(index_config)

        index: EvmIndex[Any, Any, Any]
        if isinstance(index_config, EvmTransactionsIndexConfig):
            index = EvmTransactionsIndex(self, index_config, index_datasources)
        elif isinstance(index_config, EvmEventsIndexConfig):
            index = EvmEventsIndex(self, index_config, index_datasources)
        else:
            raise NotImplementedError

        return index

    def _create_starknet_index(self, index_config: StarknetIndexConfig) -> StarknetIndex[Any, Any, Any]:
        datasource_configs = index_config.datasources
        datasources = tuple(self.get_starknet_datasource(c.name) for c in datasource_configs)
        index_datasources = tuple(d for d in datasources if isinstance(d, IndexDatasource))

        for datasource in index_datasources:
            datasource.attach_index(index_config)

        index: StarknetIndex[Any, Any, Any]
        if isinstance(index_config, StarknetEventsIndexConfig):
            index = StarknetEventsIndex(self, index_config, index_datasources)
        else:
            raise NotImplementedError

        return index

    def _create_tezos_index(self, index_config: TezosIndexConfig) -> TezosIndex[Any, Any]:
        datasources = tuple(self.get_tezos_tzkt_datasource(c.name) for c in index_config.datasources)

        index: TezosIndex[Any, Any]
        if isinstance(index_config, TezosOperationsIndexConfig | TezosOperationsUnfilteredIndexConfig):
            index = TezosOperationsIndex(self, index_config, datasources)
        elif isinstance(index_config, TezosBigMapsIndexConfig):
            index = TezosBigMapsIndex(self, index_config, datasources)
        elif isinstance(index_config, TezosHeadIndexConfig):
            index = TezosHeadIndex(self, index_config, datasources)
        elif isinstance(index_config, TezosTokenBalancesIndexConfig):
            index = TezosTokenBalancesIndex(self, index_config, datasources)
        elif isinstance(index_config, TezosTokenTransfersIndexConfig):
            index = TezosTokenTransfersIndex(self, index_config, datasources)
        elif isinstance(index_config, TezosEventsIndexConfig):
            index = TezosEventsIndex(self, index_config, datasources)
        else:
            raise NotImplementedError

        for datasource in datasources:
            datasource.attach_index(index_config)

        return index

    # TODO: disable_index(name: str)

    async def update_contract_metadata(
        self,
        network: str,
        address: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        """
        Inserts or updates corresponding rows in the internal `dipdup_contract_metadata` table
        to provide a generic metadata interface (see docs).

        :param network: Network name (e.g. `mainnet`)
        :param address: Contract address
        :param metadata: Contract metadata to insert/update
        """
        update_id = MetadataCursor.contract()
        await ContractMetadata.update_or_create(
            network=network,
            contract=address,
            defaults={'metadata': metadata, 'update_id': update_id},
        )

    async def update_token_metadata(
        self,
        network: str,
        address: str,
        token_id: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        """
        Inserts or updates corresponding rows in the internal `dipdup_token_metadata` table
        to provide a generic metadata interface (see docs).

        :param network: Network name (e.g. `mainnet`)
        :param address: Contract address
        :param token_id: Token ID
        :param metadata: Token metadata to insert/update
        """

        if not all(str.isdigit(c) for c in token_id):
            raise ValueError('`token_id` must be a number')

        update_id = MetadataCursor.token()
        await TokenMetadata.update_or_create(
            network=network,
            contract=address,
            token_id=token_id,
            defaults={'metadata': metadata, 'update_id': update_id},
        )

    def _get_datasource(self, name: str, *types: type[DatasourceT]) -> DatasourceT:
        datasource = self.datasources.get(name)
        if not datasource:
            raise ConfigurationError(f'Datasource `{name}` is missing')

        for type_ in types:
            if isinstance(datasource, type_):
                break
        else:
            raise ConfigurationError(f"Datasource `{name}` is not a `{types}, it's {datasource}`")

        return datasource

    def get_tezos_tzkt_datasource(self, name: str) -> TezosTzktDatasource:
        """Get `tezos.tzkt` datasource by name"""
        return self._get_datasource(name, TezosTzktDatasource)

    def get_evm_subsquid_datasource(self, name: str) -> EvmSubsquidDatasource:
        """Get `evm.subsquid` datasource by name"""
        return self._get_datasource(name, EvmSubsquidDatasource)

    def get_evm_node_datasource(self, name: str) -> EvmNodeDatasource:
        """Get `evm.node` datasource by name"""
        return self._get_datasource(name, EvmNodeDatasource)

    def get_abi_etherscan_datasource(self, name: str) -> AbiEtherscanDatasource:
        """Get `abi.etherscan` datasource by name

        :param name: Name of the datasource
        """
        return self._get_datasource(name, AbiEtherscanDatasource)

    def get_evm_datasource(self, name: str) -> EvmSubsquidDatasource | EvmNodeDatasource | AbiEtherscanDatasource:
        """Get `evm` datasource by name"""
        return self._get_datasource(name, EvmSubsquidDatasource, EvmNodeDatasource, AbiEtherscanDatasource)  # type: ignore[return-value]

    def get_starknet_datasource(self, name: str) -> StarknetSubsquidDatasource | StarknetNodeDatasource:
        """Get `starknet` datasource by name"""
        return self._get_datasource(name, StarknetSubsquidDatasource, StarknetNodeDatasource)  # type: ignore[return-value]

    def get_coinbase_datasource(self, name: str) -> CoinbaseDatasource:
        """Get `coinbase` datasource by name

        :param name: Name of the datasource
        """
        return self._get_datasource(name, CoinbaseDatasource)

    def get_tzip_metadata_datasource(self, name: str) -> TzipMetadataDatasource:
        """Get `metadata` datasource by name

        :param name: Name of the datasource
        """
        return self._get_datasource(name, TzipMetadataDatasource)

    def get_ipfs_datasource(self, name: str) -> IpfsDatasource:
        """Get `ipfs` datasource by name

        :param name: Name of the datasource
        """
        return self._get_datasource(name, IpfsDatasource)

    def get_http_datasource(self, name: str) -> HttpDatasource:
        """Get `http` datasource by name

        :param name: Name of the datasource
        """
        return self._get_datasource(name, HttpDatasource)

    async def rollback(self, index: str, from_level: int, to_level: int) -> None:
        """Rollback index to a given level reverting all changes made since that level.

        :param index: Index name
        :param from_level: Level to rollback from
        :param to_level: Level to rollback to
        """
        self.logger.info('Rolling back `%s`: %s -> %s', index, from_level, to_level)
        if from_level <= to_level:
            raise FrameworkException(f'Attempt to rollback in future: {from_level} <= {to_level}')

        rollback_depth = self.config.advanced.rollback_depth
        if rollback_depth is None:
            raise FrameworkException('`rollback_depth` is not set')
        if from_level - to_level > rollback_depth:
            await self.reindex(
                ReindexingReason.rollback,
                message='Rollback depth exceeded',
                from_level=from_level,
                to_level=to_level,
                rollback_depth=rollback_depth,
            )

        models = importlib.import_module(f'{self.config.package}.models')
        async with self.transactions.in_transaction():
            updates = await ModelUpdate.filter(
                level__lte=from_level,
                level__gt=to_level,
                index=index,
            ).order_by('-id')

            if updates:
                self.logger.info('Reverting %s updates', len(updates))
            for update in updates:
                model = getattr(models, update.model_name)
                await update.revert(model)

        await Index.filter(name=index).update(level=to_level)
        self._rolled_back_indexes.add(index)

    async def _hooks_loop(self) -> None:
        while True:
            await self._pending_hooks.get()

    def register_handler(self, handler_config: HandlerConfig) -> None:
        # NOTE: Same handlers can be linked to different indexes, we need to use exact config
        key = (handler_config.callback, handler_config.parent.name)
        if key not in self._handlers:
            self._handlers[key] = handler_config

    def register_hook(self, hook_config: HookConfig) -> None:
        key = hook_config.callback
        if key not in self._hooks:
            self._hooks[key] = hook_config

    async def fire_matched_handler(
        self,
        handler: MatchedHandler,
    ) -> None:
        await self.fire_handler(
            name=handler.config.callback,
            index=handler.config.parent.name,
            args=handler.args,
        )

    async def fire_handler(
        self,
        name: str,
        index: str,
        args: Iterable[Any],
    ) -> None:
        """Fire handler with given name and arguments.

        :param name: Handler name
        :param index: Index name
        :param args: Handler arguments without `ctx`
        """
        module = f'{self.package.name}.handlers.{name}'
        handler_config = self._get_handler(name, index)
        new_ctx = HandlerContext._wrap(
            self,
            logger=getLogger(module),
            handler_config=handler_config,
        )
        # NOTE: Handlers are not atomic, levels are. Do not open transaction here.
        with self._callback_wrapper(module):
            fn = self.package.get_callback('handlers', name, name.split('.')[-1])
            await fn(new_ctx, *args)

    async def fire_hook(
        self,
        name: str,
        wait: bool = True,
        **kwargs: Any,
    ) -> None:
        """Fire hook with given name and arguments.

        :param name: Hook name
        :param wait: Wait for hook to finish or fire and forget
        :param kwargs: Hook arguments
        """
        module = f'{self.package.name}.hooks.{name}'
        hook_config = self._get_hook(name)

        new_ctx = HookContext._wrap(
            self,
            logger=getLogger(module),
            hook_config=hook_config,
        )

        async def _wrapper() -> None:
            async with AsyncExitStack() as stack:
                stack.enter_context(self._callback_wrapper(module))
                if hook_config.atomic:
                    # NOTE: Do not use versioned transactions here
                    await stack.enter_async_context(new_ctx.transactions.in_transaction())

                fn = self.package.get_callback('hooks', name, name)
                await fn(new_ctx, **kwargs)

        coro = _wrapper()
        await coro if wait else self._pending_hooks.put_nowait(coro)

    async def execute_sql_script(
        self,
        name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Executes SQL script(s) with given name.

        If the `name` path is a directory, all `.sql` scripts within it will be executed in alphabetical order.

        :param name: File or directory within project's `sql` directory
        :param args: Positional arguments to pass to the script
        :param kwargs: Keyword arguments to pass to the script
        """
        # NOTE: Modified `package_path` breaks SQL discovery.
        if env.TEST:
            return

        await self.database.execute_script(
            sql=None,
            args=args,
            kwargs=kwargs,
            path=self._get_sql_path(name),
            conn=None,
        )

    # TODO: named arguments
    async def execute_sql_query(
        self,
        name: str,
        *args: Any,
    ) -> Any:
        """Executes SQL query with given name included with the project

        :param name: SQL query name within `sql` directory
        :param values: Values to pass to the query
        """

        return await self.database.execute_query(
            sql=None,
            args=args,
            path=self._get_sql_path(name),
            conn=None,
        )

    # NOTE: Aliases, remove later
    execute_sql = execute_sql_script
    execute_script = execute_sql_script
    execute_query = execute_sql_query

    @contextmanager
    def _callback_wrapper(self, module: str) -> Iterator[None]:
        try:
            yield
        # NOTE: Do not wrap known errors like ProjectImportError
        except FrameworkException:
            raise

    def _get_handler(self, name: str, index: str) -> HandlerConfig:
        try:
            return self._handlers[(name, index)]
        except KeyError as e:
            raise ConfigurationError(f'Attempt to fire unregistered handler `{name}` of index `{index}`') from e

    def _get_hook(self, name: str) -> HookConfig:
        try:
            return self._hooks[name]
        except KeyError as e:
            raise ConfigurationError(f'Attempt to fire unregistered hook `{name}`') from e

    def _get_sql_path(self, name: str) -> Path:
        subpackages = name.split('.')
        sql_path = Path(env.get_package_path(self.config.package), 'sql', *subpackages)
        if not sql_path.exists():
            sql_path = sql_path.with_name(sql_path.name + '.sql')
        if not sql_path.exists():
            raise InitializationRequiredError(f'Missing SQL file/directory `{name}`')

        return sql_path


class HookContext(DipDupContext):
    """Execution context of hook callbacks.

    :param config: DipDup configuration
    :param package: DipDup package
    :param datasources: Mapping of available datasources
    :param transactions: Transaction manager (don't use it directly)
    :param logger: Context-aware logger instance
    :param hook_config: Configuration of the current hook
    """

    def __init__(
        self,
        config: DipDupConfig,
        package: DipDupPackage,
        datasources: dict[str, Datasource[Any]],
        transactions: TransactionManager,
        logger: Logger,
        hook_config: HookConfig,
    ) -> None:
        super().__init__(
            config=config,
            package=package,
            datasources=datasources,
            transactions=transactions,
        )
        self.logger = logger
        self.hook_config = hook_config

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self.hook_config.callback})'

    @classmethod
    def _wrap(
        cls,
        ctx: DipDupContext,
        logger: Logger,
        hook_config: HookConfig,
    ) -> HookContext:
        new_ctx = cls(
            config=ctx.config,
            package=ctx.package,
            datasources=ctx.datasources,
            transactions=ctx.transactions,
            logger=logger,
            hook_config=hook_config,
        )
        ctx._link(new_ctx)
        return new_ctx


class _TemplateValues(dict[str, Any]):
    def __init__(self, index: str, values: Any) -> None:
        self._index = index
        super().__init__(values)

    def __getitem__(self, key: str) -> Any:
        try:
            return dict.__getitem__(self, key)
        except KeyError as e:
            raise ConfigurationError(f'Index `{self._index}` requires `{key}` template value to be set') from e


class HandlerContext(DipDupContext):
    """Execution context of handler callbacks.

    :param config: DipDup configuration
    :param package: DipDup package
    :param datasources: Mapping of available datasources
    :param transactions: Transaction manager (don't use it directly)
    :param logger: Context-aware logger instance
    :param handler_config: Configuration of the current handler
    """

    def __init__(
        self,
        config: DipDupConfig,
        package: DipDupPackage,
        datasources: dict[str, Datasource[Any]],
        transactions: TransactionManager,
        logger: Logger,
        handler_config: HandlerConfig,
    ) -> None:
        super().__init__(
            config=config,
            package=package,
            datasources=datasources,
            transactions=transactions,
        )
        self.logger = logger
        self.handler_config = handler_config
        self.template_values = _TemplateValues(
            handler_config.parent.name if handler_config.parent else 'unknown',
            handler_config.parent._template_values if handler_config.parent else {},
        )

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self.template_values._index}.{self.handler_config.callback})'

    @classmethod
    def _wrap(
        cls,
        ctx: DipDupContext,
        logger: Logger,
        handler_config: HandlerConfig,
    ) -> HandlerContext:
        new_ctx = cls(
            config=ctx.config,
            package=ctx.package,
            datasources=ctx.datasources,
            transactions=ctx.transactions,
            logger=logger,
            handler_config=handler_config,
        )
        ctx._link(new_ctx)
        return new_ctx

    @property
    def is_finalized(self) -> bool:
        # FIXME: check the datasource
        return True
