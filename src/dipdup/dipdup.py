import asyncio
import logging
import time
from asyncio import CancelledError
from asyncio import Event
from asyncio import Task
from asyncio import create_task
from asyncio import gather
from collections import defaultdict
from collections import deque
from collections.abc import AsyncIterator
from collections.abc import Awaitable
from collections.abc import Coroutine
from contextlib import AsyncExitStack
from contextlib import asynccontextmanager
from contextlib import suppress
from copy import copy
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from tortoise.exceptions import OperationalError

from dipdup import env
from dipdup.codegen import CodeGenerator
from dipdup.codegen import CommonCodeGenerator
from dipdup.codegen import generate_environments
from dipdup.config import SYSTEM_HOOKS
from dipdup.config import DipDupConfig
from dipdup.config import IndexTemplateConfig
from dipdup.config import PostgresDatabaseConfig
from dipdup.config import SqliteDatabaseConfig
from dipdup.config.evm import EvmContractConfig
from dipdup.config.starknet import StarknetContractConfig
from dipdup.config.tezos import TezosContractConfig
from dipdup.context import DipDupContext
from dipdup.context import MetadataCursor
from dipdup.database import generate_schema
from dipdup.database import get_connection
from dipdup.database import get_schema_hash
from dipdup.database import get_tortoise_config
from dipdup.database import preload_cached_models
from dipdup.database import tortoise_wrapper
from dipdup.datasources import Datasource
from dipdup.datasources import IndexDatasource
from dipdup.datasources import create_datasource
from dipdup.datasources.evm_node import EvmNodeDatasource
from dipdup.datasources.substrate_node import SubstrateNodeDatasource
from dipdup.datasources.tezos_tzkt import TezosTzktDatasource
from dipdup.datasources.tezos_tzkt import late_tzkt_initialization
from dipdup.exceptions import ConfigInitializationException
from dipdup.exceptions import FrameworkException
from dipdup.hasura import HasuraGateway
from dipdup.indexes.evm_events.index import EvmEventsIndex
from dipdup.indexes.evm_transactions.index import EvmTransactionsIndex
from dipdup.indexes.substrate_events.index import SubstrateEventsIndex
from dipdup.indexes.tezos_big_maps.index import TezosBigMapsIndex
from dipdup.indexes.tezos_events.index import TezosEventsIndex
from dipdup.indexes.tezos_head.index import TezosHeadIndex
from dipdup.indexes.tezos_operations.index import TezosOperationsIndex
from dipdup.indexes.tezos_operations.index import extract_operation_subgroups
from dipdup.indexes.tezos_token_transfers.index import TezosTokenTransfersIndex
from dipdup.models import Contract
from dipdup.models import ContractKind
from dipdup.models import Head
from dipdup.models import Index as IndexState
from dipdup.models import IndexStatus
from dipdup.models import MessageType
from dipdup.models import Meta
from dipdup.models import ReindexingReason
from dipdup.models import RollbackMessage
from dipdup.models import Schema
from dipdup.models.evm import EvmEventData
from dipdup.models.evm import EvmTransactionData
from dipdup.models.evm_node import EvmNodeHeadData
from dipdup.models.evm_node import EvmNodeSyncingData
from dipdup.models.substrate import HeadBlock
from dipdup.models.tezos import TezosBigMapData
from dipdup.models.tezos import TezosEventData
from dipdup.models.tezos import TezosHeadBlockData
from dipdup.models.tezos import TezosOperationData
from dipdup.models.tezos import TezosTokenTransferData
from dipdup.package import DipDupPackage
from dipdup.performance import caches
from dipdup.performance import get_stats
from dipdup.performance import metrics
from dipdup.scheduler import SchedulerManager
from dipdup.sys import fire_and_forget
from dipdup.transactions import TransactionManager

if TYPE_CHECKING:
    from dipdup.index import Index

METRICS_INTERVAL = 1.0 if env.DEBUG else 5.0
STATUS_INTERVAL = 1.0 if env.DEBUG else 5.0
CLEANUP_INTERVAL = 60.0 * 5
INDEX_DISPATCHER_INTERVAL = 0.1

_logger = logging.getLogger(__name__)


