from __future__ import annotations

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Any
from typing import Generic

from dipdup.config.tezos_tzkt_operations import (
    TezosTzktOperationsHandlerOriginationPatternConfig as OriginationPatternConfig,
)
from dipdup.config.tezos_tzkt_operations import (
    TezosTzktOperationsHandlerSmartRollupExecutePatternConfig as SmartRollupExecutePatternConfig,
)
from dipdup.config.tezos_tzkt_operations import (
    TezosTzktOperationsHandlerTransactionPatternConfig as TransactionPatternConfig,
)
from dipdup.config.tezos_tzkt_operations import TezosTzktOperationsIndexConfig
from dipdup.config.tezos_tzkt_operations import TezosTzktOperationsUnfilteredIndexConfig
from dipdup.exceptions import ConfigurationError
from dipdup.exceptions import FrameworkException
from dipdup.fetcher import DataFetcher
from dipdup.fetcher import FetcherChannel
from dipdup.fetcher import FetcherFilterT
from dipdup.fetcher import readahead_by_level
from dipdup.indexes.tezos_tzkt import TZKT_READAHEAD_LIMIT
from dipdup.models.tezos_tzkt import TezosTzktOperationData
from dipdup.models.tezos_tzkt import TezosTzktOperationType

if TYPE_CHECKING:
    from collections import defaultdict
    from collections import deque
    from collections.abc import AsyncIterator

    from dipdup.datasources.tezos_tzkt import TezosTzktDatasource

_logger = logging.getLogger('dipdup.fetcher')


def dedup_operations(operations: tuple[TezosTzktOperationData, ...]) -> tuple[TezosTzktOperationData, ...]:
    """Merge and sort operations fetched from multiple endpoints"""
    return tuple(
        sorted(
            (({op.id: op for op in operations}).values()),
            key=lambda op: op.id,
        )
    )


def get_operations_head(operations: tuple[TezosTzktOperationData, ...]) -> int:
    """Get latest block level (head) of sorted operations batch"""
    for i in range(len(operations) - 1)[::-1]:
        if operations[i].level != operations[i + 1].level:
            return operations[i].level
    return operations[0].level


async def get_transaction_filters(
    config: TezosTzktOperationsIndexConfig,
    datasource: TezosTzktDatasource,
) -> tuple[set[str], set[int]]:
    """Get addresses to fetch transactions from during initial synchronization"""
    if TezosTzktOperationType.transaction not in config.types:
        return set(), set()

    code_hash: int | str | None
    addresses: set[str] = set()
    hashes: set[int] = set()

    # NOTE: Don't try to guess contracts from handlers if set implicitly
    if config.contracts:
        for contract in config.contracts:
            if contract.address:
                addresses.add(contract.address)
            elif contract.resolved_code_hash:
                hashes.add(contract.resolved_code_hash)

        return addresses, hashes

    for handler_config in config.handlers:
        for pattern_config in handler_config.pattern:
            if not isinstance(pattern_config, TransactionPatternConfig):
                continue

            if pattern_config.source:
                if address := pattern_config.source.address:
                    addresses.add(address)
                if code_hash := pattern_config.source.resolved_code_hash:
                    hashes.add(code_hash)

            if pattern_config.destination:
                if address := pattern_config.destination.address:
                    addresses.add(address)
                if code_hash := pattern_config.destination.resolved_code_hash:
                    hashes.add(code_hash)

    return addresses, hashes


