import asyncio
import time
from asyncio import Queue
from collections import defaultdict
from collections import deque
from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any

from dipdup.config import HttpConfig
from dipdup.config.evm_node import EvmNodeDatasourceConfig
from dipdup.datasources import JsonRpcDatasource
from dipdup.datasources._web3 import create_web3_client
from dipdup.exceptions import DatasourceError
from dipdup.exceptions import FrameworkException
from dipdup.models._subsquid import SubsquidMessageType
from dipdup.models.evm import EvmEventData
from dipdup.models.evm import EvmTransactionData
from dipdup.models.evm_node import EvmNodeHeadData
from dipdup.models.evm_node import EvmNodeHeadSubscription
from dipdup.models.evm_node import EvmNodeLogsSubscription
from dipdup.models.evm_node import EvmNodeSubscription
from dipdup.models.evm_node import EvmNodeSyncingData
from dipdup.models.evm_node import EvmNodeSyncingSubscription
from dipdup.pysignalr import Message
from dipdup.pysignalr import WebsocketMessage
from dipdup.pysignalr import WebsocketTransport
from dipdup.utils import Watchdog

if TYPE_CHECKING:
    from web3 import AsyncWeb3


NODE_LEVEL_TIMEOUT = 0.1


HeadCallback = Callable[['EvmNodeDatasource', EvmNodeHeadData], Awaitable[None]]
LogsCallback = Callable[['EvmNodeDatasource', tuple[EvmEventData, ...]], Awaitable[None]]
TransactionsCallback = Callable[['EvmNodeDatasource', tuple[EvmTransactionData, ...]], Awaitable[None]]
SyncingCallback = Callable[['EvmNodeDatasource', EvmNodeSyncingData], Awaitable[None]]


@dataclass
class LevelData:
    head: dict[str, Any] | None = None
    events: deque[dict[str, Any]] = field(default_factory=deque)
    fetch_transactions: bool = False

    created_at: float = field(default_factory=time.time)

    async def get_head(self) -> dict[str, Any]:
        await self.wait_level()
        if not self.head:
            raise FrameworkException('LevelData event is set, but head is None')
        return self.head

    async def wait_level(self) -> None:
        to_wait = NODE_LEVEL_TIMEOUT - (time.time() - self.created_at)
        if to_wait > 0:
            await asyncio.sleep(to_wait)


