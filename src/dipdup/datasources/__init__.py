import asyncio
import time
from abc import abstractmethod
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any
from typing import Generic
from typing import TypeVar
from uuid import uuid4

from pysignalr.messages import CompletionMessage

from dipdup.config import DatasourceConfig
from dipdup.config import HttpConfig
from dipdup.config import IndexConfig
from dipdup.config import ResolvedHttpConfig
from dipdup.exceptions import DatasourceError
from dipdup.exceptions import FrameworkException
from dipdup.http import HTTPGateway
from dipdup.models import MessageType
from dipdup.performance import metrics
from dipdup.pysignalr import Message
from dipdup.pysignalr import WebsocketMessage
from dipdup.pysignalr import WebsocketProtocol
from dipdup.pysignalr import WebsocketTransport
from dipdup.subscriptions import Subscription
from dipdup.subscriptions import SubscriptionManager
from dipdup.utils import FormattedLogger

DatasourceConfigT = TypeVar('DatasourceConfigT', bound=DatasourceConfig)


EmptyCallback = Callable[[], Awaitable[None]]
RollbackCallback = Callable[['IndexDatasource[Any]', MessageType, int, int], Awaitable[None]]


class Datasource(HTTPGateway, Generic[DatasourceConfigT]):
    _default_http_config = HttpConfig()

    def __init__(self, config: DatasourceConfigT) -> None:
        self._config = config
        http_config = ResolvedHttpConfig.create(self._default_http_config, config.http)
        http_config.alias = http_config.alias or config.name
        super().__init__(
            url=config.url,
            http_config=http_config,
        )
        self._logger = FormattedLogger(__name__, config.name + ': {}')

    @property
    def name(self) -> str:
        return self._config.name

    async def run(self) -> None:
        pass


class AbiDatasource(Datasource[DatasourceConfigT], Generic[DatasourceConfigT]):
    @abstractmethod
    async def get_abi(self, address: str) -> dict[str, Any]: ...


# FIXME: inconsistent usage
class IndexDatasource(Datasource[DatasourceConfigT], Generic[DatasourceConfigT]):
    def __init__(
        self,
        config: DatasourceConfigT,
        merge_subscriptions: bool = False,
    ) -> None:
        super().__init__(config)
        self._subscriptions: SubscriptionManager = SubscriptionManager(merge_subscriptions)
        self._on_connected_callbacks: set[EmptyCallback] = set()
        self._on_disconnected_callbacks: set[EmptyCallback] = set()
        self._on_rollback_callbacks: set[RollbackCallback] = set()

    @abstractmethod
    async def run(self) -> None: ...

    @abstractmethod
    async def subscribe(self) -> None: ...

    @abstractmethod
    async def initialize(self) -> None: ...

    def attach_index(self, index_config: IndexConfig) -> None:
        """Register index config in internal mappings and matchers. Find and register subscriptions."""
        for subscription in index_config.get_subscriptions():
            self._subscriptions.add(subscription)

    def set_sync_level(self, subscription: Subscription | None, level: int) -> None:
        self._subscriptions.set_sync_level(subscription, level)

    def get_sync_level(self, subscription: Subscription) -> int | None:
        return self._subscriptions.get_sync_level(subscription)

    def call_on_connected(self, fn: EmptyCallback) -> None:
        self._on_connected_callbacks.add(fn)

    def call_on_disconnected(self, fn: EmptyCallback) -> None:
        self._on_disconnected_callbacks.add(fn)

    def call_on_rollback(self, fn: RollbackCallback) -> None:
        self._on_rollback_callbacks.add(fn)

    async def emit_connected(self) -> None:
        for fn in self._on_connected_callbacks:
            await fn()

    async def emit_disconnected(self) -> None:
        for fn in self._on_disconnected_callbacks:
            await fn()

    async def emit_rollback(self, type_: MessageType, from_level: int, to_level: int) -> None:
        for fn in self._on_rollback_callbacks:
            await fn(self, type_, from_level, to_level)