async def get_origination_filters(
    config: TezosTzktOperationsIndexConfig,
    datasource: TezosTzktDatasource,
) -> tuple[set[str], set[int]]:
    """Get addresses to fetch origination from during initial synchronization"""
    if TezosTzktOperationType.origination not in config.types:
        return set(), set()

    addresses: set[str] = set()
    hashes: set[int] = set()

    for handler_config in config.handlers:
        for pattern_config in handler_config.pattern:
            if not isinstance(pattern_config, OriginationPatternConfig):
                continue

            if pattern_config.originated_contract:
                if address := pattern_config.originated_contract.address:
                    addresses.add(address)
                if code_hash := pattern_config.originated_contract.resolved_code_hash:
                    hashes.add(code_hash)

            if pattern_config.source:
                _logger.warning(
                    "`source.address` filter significantly hurts indexing performance and doesn't support strict"
                    " typing. Consider using `originated_contract.code_hash` instead"
                )
                if address := pattern_config.source.address:
                    async for batch in datasource.iter_originated_contracts(address):
                        addresses.update(item['address'] for item in batch)
                if code_hash := pattern_config.source.resolved_code_hash:
                    raise FrameworkException('Invalid transaction filter `source.code_hash`')

    return addresses, hashes


async def get_sr_execute_filters(
    config: TezosTzktOperationsIndexConfig,
) -> set[str]:
    """Get addresses to fetch smart rollup executions from during initial synchronization"""
    if TezosTzktOperationType.sr_execute not in config.types:
        return set()

    addresses: set[str] = set()

    if config.contracts:
        for contract in config.contracts:
            if contract.address:
                addresses.add(contract.address)

    for handler_config in config.handlers:
        for pattern_config in handler_config.pattern:
            if not isinstance(pattern_config, SmartRollupExecutePatternConfig):
                continue

            if pattern_config.source:
                if address := pattern_config.source.address:
                    addresses.add(address)
                if pattern_config.source.resolved_code_hash:
                    raise ConfigurationError('Invalid `sr_execute` filter: `source.code_hash`')

            if pattern_config.destination:
                if address := pattern_config.destination.address:
                    addresses.add(address)
                if pattern_config.destination.resolved_code_hash:
                    raise ConfigurationError('Invalid `sr_execute` filter: `destination.code_hash`')

    addresses = {a for a in addresses if a.startswith('sr1')}
    _logger.info('Fetching smart rollup executions from %s addresses', len(addresses))
    return addresses


class OriginationAddressFetcherChannel(FetcherChannel[TezosTzktOperationData, str]):
    _datasource: TezosTzktDatasource

    async def fetch(self) -> None:
        if not self._filter:
            self._head = self._last_level
            self._offset = self._last_level
            return

        # FIXME: No pagination because of URL length limit workaround
        originations = await self._datasource.get_originations(
            addresses=self._filter,
            first_level=self._first_level,
            last_level=self._last_level,
        )

        for op in originations:
            self._buffer[op.level].append(op)

        self._head = self._last_level
        self._offset = self._last_level


class OriginationHashFetcherChannel(FetcherChannel[TezosTzktOperationData, int]):
    _datasource: TezosTzktDatasource

    async def fetch(self) -> None:
        if not self._filter:
            self._head = self._last_level
            self._offset = self._last_level
            return

        originations = await self._datasource.get_originations(
            code_hashes=self._filter,
            offset=self._offset,
            first_level=self._first_level,
            last_level=self._last_level,
        )

        for op in originations:
            self._buffer[op.level].append(op)

        if len(originations) < self._datasource.request_limit:
            self._head = self._last_level
        else:
            self._offset = originations[-1].id
            self._head = get_operations_head(originations)


class MigrationOriginationFetcherChannel(FetcherChannel[TezosTzktOperationData, None]):
    _datasource: TezosTzktDatasource

    async def fetch(self) -> None:
        if self._filter:
            raise FrameworkException("Migration origination fetcher channel doesn't support filters")

        originations = await self._datasource.get_migration_originations(
            first_level=self._first_level,
            last_level=self._last_level,
            offset=self._offset,
        )

        for op in originations:
            if op.originated_contract_address:
                code_hash, type_hash = await self._datasource.get_contract_hashes(op.originated_contract_address)
                op_dict = op.__dict__
                op_dict.update(
                    originated_contract_code_hash=code_hash,
                    originated_contract_type_hash=type_hash,
                )
                op = TezosTzktOperationData(**op_dict)

            self._buffer[op.level].append(op)

        if len(originations) < self._datasource.request_limit:
            self._head = self._last_level
        else:
            self._offset = originations[-1].id
            self._head = get_operations_head(originations)