class IndexDispatcher:
    def __init__(self, ctx: DipDupContext) -> None:
        self._ctx = ctx
        self._indexes: dict[str, Index[Any, Any, Any]] = {}
        # FIXME: Tezos-specific
        self._entrypoint_filter: set[str] = set()
        self._address_filter: set[str] = set()
        self._code_hash_filter: set[int] = set()
        # NOTE: Monitoring purposes
        self._initial_levels: defaultdict[str, int] = defaultdict(int)
        self._previous_levels: defaultdict[str, int] = defaultdict(int)
        self._last_levels_nonempty: int = 0
        self._last_objects_indexed: int = 0

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({len(self._indexes)})'

    async def run(
        self,
        spawn_datasources_event: Event,
        start_scheduler_event: Event,
        early_realtime: bool = False,
    ) -> None:
        _logger.info('Starting index dispatcher')
        self._started_at = time.time()
        metrics.started_at = self._started_at

        await self._subscribe_to_datasource_events()
        await self._load_index_state()

        on_synchronized_fired = False
        on_realtime_fired = False

        for index in self._indexes.values():
            if isinstance(index, TezosOperationsIndex):
                await self._apply_filters(index)

        while True:
            if not spawn_datasources_event.is_set() and not self.is_oneshot():
                if self._every_index_is(IndexStatus.realtime) or early_realtime:
                    spawn_datasources_event.set()

            if spawn_datasources_event.is_set():
                for datasource in self._ctx.datasources.values():
                    if not isinstance(datasource, IndexDatasource):
                        continue
                    await datasource.subscribe()

            tasks: deque[Awaitable[bool]] = deque()
            for _, index in copy(self._indexes).items():
                # NOTE: Do not remove disabled indexes from the mapping or is_oneshot() check will fail
                if index.state.status == IndexStatus.disabled:
                    continue

                tasks.append(index.process())

            indexes_processed = any(await gather(*tasks))
            indexes_spawned = False

            while not self._ctx._pending_indexes.empty():
                index = self._ctx._pending_indexes.get_nowait()
                self._indexes[index._config.name] = index
                indexes_spawned = True

                if isinstance(index, TezosOperationsIndex):
                    await self._apply_filters(index)

            if not indexes_spawned and self.is_oneshot():
                _logger.info('No indexes left, exiting')
                await self._on_synchronized()
                [t.cancel() for t in asyncio.all_tasks() if t is not asyncio.current_task()]

            if self._every_index_is(IndexStatus.realtime) and not indexes_spawned:
                if not on_synchronized_fired:
                    await self._on_synchronized()
                    on_synchronized_fired = True

                if not on_realtime_fired and not indexes_processed:
                    await self._on_realtime()
                    on_realtime_fired = True

                if not start_scheduler_event.is_set():
                    start_scheduler_event.set()
            else:
                metrics.synchronized_at = 0
                metrics.realtime_at = 0
                # NOTE: Fire `on_synchronized` hook when indexes will reach realtime state again
                on_synchronized_fired = False
                on_realtime_fired = False

            await asyncio.sleep(INDEX_DISPATCHER_INTERVAL)

    def is_oneshot(self) -> bool:
        from dipdup.config.tezos_head import TezosHeadIndexConfig

        # NOTE: Empty config means indexes will be spawned later via API.
        if not self._indexes:
            return False

        if not self._ctx._pending_indexes.empty():
            return False

        # NOTE: Run forever if at least one index has no upper bound.
        for index in self._indexes.values():
            if isinstance(index._config, TezosHeadIndexConfig):
                return False
            if not index._config.last_level:
                return False

        return True

    async def _metrics_loop(self, update_interval: float) -> None:
        while True:
            await asyncio.sleep(update_interval)
            await self._update_metrics()

    async def _cleanup_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await self._ctx.transactions.cleanup()

    async def _update_metrics(self) -> None:
        if not self._indexes:
            return
        if not all(i.state.level for i in self._indexes.values()):
            return

        active, synced, realtime = 0, 0, 0
        levels_indexed, levels_total, levels_interval = 0, 0, 0
        for index in self._indexes.values():
            # FIXME: We don't remove disabled indexes from dispatcher anymore
            active += 1
            if index.synchronized:
                synced += 1
            if index.realtime:
                realtime += 1

            try:
                sync_level = index.get_sync_level()
            except FrameworkException:
                return

            if index._config.last_level:
                sync_level = min(sync_level, index._config.last_level)

            initial_level = self._initial_levels[index.name]
            if not initial_level:
                self._initial_levels[index.name] |= index.state.level
                continue

            levels_interval += index.state.level - self._previous_levels[index.name]
            levels_indexed += index.state.level - initial_level
            levels_total += sync_level - initial_level

            self._previous_levels[index.name] = index.state.level

        metrics._indexes_total['active'] = active
        metrics._indexes_total['synced'] = synced
        metrics._indexes_total['realtime'] = realtime

        update_interval = time.time() - float(metrics.metrics_updated_at)
        metrics.metrics_updated_at = time.time()

        last_levels_nonempty, last_objects_indexed = self._last_levels_nonempty, self._last_objects_indexed
        batch_levels_nonempty = metrics.levels_nonempty - last_levels_nonempty
        batch_objects = metrics.objects_indexed - last_objects_indexed

        levels_speed = levels_interval / update_interval
        levels_speed_average = levels_indexed / (time.time() - self._started_at)
        time_passed = time.time() - self._started_at
        time_left, progress = 0.0, 0.0
        if levels_speed_average:
            time_left = (levels_total - levels_indexed) / levels_speed_average
        if levels_total:
            progress = levels_indexed / levels_total

        # FIXME: Only with Etherlink demo. Why?
        if levels_total <= 0:
            return

        metrics.levels_indexed = levels_indexed
        metrics.levels_total = levels_total

        metrics.levels_speed = levels_speed
        metrics.levels_speed_average = levels_speed_average

        metrics.objects_speed = batch_objects / update_interval
        metrics.levels_nonempty_speed = batch_levels_nonempty / update_interval

        metrics.time_passed = time_passed
        metrics.time_left = time_left
        metrics.progress = progress

        self._last_levels_nonempty = int(metrics.levels_nonempty)
        self._last_objects_indexed = int(metrics.objects_indexed)

        fire_and_forget(
            Meta.update_or_create(
                key='dipdup_metrics',
                defaults={'value': get_stats()},
            )
        )

    async def _status_loop(self, update_interval: float) -> None:
        while True:
            await asyncio.sleep(update_interval)
            self._log_status()

    def _log_status(self) -> None:
        total, indexed = int(metrics.levels_total), int(metrics.levels_indexed)
        if metrics.realtime_at:
            _logger.info('realtime: %s levels indexed and counting', indexed)
            return

        progress, left = float(metrics.progress) * 100, total - indexed
        scanned_levels = int(metrics.levels_indexed) or int(metrics.levels_nonempty)
        if not progress:
            if self._indexes:
                if scanned_levels:
                    msg = f'indexing: {scanned_levels} levels, estimating...'
                elif metrics.objects_indexed:
                    msg = f'indexing: {metrics.objects_indexed} objects, estimating...'
                else:
                    msg = 'indexing: warming up...'
            else:
                msg = 'no indexes, idling'
            _logger.info(msg)
            return

        levels_speed, objects_speed = int(metrics.levels_nonempty_speed), int(metrics.objects_speed)
        msg = 'last mile' if metrics.synchronized_at else 'indexing'
        msg += f': {progress:5.1f}% done, {left} levels left'

        # NOTE: Resulting message is about 80 chars with the current logging format
        msg += ' ' * (48 - len(msg))
        msg += f' {levels_speed:5} L {objects_speed:5} O'
        _logger.info(msg)

    async def _apply_filters(self, index: TezosOperationsIndex) -> None:
        entrypoints, addresses, code_hashes = await index.get_filters()
        self._entrypoint_filter.update(entrypoints)
        self._address_filter.update(addresses)
        self._code_hash_filter.update(code_hashes)

    def _every_index_is(self, status: IndexStatus) -> bool:
        if not self._indexes:
            return False

        statuses = {i.state.status for i in self._indexes.values()}
        return statuses == {status}

    async def _fetch_contracts(self) -> None:
        """Add contracts spawned from context to config"""
        contracts = await Contract.filter().all()
        _logger.info('%s contracts fetched from database', len(contracts))

        for contract in contracts:
            if contract.name in self._ctx.config.contracts:
                continue

            contract_config: TezosContractConfig | EvmContractConfig | StarknetContractConfig
            if contract.kind == ContractKind.tezos:
                contract_config = TezosContractConfig(
                    kind='tezos',
                    address=contract.address,
                    code_hash=contract.code_hash,
                    typename=contract.typename,
                )
            elif contract.kind == ContractKind.evm:
                contract_config = EvmContractConfig(
                    kind='evm',
                    address=contract.address,
                    typename=contract.typename,
                )
            elif contract.kind == ContractKind.starknet:
                contract_config = StarknetContractConfig(
                    kind='starknet',
                    address=contract.address,
                    typename=contract.typename,
                )
            else:
                raise NotImplementedError(contract.kind)

            self._ctx.config.contracts[contract.name] = contract_config

        self._ctx.config.initialize()

    async def _load_index_state(self) -> None:
        if self._indexes:
            raise FrameworkException('Index states are already loaded')

        await self._fetch_contracts()
        _logger.info('%s indexes found in database', await IndexState.all().count())

        async def _process(index_state: IndexState) -> None:
            name, template, template_values = index_state.name, index_state.template, index_state.template_values

            # NOTE: Index in config (templates are already resolved): just verify hash
            if index_config := self._ctx.config.indexes.get(name):
                if isinstance(index_config, IndexTemplateConfig):
                    raise ConfigInitializationException

                new_hash = index_config.hash()
                if not index_state.config_hash:
                    index_state.config_hash = new_hash
                    await index_state.save()
                elif new_hash != index_state.config_hash:
                    await self._ctx.reindex(
                        ReindexingReason.config_modified,
                        message='Config hash mismatch',
                        index_name=index_state.name,
                        old_hash=index_state.config_hash,
                        new_hash=new_hash,
                    )

            # NOTE: Templated index: recreate index config, verify hash
            elif template:
                if template not in self._ctx.config.templates:
                    await self._ctx.reindex(
                        ReindexingReason.config_modified,
                        message='Template not found',
                        index_name=index_state.name,
                        template=template,
                    )
                await self._ctx.add_index(
                    name,
                    template,
                    template_values,
                    state=index_state,
                )

            # NOTE: Index config is missing, possibly just commented-out
            else:
                _logger.warning('Index `%s` not found in config, ignoring', name)

        async for index_state in IndexState.all():
            await _process(index_state)

    async def _subscribe_to_datasource_events(self) -> None:
        for datasource in self._ctx.datasources.values():
            if isinstance(datasource, IndexDatasource):
                datasource.call_on_rollback(self._on_rollback)

            if isinstance(datasource, TezosTzktDatasource):
                datasource.call_on_head(self._on_tzkt_head)
                datasource.call_on_operations(self._on_tzkt_operations)
                datasource.call_on_token_transfers(self._on_tzkt_token_transfers)
                datasource.call_on_big_maps(self._on_tzkt_big_maps)
                datasource.call_on_events(self._on_tzkt_events)
            elif isinstance(datasource, EvmNodeDatasource):
                datasource.call_on_head(self._on_evm_node_head)
                datasource.call_on_events(self._on_evm_node_events)
                datasource.call_on_transactions(self._on_evm_node_transactions)
                datasource.call_on_syncing(self._on_evm_node_syncing)
            elif isinstance(datasource, SubstrateNodeDatasource):
                datasource.call_on_head(self._on_substrate_head)
                datasource.call_on_events(self._on_substrate_events)

    async def _on_tzkt_head(self, datasource: TezosTzktDatasource, head: TezosHeadBlockData) -> None:
        # NOTE: Do not await query results, it may block Websocket loop. We do not use Head anyway.
        fire_and_forget(
            Head.update_or_create(
                name=datasource.name,
                defaults={
                    'level': head.level,
                    'hash': head.hash,
                    'timestamp': head.timestamp,
                },
            ),
        )
        metrics._datasource_head_updated[datasource.name] = time.time()

        for index in self._indexes.values():
            if isinstance(index, TezosHeadIndex) and datasource in index.datasources:
                index.push_realtime_message(head)

    async def _on_evm_node_head(self, datasource: EvmNodeDatasource, head: EvmNodeHeadData) -> None:
        # NOTE: Do not await query results, it may block Websocket loop. We do not use Head anyway.
        fire_and_forget(
            Head.update_or_create(
                name=datasource.name,
                defaults={
                    'level': head.number,
                    'hash': head.hash,
                    'timestamp': head.timestamp,
                },
            ),
        )
        metrics._datasource_head_updated[datasource.name] = time.time()

    async def _on_evm_node_events(
        self,
        datasource: EvmNodeDatasource,
        logs: tuple[EvmEventData, ...],
    ) -> None:
        for index in self._indexes.values():
            if not isinstance(index, EvmEventsIndex):
                continue
            if datasource not in index.node_datasources:
                continue
            index.push_realtime_message(logs)

    async def _on_evm_node_transactions(
        self,
        datasource: EvmNodeDatasource,
        transactions: tuple[EvmTransactionData, ...],
    ) -> None:
        for index in self._indexes.values():
            if not isinstance(index, EvmTransactionsIndex):
                continue
            if datasource not in index.node_datasources:
                continue
            index.push_realtime_message(transactions)

    async def _on_evm_node_syncing(self, datasource: EvmNodeDatasource, syncing: EvmNodeSyncingData) -> None:
        raise NotImplementedError

    async def _on_tzkt_operations(
        self, datasource: TezosTzktDatasource, operations: tuple[TezosOperationData, ...]
    ) -> None:
        operation_subgroups = tuple(
            extract_operation_subgroups(
                operations,
                addresses=self._address_filter,
                entrypoints=self._entrypoint_filter,
                code_hashes=self._code_hash_filter,
            )
        )

        if not operation_subgroups:
            return

        for index in self._indexes.values():
            if isinstance(index, TezosOperationsIndex) and datasource in index.datasources:
                index.push_realtime_message(operation_subgroups)

    async def _on_tzkt_token_transfers(
        self, datasource: TezosTzktDatasource, token_transfers: tuple[TezosTokenTransferData, ...]
    ) -> None:
        for index in self._indexes.values():
            if isinstance(index, TezosTokenTransfersIndex) and datasource in index.datasources:
                index.push_realtime_message(token_transfers)

    async def _on_tzkt_big_maps(self, datasource: TezosTzktDatasource, big_maps: tuple[TezosBigMapData, ...]) -> None:
        for index in self._indexes.values():
            if isinstance(index, TezosBigMapsIndex) and datasource in index.datasources:
                index.push_realtime_message(big_maps)

    async def _on_tzkt_events(self, datasource: TezosTzktDatasource, events: tuple[TezosEventData, ...]) -> None:
        for index in self._indexes.values():
            if isinstance(index, TezosEventsIndex) and datasource in index.datasources:
                index.push_realtime_message(events)

    # TODO: fix data typing
    async def _on_substrate_head(self, datasource: SubstrateNodeDatasource, head: HeadBlock) -> None:
        # TODO: any head updates here?
        pass

    # TODO: fix data typing
    async def _on_substrate_events(
        self, datasource: SubstrateNodeDatasource, events: tuple[dict[str, Any], ...]
    ) -> None:
        for index in self._indexes.values():
            if isinstance(index, SubstrateEventsIndex) and datasource in index.datasources:
                index.push_realtime_message(events)

    async def _on_rollback(
        self,
        datasource: IndexDatasource[Any],
        type_: MessageType,
        from_level: int,
        to_level: int,
    ) -> None:
        """Call `on_index_rollback` hook for each index that is affected by rollback"""
        if from_level <= to_level:
            raise FrameworkException(f'Attempt to rollback forward: {from_level} -> {to_level}')

        channel = f'{datasource.name}:{type_.value}'
        _logger.info('Channel `%s` has rolled back: %s -> %s', channel, from_level, to_level)
        metrics._datasource_rollbacks[datasource.name] += 1

        # NOTE: Choose action for each index
        for index_name, index in self._indexes.items():
            await index.state.refresh_from_db()
            index_level = index.state.level

            if index.message_type != type_:
                _logger.debug('%s: different channel, skipping', index_name)

            elif datasource not in index.datasources:
                _logger.debug('%s: different datasource, skipping', index_name)

            elif to_level >= index_level:
                _logger.debug('%s: level is too low, skipping', index_name)

            else:
                _logger.debug('%s: affected', index_name)
                index.push_realtime_message(
                    RollbackMessage(from_level, to_level),
                )

        _logger.info('`%s` rollback processed', channel)

    async def _on_synchronized(self) -> None:
        await self._ctx.fire_hook('on_synchronized')

        metrics.synchronized_at = time.time()

    async def _on_realtime(self) -> None:
        # NOTE: We don't have system hook for this event!
        # await self._ctx.fire_hook('on_realtime')
        caches.clear()

        metrics.realtime_at = time.time()