# FIXME: Not necessary a index datasource
class WebsocketDatasource(IndexDatasource[DatasourceConfigT]):
    def __init__(self, config: DatasourceConfigT) -> None:
        super().__init__(config)
        self._ws_client: WebsocketTransport | None = None

    @abstractmethod
    async def _on_message(self, message: Message) -> None: ...

    async def _on_error(self, message: CompletionMessage) -> None:
        raise DatasourceError(f'RPC error: {message}', self.name)

    async def _on_connected(self) -> None:
        self._logger.info('Realtime connection established')
        # NOTE: Subscribing here will block WebSocket loop, don't do it.
        await self.emit_connected()

    async def _on_disconnected(self) -> None:
        self._logger.info('Realtime connection lost, resetting subscriptions')
        self._subscriptions.reset()
        await self.emit_disconnected()

    def _get_ws_client(self) -> WebsocketTransport:
        if self._ws_client:
            return self._ws_client

        self._logger.debug('Creating Websocket client')

        # FIXME: correct config class
        url = self._config.ws_url  # type: ignore
        if not url:
            raise FrameworkException('Spawning node datasource, but `ws_url` is not set')
        self._ws_client = WebsocketTransport(
            url=url,
            protocol=WebsocketProtocol(),
            callback=self._on_message,
            skip_negotiation=True,
            connection_timeout=self._http_config.connection_timeout,
        )

        self._ws_client.on_open(self._on_connected)
        self._ws_client.on_close(self._on_disconnected)
        self._ws_client.on_error(self._on_error)

        return self._ws_client


# FIXME: Not necessary a WS datasource
class JsonRpcDatasource(WebsocketDatasource[DatasourceConfigT]):
    NODE_LAST_MILE = 0

    def __init__(self, config: DatasourceConfigT) -> None:
        super().__init__(config)
        self._requests: dict[str, tuple[asyncio.Event, Any]] = {}

    async def _jsonrpc_request(
        self,
        method: str,
        params: Any,
        raw: bool = False,
        ws: bool = False,
    ) -> Any:
        request_id = uuid4().hex
        request = {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': method,
            'params': params,
        }
        self._logger.debug('JSON-RPC request: %s', request)

        if ws:
            started_at = time.time()
            event = asyncio.Event()
            self._requests[request_id] = (event, None)

            message = WebsocketMessage(request)
            client = self._get_ws_client()

            async def _request() -> None:
                await client.send(message)
                await event.wait()

            await asyncio.wait_for(
                _request(),
                timeout=self._http_config.request_timeout,
            )
            data = self._requests[request_id][1]
            del self._requests[request_id]

            metrics.time_in_requests[self.name] += time.time() - started_at
            metrics.requests_total[self.name] += 1
        else:
            data = await self.request(
                method='post',
                url='',
                json=request,
            )

        if raw:
            return data

        if 'error' in data:
            raise DatasourceError(data['error']['message'], self.name)
        return data['result']

    # TODO: probably should be defined higher
    @abstractmethod
    async def get_head_level(self) -> int: ...


def create_datasource(config: DatasourceConfig) -> Datasource[Any]:
    from dipdup.config.abi_etherscan import AbiEtherscanDatasourceConfig
    from dipdup.config.coinbase import CoinbaseDatasourceConfig
    from dipdup.config.evm_node import EvmNodeDatasourceConfig
    from dipdup.config.evm_subsquid import EvmSubsquidDatasourceConfig
    from dipdup.config.http import HttpDatasourceConfig
    from dipdup.config.ipfs import IpfsDatasourceConfig
    from dipdup.config.starknet_node import StarknetNodeDatasourceConfig
    from dipdup.config.starknet_subsquid import StarknetSubsquidDatasourceConfig
    from dipdup.config.tezos_tzkt import TezosTzktDatasourceConfig
    from dipdup.config.tzip_metadata import TzipMetadataDatasourceConfig
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

    by_config: dict[type[DatasourceConfig], type[Datasource[Any]]] = {
        AbiEtherscanDatasourceConfig: AbiEtherscanDatasource,
        CoinbaseDatasourceConfig: CoinbaseDatasource,
        TezosTzktDatasourceConfig: TezosTzktDatasource,
        TzipMetadataDatasourceConfig: TzipMetadataDatasource,
        HttpDatasourceConfig: HttpDatasource,
        IpfsDatasourceConfig: IpfsDatasource,
        EvmSubsquidDatasourceConfig: EvmSubsquidDatasource,
        EvmNodeDatasourceConfig: EvmNodeDatasource,
        StarknetSubsquidDatasourceConfig: StarknetSubsquidDatasource,
        StarknetNodeDatasourceConfig: StarknetNodeDatasource,
    }

    try:
        return by_config[type(config)](config)
    except KeyError as e:
        raise FrameworkException(f'Unknown datasource type: {type(config)}') from e