class TransactionBaseFetcherChannel(FetcherChannel[TezosTzktOperationData, FetcherFilterT], Generic[FetcherFilterT]):
    _datasource: TezosTzktDatasource

    def __init__(
        self,
        buffer: defaultdict[int, deque[TezosTzktOperationData]],
        filter: set[FetcherFilterT],
        first_level: int,
        last_level: int,
        datasource: TezosTzktDatasource,
        field: str,
    ) -> None:
        super().__init__(buffer, filter, first_level, last_level, datasource)
        self._field = field

    @abstractmethod
    async def _get_transactions(self) -> tuple[TezosTzktOperationData, ...]:
        raise NotImplementedError

    async def fetch(self) -> None:
        if not self._filter:
            self._head = self._last_level
            self._offset = self._last_level
            return

        transactions = await self._get_transactions()

        for op in transactions:
            self._buffer[op.level].append(op)

        if len(transactions) < self._datasource.request_limit:
            self._head = self._last_level
        else:
            self._offset = transactions[-1].id
            self._head = get_operations_head(transactions)


class TransactionAddressFetcherChannel(TransactionBaseFetcherChannel[str]):
    async def _get_transactions(self) -> tuple[TezosTzktOperationData, ...]:
        return await self._datasource.get_transactions(
            field=self._field,
            addresses=self._filter,
            code_hashes=None,
            offset=self._offset,
            first_level=self._first_level,
            last_level=self._last_level,
        )


class TransactionHashFetcherChannel(TransactionBaseFetcherChannel[int]):
    async def _get_transactions(self) -> tuple[TezosTzktOperationData, ...]:
        return await self._datasource.get_transactions(
            field=self._field,
            addresses=None,
            code_hashes=self._filter,
            offset=self._offset,
            first_level=self._first_level,
            last_level=self._last_level,
        )


class SmartRollupExecuteAddressFetcherChannel(FetcherChannel[TezosTzktOperationData, str]):
    _datasource: TezosTzktDatasource

    def __init__(
        self,
        buffer: defaultdict[int, deque[TezosTzktOperationData]],
        filter: set[str],
        first_level: int,
        last_level: int,
        datasource: TezosTzktDatasource,
        field: str,
    ) -> None:
        super().__init__(buffer, filter, first_level, last_level, datasource)
        self._field = field

    async def fetch(self) -> None:
        if not self._filter:
            self._head = self._last_level
            self._offset = self._last_level
            return

        operations = await self._datasource.get_sr_execute(
            field=self._field,
            addresses=self._filter,
            offset=self._offset,
            first_level=self._first_level,
            last_level=self._last_level,
        )

        for op in operations:
            self._buffer[op.level].append(op)

        if len(operations) < self._datasource.request_limit:
            self._head = self._last_level
        else:
            self._offset = operations[-1].id
            self._head = get_operations_head(operations)


class OperationsUnfilteredFetcherChannel(FetcherChannel[TezosTzktOperationData, None]):
    _datasource: TezosTzktDatasource

    def __init__(
        self,
        buffer: defaultdict[int, deque[TezosTzktOperationData]],
        first_level: int,
        last_level: int,
        datasource: TezosTzktDatasource,
        type: TezosTzktOperationType,
    ) -> None:
        super().__init__(buffer, set(), first_level, last_level, datasource)
        self._type = type

    async def fetch(self) -> None:
        match self._type:
            case TezosTzktOperationType.origination:
                operations = await self._datasource.get_originations(
                    addresses=None,
                    code_hashes=None,
                    first_level=self._first_level,
                    last_level=self._last_level,
                    offset=self._offset,
                )
            case TezosTzktOperationType.transaction:
                operations = await self._datasource.get_transactions(
                    field='',
                    addresses=None,
                    code_hashes=None,
                    first_level=self._first_level,
                    last_level=self._last_level,
                    offset=self._offset,
                )
            case TezosTzktOperationType.sr_execute:
                operations = await self._datasource.get_sr_execute(
                    field='',
                    addresses=None,
                    first_level=self._first_level,
                    last_level=self._last_level,
                    offset=self._offset,
                )
            case _:
                raise FrameworkException('Unsupported operation type')

        for op in operations:
            self._buffer[op.level].append(op)

        if len(operations) < self._datasource.request_limit:
            self._head = self._last_level
        else:
            self._offset = operations[-1].id
            self._head = get_operations_head(operations)