class DipDup:
    """Main indexer class.

    Spawns datasources, registers indexes, passes handler callbacks to executor"""

    def __init__(self, config: DipDupConfig) -> None:
        self._config = config
        self._datasources: dict[str, Datasource[Any]] = {}
        self._transactions: TransactionManager = TransactionManager(
            depth=self._config.advanced.rollback_depth,
            immune_tables=self._config.database.immune_tables,
        )
        self._ctx = DipDupContext(
            config=self._config,
            package=DipDupPackage(config.package_path),
            datasources=self._datasources,
            transactions=self._transactions,
        )
        self._index_dispatcher: IndexDispatcher = IndexDispatcher(self._ctx)
        self._schema: Schema | None = None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self._ctx.package.name})'

    @property
    def schema(self) -> Schema:
        if self._schema is None:
            raise FrameworkException('Schema is not initialized')
        return self._schema

    async def init(
        self,
        force: bool = False,
        base: bool = False,
        include: set[str] | None = None,
    ) -> None:
        """Create new or update existing dipdup project"""
        from dipdup.codegen.evm import EvmCodeGenerator
        from dipdup.codegen.starknet import StarknetCodeGenerator
        from dipdup.codegen.substrate import SubstrateCodeGenerator
        from dipdup.codegen.tezos import TezosCodeGenerator

        await self._create_datasources()

        async with AsyncExitStack() as stack:
            for datasource in self._datasources.values():
                await stack.enter_async_context(datasource)

            package = DipDupPackage(self._config.package_path)
            package.load_abis()

            codegen_classes: tuple[type[CodeGenerator], ...] = (  # type: ignore[assignment]
                CommonCodeGenerator,
                EvmCodeGenerator,
                StarknetCodeGenerator,
                SubstrateCodeGenerator,
                TezosCodeGenerator,
            )
            for codegen_cls in codegen_classes:
                codegen = codegen_cls(
                    config=self._config,
                    package=package,
                    datasources=self._datasources,
                    include=include,
                )
                await codegen.init(
                    force=force,
                    base=base,
                )

            await generate_environments(self._config, package)

    async def run(self) -> None:
        """Run indexing process"""
        # NOTE: DipDup is initialized layer by layer adding tasks to the loop and entering contexts.
        # NOTE: Order matters. But usually you can skip some layers if you don't need them.
        advanced = self._config.advanced
        tasks: set[Task[None]] = set()

        # NOTE: Verify package before indexing to ensure that all modules are importable
        self._ctx.package.verify()
        self._ctx.package.load_abis()

        async with AsyncExitStack() as stack:
            stack.enter_context(suppress(KeyboardInterrupt, CancelledError))
            await self._set_up_database(stack)
            await self._set_up_transactions(stack)
            await self._set_up_datasources(stack)
            await self._set_up_hooks()
            await self._set_up_prometheus()
            await self._set_up_api(stack)

            await self._initialize_schema()
            await self._initialize_migrations()
            await self._initialize_datasources()

            hasura_gateway = await self._set_up_hasura(stack)
            if hasura_gateway:
                await hasura_gateway.configure()

            await MetadataCursor.initialize()

            for name in self._config.indexes:
                await self._ctx._spawn_index(name)

            if self._index_dispatcher.is_oneshot():
                start_scheduler_event = Event()
                spawn_datasources_event = Event()
            else:
                start_scheduler_event = await self._set_up_scheduler(tasks)
                spawn_datasources_event = await self._spawn_datasources(tasks)

                if not advanced.postpone_jobs:
                    start_scheduler_event.set()

            await self._set_up_background_tasks(
                tasks=tasks,
                spawn_datasources_event=spawn_datasources_event,
                start_scheduler_event=start_scheduler_event,
                early_realtime=advanced.early_realtime,
            )

            if tasks:
                await gather(*tasks)

    async def _create_datasources(self) -> None:
        for name, config in self._config.datasources.items():
            if name not in self._datasources:
                self._datasources[name] = create_datasource(config)

    async def _initialize_schema(self) -> None:
        _logger.info('Initializing database schema')
        schema_name = self._config.schema_name
        conn = get_connection()

        # NOTE: Try to fetch existing schema, but don't fail yet
        with suppress(OperationalError):
            self._schema = await Schema.get_or_none(name=schema_name)

        # NOTE: Call with existing Schema too to create new tables if missing
        try:
            await generate_schema(
                conn,
                schema_name,
            )
        except OperationalError as e:
            await self._ctx.reindex(
                ReindexingReason.schema_modified,
                message='Schema initialization failed',
                exception=str(e),
            )

        schema_hash = get_schema_hash(conn)

        if self._schema is None:
            await self._ctx.fire_hook('on_reindex')

            self._schema = Schema(
                name=schema_name,
                hash=schema_hash,
            )
            try:
                await self._schema.save()
            except OperationalError as e:
                await self._ctx.reindex(
                    ReindexingReason.schema_modified,
                    message='Schema initialization failed',
                    exception=str(e),
                )

        elif not self._schema.hash:
            self._schema.hash = schema_hash
            await self._schema.save()

        elif self._schema.hash != schema_hash:
            await self._ctx.reindex(
                ReindexingReason.schema_modified,
                message='Schema hash mismatch',
                old_hash=self._schema.hash,
                new_hash=schema_hash,
            )

        elif self._schema.reindex:
            await self._ctx.reindex(self._schema.reindex)

        await self._ctx.fire_hook('on_restart')

    async def _set_up_transactions(self, stack: AsyncExitStack) -> None:
        await stack.enter_async_context(self._transactions.register())

    async def _set_up_database(self, stack: AsyncExitStack) -> None:
        _logger.info('Setting up database')
        await stack.enter_async_context(
            tortoise_wrapper(
                url=self._config.database.connection_string,
                models=self._config.package,
                timeout=self._config.database.connection_timeout,
                decimal_precision=self._config.advanced.decimal_precision,
                unsafe_sqlite=self._config.advanced.unsafe_sqlite,
            )
        )

    async def _set_up_hooks(self) -> None:
        for system_hook_config in SYSTEM_HOOKS.values():
            self._ctx.register_hook(system_hook_config)

        for hook_config in self._config.hooks.values():
            self._ctx.register_hook(hook_config)

    async def _set_up_prometheus(self) -> None:
        if not self._config.prometheus:
            return

        from prometheus_client import start_http_server

        _logger.info('Setting up Prometheus at %s:%s', self._config.prometheus.host, self._config.prometheus.port)
        start_http_server(self._config.prometheus.port, self._config.prometheus.host)

    async def _set_up_api(self, stack: AsyncExitStack) -> None:
        api_config = self._config.api
        if not api_config or env.TEST or env.CI:
            return

        from aiohttp import web

        from dipdup.api import create_api

        _logger.info('Setting up API')
        api = await create_api(self._ctx)
        runner = web.AppRunner(api)
        await runner.setup()
        site = web.TCPSite(runner, api_config.host, api_config.port)

        @asynccontextmanager
        async def _api_wrapper() -> AsyncIterator[None]:
            await site.start()
            yield
            await site.stop()

        await stack.enter_async_context(_api_wrapper())

    async def _set_up_hasura(self, stack: AsyncExitStack) -> HasuraGateway | None:
        if not self._config.hasura:
            return None

        if not isinstance(self._config.database, PostgresDatabaseConfig):
            raise FrameworkException('PostgresDatabaseConfig expected; check earlier')

        hasura_gateway = HasuraGateway(
            self._config.package,
            self._config.hasura,
            self._config.database,
        )
        await stack.enter_async_context(hasura_gateway)
        return hasura_gateway

    async def _set_up_datasources(self, stack: AsyncExitStack) -> None:
        await self._create_datasources()
        for datasource in self._datasources.values():
            await stack.enter_async_context(datasource)

    async def _initialize_datasources(self) -> None:
        init_tzkt = False
        for datasource in self._datasources.values():
            if not isinstance(datasource, IndexDatasource):
                continue
            await datasource.initialize()
            if isinstance(datasource, TezosTzktDatasource):
                init_tzkt = True

        if init_tzkt:
            await late_tzkt_initialization(
                config=self._config,
                datasources=self._datasources,
                reindex_fn=self._ctx.reindex,
            )

    async def _set_up_background_tasks(
        self,
        tasks: set[Task[None]],
        spawn_datasources_event: Event,
        start_scheduler_event: Event,
        early_realtime: bool,
    ) -> None:
        index_dispatcher = self._index_dispatcher

        def _add_task(coro: Coroutine[Any, Any, None]) -> None:
            tasks.add(create_task(coro, name=f'loop:{coro.__name__.strip("_")}'))

        # NOTE: The main loop; cancels other tasks on exit.
        _add_task(index_dispatcher.run(spawn_datasources_event, start_scheduler_event, early_realtime))

        # NOTE: Monitoring tasks
        _add_task(index_dispatcher._metrics_loop(METRICS_INTERVAL))
        _add_task(index_dispatcher._status_loop(STATUS_INTERVAL))
        # NOTE: Outdated model updates cleanup
        _add_task(index_dispatcher._cleanup_loop(CLEANUP_INTERVAL))

        # NOTE: Hooks called with `wait=False`
        _add_task(self._ctx._hooks_loop())

        # NOTE: Preloading `CachedModel`
        _add_task(preload_cached_models(self._config.package))

    async def _spawn_datasources(self, tasks: set[Task[None]]) -> Event:
        event = Event()

        async def _event_wrapper() -> None:
            _logger.info('Waiting for indexes to synchronize before spawning datasources')
            await event.wait()

            _logger.info('Spawning datasources')
            _run_tasks: deque[Task[None]] = deque()
            for datasource in self._datasources.values():
                _run_tasks.append(
                    create_task(
                        datasource.run(),
                        name=f'datasource:{datasource.name}',
                    )
                )
            await gather(*_run_tasks)

        tasks.add(
            create_task(
                _event_wrapper(),
                name='loop:datasources',
            )
        )
        return event

    async def _initialize_migrations(self) -> None:
        """Initialize database migrations with aerich."""
        if isinstance(self._config.database, SqliteDatabaseConfig):
            _logger.debug('SQLite database detected, skipping migrations initialization')
            return

        migrations_dir = self._ctx.package.migrations
        try:
            from aerich import Command as AerichCommand  # type: ignore[import-untyped]

            tortoise_config = get_tortoise_config(self._config.database.connection_string, self._config.package)
            aerich_command = AerichCommand(
                tortoise_config=tortoise_config, app='models', location=migrations_dir.as_posix()
            )
            await aerich_command.init()

            _logger.info("Initializing database migrations at '%s'", migrations_dir)
            await aerich_command.init_db(safe=True)
        except ModuleNotFoundError as e:
            if e.name != 'aerich':
                raise
            _logger.debug('aerich is not installed, skipping database migration initialization')
        except FileExistsError as e:
            if Path(e.filename).is_relative_to(migrations_dir):
                _logger.debug("Database migrations already initialized at '%s'", migrations_dir)

    async def _set_up_scheduler(self, tasks: set[Task[None]]) -> Event:
        event = Event()
        scheduler = SchedulerManager(
            jobs=self._config.jobs,
            config=self._config.advanced.scheduler,
        )
        run_task = create_task(
            scheduler.run(
                ctx=self._ctx,
                event=event,
            ),
            name='loop:scheduler',
        )
        tasks.add(run_task)

        return event
