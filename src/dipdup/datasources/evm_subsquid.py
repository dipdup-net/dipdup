from collections import defaultdict
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from dipdup.config.evm_subsquid import EvmSubsquidDatasourceConfig
from dipdup.datasources._subsquid import AbstractSubsquidDatasource
from dipdup.datasources._subsquid import AbstractSubsquidWorker
from dipdup.models.evm import EvmEventData
from dipdup.models.evm import EvmTransactionData
from dipdup.models.evm_subsquid import FieldSelection
from dipdup.models.evm_subsquid import LogRequest
from dipdup.models.evm_subsquid import Query
from dipdup.models.evm_subsquid import TransactionRequest

_LOG_FIELDS: FieldSelection = {
    'block': {
        'timestamp': True,
    },
    'log': {
        'logIndex': True,
        'transactionIndex': True,
        'transactionHash': True,
        'address': True,
        'data': True,
        'topics': True,
    },
}
_TRANSACTION_FIELDS: FieldSelection = {
    'block': {
        'timestamp': True,
    },
    'transaction': {
        # 'accessList': True,
        'chainId': True,
        'contractAddress': True,
        'cumulativeGasUsed': True,
        'effectiveGasPrice': True,
        'from': True,
        'gasPrice': True,
        'gas': True,
        'gasUsed': True,
        'hash': True,
        'input': True,
        'maxFeePerGas': True,
        'maxPriorityFeePerGas': True,
        'nonce': True,
        'r': True,
        'sighash': True,
        'status': True,
        's': True,
        'to': True,
        'transactionIndex': True,
        'type': True,
        'value': True,
        'v': True,
        'yParity': True,
    },
}


class _EvmSubsquidWorker(AbstractSubsquidWorker[Query]):
    pass


class EvmSubsquidDatasource(AbstractSubsquidDatasource[EvmSubsquidDatasourceConfig, Query]):

    def __init__(self, config: EvmSubsquidDatasourceConfig) -> None:
        super().__init__(config)

    async def _get_worker(self, level: int) -> _EvmSubsquidWorker:
        return _EvmSubsquidWorker(await self._fetch_worker(level))

    async def query_worker(self, query: Query, current_level: int) -> list[dict[str, Any]]:
        return await super().query_worker(query, current_level)

    async def iter_events(
        self,
        topics: tuple[tuple[str | None, str], ...],
        first_level: int,
        last_level: int,
    ) -> AsyncIterator[tuple[EvmEventData, ...]]:
        current_level = first_level

        # TODO: Smarter query optimizator
        topics_by_address = defaultdict(list)
        for address, topic in topics:
            topics_by_address[address].append(topic)

        log_request: list[LogRequest] = []
        for address, topic_list in topics_by_address.items():
            if address:
                log_request.append(LogRequest(address=[address], topic0=topic_list))
            else:
                log_request.append(LogRequest(topic0=topic_list))

        while current_level <= last_level:
            query: Query = {
                'logs': log_request,
                'fields': _LOG_FIELDS,
                'fromBlock': current_level,
                'toBlock': last_level,
            }
            response = await self.query_worker(query, current_level)

            for level_item in response:
                current_level = level_item['header']['number'] + 1
                logs: deque[EvmEventData] = deque()
                for raw_log in level_item['logs']:
                    logs.append(
                        EvmEventData.from_subsquid_json(
                            event_json=raw_log,
                            header=level_item['header'],
                        ),
                    )
                yield tuple(logs)

    async def iter_transactions(
        self,
        first_level: int,
        last_level: int,
        filters: tuple[TransactionRequest, ...],
    ) -> AsyncIterator[tuple[EvmTransactionData, ...]]:
        current_level = first_level

        while current_level <= last_level:
            query: Query = {
                'fields': _TRANSACTION_FIELDS,
                'fromBlock': current_level,
                'toBlock': last_level,
                'transactions': list(filters),
            }
            response = await self.query_worker(query, current_level)

            for level_item in response:
                current_level = level_item['header']['number'] + 1
                transactions: deque[EvmTransactionData] = deque()
                for raw_transaction in level_item['transactions']:
                    transaction = EvmTransactionData.from_subsquid_json(
                        transaction_json=raw_transaction,
                        header=level_item['header'],
                    )
                    # NOTE: `None` falue is for chains and block ranges not compliant with the post-Byzantinum
                    # hard fork EVM specification (e.g. before 4.370,000 on Ethereum).
                    if transaction.status != 0:
                        transactions.append(transaction)
                yield tuple(transactions)