class OperationFetcher(DataFetcher[TezosTzktOperationData]):
    """Fetches operations from multiple REST API endpoints, merges them and yields by level.

    Offet of every endpoint is tracked separately.
    """

    def __init__(
        self,
        datasource: TezosTzktDatasource,
        first_level: int,
        last_level: int,
        transaction_addresses: set[str],
        transaction_hashes: set[int],
        origination_addresses: set[str],
        origination_hashes: set[int],
        sr_execute_addresses: set[str],
        migration_originations: bool = False,
    ) -> None:
        super().__init__(datasource, first_level, last_level)
        self._transaction_addresses = transaction_addresses
        self._transaction_hashes = transaction_hashes
        self._origination_addresses = origination_addresses
        self._origination_hashes = origination_hashes
        self._sr_execute_addresses = sr_execute_addresses
        self._migration_originations = migration_originations

    @classmethod
    async def create(
        cls,
        config: TezosTzktOperationsIndexConfig,
        datasource: TezosTzktDatasource,
        first_level: int,
        last_level: int,
    ) -> OperationFetcher:
        transaction_addresses, transaction_hashes = await get_transaction_filters(config, datasource)
        origination_addresses, origination_hashes = await get_origination_filters(config, datasource)
        sr_execute_addresses = await get_sr_execute_filters(config)

        return OperationFetcher(
            datasource=datasource,
            first_level=first_level,
            last_level=last_level,
            transaction_addresses=transaction_addresses,
            transaction_hashes=transaction_hashes,
            origination_addresses=origination_addresses,
            origination_hashes=origination_hashes,
            sr_execute_addresses=sr_execute_addresses,
            migration_originations=TezosTzktOperationType.migration in config.types,
        )

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[TezosTzktOperationData, ...]]]:
        """Iterate over operations fetched with multiple REST requests with different filters.

        Resulting data is split by level, deduped, sorted and ready to be processed by TezosTzktOperationsIndex.
        """
        channel_kwargs = {
            'buffer': self._buffer,
            'datasource': self._datasource,
            'first_level': self._first_level,
            'last_level': self._last_level,
        }
        channels: tuple[FetcherChannel[TezosTzktOperationData, Any], ...] = (
            TransactionAddressFetcherChannel(
                filter=self._transaction_addresses,
                field='sender',
                **channel_kwargs,  # type: ignore[arg-type]
            ),
            TransactionAddressFetcherChannel(
                filter=self._transaction_addresses,
                field='target',
                **channel_kwargs,  # type: ignore[arg-type]
            ),
            TransactionHashFetcherChannel(
                filter=self._transaction_hashes,
                field='sender',
                **channel_kwargs,  # type: ignore[arg-type]
            ),
            TransactionHashFetcherChannel(
                filter=self._transaction_hashes,
                field='target',
                **channel_kwargs,  # type: ignore[arg-type]
            ),
            OriginationAddressFetcherChannel(
                filter=self._origination_addresses,
                **channel_kwargs,  # type: ignore[arg-type]
            ),
            OriginationHashFetcherChannel(
                filter=self._origination_hashes,
                **channel_kwargs,  # type: ignore[arg-type]
            ),
            SmartRollupExecuteAddressFetcherChannel(
                filter=self._sr_execute_addresses,
                field='sender',
                **channel_kwargs,  # type: ignore[arg-type]
            ),
            SmartRollupExecuteAddressFetcherChannel(
                filter=self._sr_execute_addresses,
                field='rollup',
                **channel_kwargs,  # type: ignore[arg-type]
            ),
        )

        async def _merged_iter(
            merging_channels: tuple[FetcherChannel[TezosTzktOperationData, Any], ...]
        ) -> AsyncIterator[tuple[TezosTzktOperationData, ...]]:
            while True:
                min_channel = sorted(merging_channels, key=lambda x: x.head)[0]
                await min_channel.fetch()

                # NOTE: It's a different channel now, but with greater head level
                next_min_channel = sorted(merging_channels, key=lambda x: x.head)[0]
                next_min_head = next_min_channel.head

                if self._head <= next_min_head:
                    buffer_keys = sorted(self._buffer.keys())
                    for key in buffer_keys:
                        if key < self._head:
                            continue
                        if key > next_min_head:
                            break

                        self._head = key
                        channel_operations = self._buffer.pop(self._head)
                        yield dedup_operations(tuple(channel_operations))
                    self._head += 1

                if all(c.fetched for c in merging_channels):
                    break

            if self._buffer:
                raise FrameworkException('Operations left in queue')

        event_iter = _merged_iter(channels)
        async for level, operations in readahead_by_level(event_iter, limit=TZKT_READAHEAD_LIMIT):
            yield level, operations


