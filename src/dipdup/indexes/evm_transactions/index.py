from collections import deque
from typing import Any

from dipdup.config.evm_transactions import EvmTransactionsIndexConfig
from dipdup.datasources.evm_node import EvmNodeDatasource
from dipdup.datasources.evm_subsquid import EvmSubsquidDatasource
from dipdup.indexes.evm import EvmIndex
from dipdup.indexes.evm import get_sighash
from dipdup.indexes.evm_transactions.fetcher import EvmNodeTransactionFetcher
from dipdup.indexes.evm_transactions.fetcher import EvmSubsquidTransactionFetcher
from dipdup.indexes.evm_transactions.matcher import match_transactions
from dipdup.models import RollbackMessage
from dipdup.models._subsquid import SubsquidMessageType
from dipdup.models.evm import EvmTransactionData
from dipdup.models.evm_subsquid import TransactionRequest
from dipdup.performance import metrics

QueueItem = tuple[EvmTransactionData, ...] | RollbackMessage
EvmDatasource = EvmSubsquidDatasource | EvmNodeDatasource


class EvmTransactionsIndex(
    EvmIndex[EvmTransactionsIndexConfig, QueueItem, EvmDatasource],
    message_type=SubsquidMessageType.evm_transactions,
):
    def _match_level_data(self, handlers: Any, level_data: Any) -> deque[Any]:
        return match_transactions(
            package=self._ctx.package,
            handlers=handlers,
            transactions=level_data,
        )

    async def _synchronize_subsquid(self, sync_level: int) -> None:
        first_level = self.state.level + 1
        fetcher = self._create_subsquid_fetcher(first_level, sync_level)

        async for _level, transactions in fetcher.fetch_by_level():
            await self._process_level_data(transactions, sync_level)
            metrics._sqd_processor_last_block = _level

    async def _synchronize_node(self, sync_level: int) -> None:
        first_level = self.state.level + 1
        fetcher = self._create_node_fetcher(first_level, sync_level)

        async for _level, transactions in fetcher.fetch_by_level():
            await self._process_level_data(transactions, sync_level)
            metrics._sqd_processor_last_block = _level

    def _create_subsquid_fetcher(self, first_level: int, last_level: int) -> EvmSubsquidTransactionFetcher:

        filters: deque[TransactionRequest] = deque()
        for handler_config in self._config.handlers:
            query: TransactionRequest = {}
            if (from_ := handler_config.from_) and from_.address:
                query['from'] = [from_.address]
            if (to_ := handler_config.to) and to_.address:
                query['to'] = [to_.address]
            if handler_config.method or handler_config.signature:
                sighash = get_sighash(
                    package=self._ctx.package,
                    method=handler_config.method,
                    signature=handler_config.signature,
                    to=to_,
                )
                query['sighash'] = [sighash]
            if not query:
                raise NotImplementedError
            filters.append(query)

        return EvmSubsquidTransactionFetcher(
            name=self.name,
            datasources=self.subsquid_datasources,
            first_level=first_level,
            last_level=last_level,
            filters=tuple(filters),
        )

    def _create_node_fetcher(self, first_level: int, last_level: int) -> EvmNodeTransactionFetcher:
        return EvmNodeTransactionFetcher(
            name=self.name,
            datasources=self.node_datasources,
            first_level=first_level,
            last_level=last_level,
        )