class EvmNodeDatasource(JsonRpcDatasource[EvmNodeDatasourceConfig]):
    NODE_LAST_MILE = 128

    _default_http_config = HttpConfig(
        batch_size=10,
        ratelimit_sleep=1,
        polling_interval=1.0,
    )

    def __init__(self, config: EvmNodeDatasourceConfig, merge_subscriptions: bool = False) -> None:
        super().__init__(config)
        self._web3_client: AsyncWeb3 | None = None
        self._ws_client: WebsocketTransport | None = None
        self._requests: dict[str, tuple[asyncio.Event, Any]] = {}
        self._subscription_ids: dict[str, EvmNodeSubscription] = {}
        self._emitter_queue: Queue[LevelData] = Queue()
        self._level_data: defaultdict[str, LevelData] = defaultdict(LevelData)
        self._watchdog: Watchdog = Watchdog(self._http_config.connection_timeout)

        self._on_head_callbacks: set[HeadCallback] = set()
        self._on_events_callbacks: set[LogsCallback] = set()
        self._on_transactions_callbacks: set[TransactionsCallback] = set()
        self._on_syncing_callbacks: set[SyncingCallback] = set()

    @property
    def web3(self) -> 'AsyncWeb3':
        if not self._web3_client:
            raise FrameworkException('web3 client is not initialized; is datasource running?')
        return self._web3_client

    async def initialize(self) -> None:
        self._web3_client = await create_web3_client(self)
        level = await self.get_head_level()
        self.set_sync_level(None, level)

    async def run(self) -> None:
        if self.ws_available:
            await asyncio.gather(
                self._ws_loop(),
                self._emitter_loop(),
                self._watchdog.run(),
            )
        else:
            while True:
                level = await self.get_head_level()
                self.set_sync_level(None, level)
                await asyncio.sleep(self._http_config.polling_interval)

    async def _emitter_loop(self) -> None:
        known_level = 0

        while True:
            level_data = await self._emitter_queue.get()
            head = EvmNodeHeadData.from_json(
                await level_data.get_head(),
            )

            self._logger.info('New head: %s -> %s', known_level, head.level)
            await self.emit_head(head)

            # NOTE: Push rollback to all EVM indexes, but continue processing.
            if head.level <= known_level:
                for type_ in (
                    SubsquidMessageType.evm_blocks,
                    SubsquidMessageType.evm_logs,
                    SubsquidMessageType.evm_traces,
                    SubsquidMessageType.evm_transactions,
                ):
                    await self.emit_rollback(
                        type_,
                        from_level=known_level,
                        to_level=head.level - 1,
                    )

            known_level = head.level

            if raw_events := level_data.events:
                events = tuple(
                    EvmEventData.from_node_json(event, head.timestamp) for event in raw_events if not event['removed']
                )
                if events:
                    self._logger.debug('Emitting %s events', len(events))
                    await self.emit_events(events)
            if level_data.fetch_transactions:
                full_block = await self.get_block_by_level(
                    block_number=head.level,
                    full_transactions=True,
                )
                transactions = tuple(
                    EvmTransactionData.from_node_json(transaction, head.timestamp)
                    for transaction in full_block['transactions']
                )
                if transactions:
                    self._logger.debug('Emitting %s transactions', len(transactions))
                    await self.emit_transactions(transactions)

            del self._level_data[head.hash]

    @property
    def ws_available(self) -> bool:
        return self._config.ws_url is not None

    async def subscribe(self) -> None:
        if not self.ws_available:
            return

        missing_subscriptions = self._subscriptions.missing_subscriptions
        if not missing_subscriptions:
            return

        self._logger.info('Subscribing to %s channels', len(missing_subscriptions))
        for subscription in missing_subscriptions:
            if isinstance(subscription, EvmNodeSubscription):
                await self._subscribe(subscription)

    async def emit_head(self, head: EvmNodeHeadData) -> None:
        for fn in self._on_head_callbacks:
            await fn(self, head)

    async def emit_events(self, events: tuple[EvmEventData, ...]) -> None:
        for fn in self._on_events_callbacks:
            await fn(self, events)

    async def emit_syncing(self, syncing: EvmNodeSyncingData) -> None:
        for fn in self._on_syncing_callbacks:
            await fn(self, syncing)

    async def emit_transactions(self, transactions: tuple[EvmTransactionData, ...]) -> None:
        for fn in self._on_transactions_callbacks:
            await fn(self, transactions)

    def call_on_head(self, fn: HeadCallback) -> None:
        self._on_head_callbacks.add(fn)

    def call_on_events(self, fn: LogsCallback) -> None:
        self._on_events_callbacks.add(fn)

    def call_on_transactions(self, fn: TransactionsCallback) -> None:
        self._on_transactions_callbacks.add(fn)

    def call_on_syncing(self, fn: SyncingCallback) -> None:
        self._on_syncing_callbacks.add(fn)

    async def get_block_by_hash(self, block_hash: str) -> dict[str, Any]:
        return await self._jsonrpc_request('eth_getBlockByHash', [block_hash, True])  # type: ignore[no-any-return]

    async def get_block_by_level(self, block_number: int, full_transactions: bool = False) -> dict[str, Any]:
        return await self._jsonrpc_request('eth_getBlockByNumber', [hex(block_number), full_transactions])  # type: ignore[no-any-return]

    async def get_events(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._jsonrpc_request('eth_getLogs', [params])  # type: ignore[no-any-return]

    async def get_head_level(self) -> int:
        return int((await self._jsonrpc_request('eth_blockNumber', [])), 16)

    async def _subscribe(self, subscription: EvmNodeSubscription) -> None:
        self._logger.debug('Subscribing to %s', subscription)
        response = await self._jsonrpc_request(
            method='eth_subscribe',
            params=subscription.get_params(),
            ws=True,
        )
        self._subscription_ids[response] = subscription
        # NOTE: Is's likely unnecessary and/or unreliable, but node doesn't return sync level.
        level = await self.get_head_level()
        self._subscriptions.set_sync_level(subscription, level)

    async def _on_message(self, message: Message) -> None:
        # NOTE: pysignalr will eventually get a raw client
        if not isinstance(message, WebsocketMessage):
            raise FrameworkException(f'Unknown message type: {type(message)}')

        data = message.data
        self._watchdog.reset()

        if 'id' in data:
            request_id = data['id']
            self._logger.debug('Received response for request %s', request_id)
            if request_id not in self._requests:
                raise DatasourceError(f'Unknown request ID: {data["id"]}', self.name)

            event = self._requests[request_id][0]
            # NOTE: Don't unpack; processed later
            self._requests[request_id] = (event, data)
            event.set()
        elif 'method' in data:
            if data['method'] == 'eth_subscription':
                subscription_id = data['params']['subscription']
                if subscription_id not in self._subscription_ids:
                    raise FrameworkException(f'{self.name}: Unknown subscription ID: {subscription_id}')
                subscription = self._subscription_ids[subscription_id]
                await self._handle_subscription(subscription, data['params']['result'])
            else:
                raise DatasourceError(f'Unknown method: {data["method"]}', self.name)
        else:
            raise DatasourceError(f'Unknown message: {data}', self.name)

    async def _handle_subscription(self, subscription: EvmNodeSubscription, data: Any) -> None:
        if isinstance(subscription, EvmNodeHeadSubscription):
            level_data = self._level_data[data['hash']]
            level_data.head = data
            if subscription.transactions:
                level_data.fetch_transactions = True
            self._emitter_queue.put_nowait(level_data)
        elif isinstance(subscription, EvmNodeLogsSubscription):
            level_data = self._level_data[data['blockHash']]
            level_data.events.append(data)
        elif isinstance(subscription, EvmNodeSyncingSubscription):
            syncing = EvmNodeSyncingData.from_json(data)
            await self.emit_syncing(syncing)
        else:
            raise NotImplementedError