class OperationsUnfilteredFetcher(DataFetcher[TezosTzktOperationData]):
    def __init__(
        self,
        datasource: TezosTzktDatasource,
        first_level: int,
        last_level: int,
        transactions: bool,
        originations: bool,
        migration_originations: bool,
    ) -> None:
        super().__init__(datasource, first_level, last_level)
        self._transactions = transactions
        self._originations = originations
        self._migration_originations = migration_originations

    @classmethod
    async def create(
        cls,
        config: TezosTzktOperationsUnfilteredIndexConfig,
        datasource: TezosTzktDatasource,
        first_level: int,
        last_level: int,
    ) -> OperationsUnfilteredFetcher:
        return OperationsUnfilteredFetcher(
            datasource=datasource,
            first_level=first_level,
            last_level=last_level,
            transactions=TezosTzktOperationType.transaction in config.types,
            originations=TezosTzktOperationType.origination in config.types,
            migration_originations=TezosTzktOperationType.migration in config.types,
        )

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[TezosTzktOperationData, ...]]]:
        """Iterate over operations fetched with multiple REST requests with different filters.

        Resulting data is split by level, deduped, sorted and ready to be processed by TezosTzktOperationsIndex.
        """
        channel_kwargs = {
            'buffer': self._buffer,
            'datasource': self._datasource,
            'first_level': self._first_level,
            'last_level': self._last_level,
        }
        channels: tuple[FetcherChannel[TezosTzktOperationData, Any], ...] = ()
        if self._transactions:
            channels += (
                OperationsUnfilteredFetcherChannel(
                    type=TezosTzktOperationType.transaction,
                    **channel_kwargs,  # type: ignore[arg-type]
                ),
            )
        if self._originations:
            channels += (
                OperationsUnfilteredFetcherChannel(
                    type=TezosTzktOperationType.origination,
                    **channel_kwargs,  # type: ignore[arg-type]
                ),
            )
        if self._migration_originations:
            channels += (
                MigrationOriginationFetcherChannel(
                    filter=set(),
                    **channel_kwargs,  # type: ignore[arg-type]
                ),
            )

        while True:
            min_channel = sorted(channels, key=lambda x: x.head)[0]
            await min_channel.fetch()

            # NOTE: It's a different channel now, but with greater head level
            min_channel = sorted(channels, key=lambda x: x.head)[0]
            min_head = min_channel.head

            while self._head <= min_head:
                if self._head in self._buffer:
                    operations = self._buffer.pop(self._head)
                    yield self._head, dedup_operations(tuple(operations))
                self._head += 1

            if all(c.fetched for c in channels):
                break

        if self._buffer:
            raise FrameworkException('Operations left in queue')
