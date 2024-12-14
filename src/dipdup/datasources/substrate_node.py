import asyncio
import logging
import math
from asyncio import Queue
from collections.abc import Awaitable
from collections.abc import Callable
from copy import copy
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

import orjson
import pysignalr.exceptions

from dipdup.config import HttpConfig
from dipdup.config.substrate import SubstrateDatasourceConfigU
from dipdup.datasources import JsonRpcDatasource
from dipdup.exceptions import DatasourceError
from dipdup.exceptions import FrameworkException
from dipdup.models.substrate import BlockHeader
from dipdup.models.substrate import HeadBlock
from dipdup.models.substrate import SubstrateEventData
from dipdup.models.substrate import SubstrateEventDataDict
from dipdup.models.substrate_node import SubstrateNodeHeadSubscription
from dipdup.models.substrate_node import SubstrateNodeSubscription
from dipdup.pysignalr import Message
from dipdup.pysignalr import WebsocketMessage
from dipdup.utils import Watchdog

_logger = logging.getLogger(__name__)


HeadCallback = Callable[['SubstrateNodeDatasource', HeadBlock], Awaitable[None]]
EventCallback = Callable[['SubstrateNodeDatasource', tuple[SubstrateEventData, ...]], Awaitable[None]]


# NOTE: Renamed entity class LevelData from evm_node
@dataclass
class SubscriptionMessage:
    head: HeadBlock
    fetch_events: bool = False


@dataclass
class MetadataVersion:
    spec_name: str
    spec_version: int
    block_number: int
    block_hash: str
    metadata: str | None = None

    @property
    def key(self) -> str:
        return f'{self.spec_name}@{self.spec_version}'


MetadataHeader = MetadataVersion


def equal_specs(a: MetadataVersion, b: MetadataVersion) -> bool:
    return a.spec_name == b.spec_name and a.spec_version == b.spec_version


@dataclass
class MetadataStorage:
    path: Path
    versions: list[MetadataVersion] = field(default_factory=list)

    def load_file(self) -> None:
        if self.path.name.endswith('.jsonl'):
            self.versions = []
            for line in self.path.read_text().splitlines():
                if not line:
                    continue
                version = MetadataVersion(**orjson.loads(line))
                self.versions.append(version)
        elif self.path.name.endswith('.json'):
            self.versions = [MetadataVersion(**i) for i in orjson.loads(self.path.read_bytes())]
        else:
            raise ValueError(f'Unsupported file type: {self.path}')

    def save_file(self) -> None:
        if self.path.name.endswith('.jsonl'):
            self.path.write_bytes(b'\n'.join(orjson.dumps(version.__dict__) for version in self.versions))
        elif self.path.name.endswith('.json'):
            self.path.write_bytes(orjson.dumps(self.versions))
        else:
            raise ValueError(f'Unsupported file type: {self.path}')


class SubstrateNodeDatasource(JsonRpcDatasource[SubstrateDatasourceConfigU]):
    _default_http_config = HttpConfig(
        batch_size=20,
    )

    def __init__(self, config: SubstrateDatasourceConfigU) -> None:
        from aiosubstrate.base import SubstrateInterface

        super().__init__(config)
        self._pending_subscription = None
        self._subscription_ids: dict[str, SubstrateNodeSubscription] = {}
        self._interface = SubstrateInterface(config.url)

        self._emitter_queue: Queue[SubscriptionMessage] = Queue()

        self._watchdog: Watchdog = Watchdog(self._http_config.connection_timeout)

        self._on_head_callbacks: set[HeadCallback] = set()
        self._on_event_callbacks: set[EventCallback] = set()

    async def run(self) -> None:
        if self.realtime:
            await asyncio.gather(
                self._ws_loop(),
                self._emitter_loop(),
                # self._watchdog.run(),
            )
        else:
            while True:
                level = await self.get_head_level()
                self.set_sync_level(None, level)
                await asyncio.sleep(self._http_config.polling_interval)

    async def initialize(self) -> None:
        level = await self.get_head_level()
        self.set_sync_level(None, level)

        # NOTE: Prepare substrate_interface
        await self._interface.init_props()
        self._interface.reload_type_registry()

    async def _ws_loop(self) -> None:
        # TODO: probably add to inheritance WebsocketSubscriptionDatasource, and move this method there
        self._logger.info('Establishing realtime connection')
        client = self._get_ws_client()
        retry_sleep = self._http_config.retry_sleep

        for _ in range(1, self._http_config.retry_count + 1):
            try:
                await client.run()
            except pysignalr.exceptions.ConnectionError as e:
                self._logger.error('Websocket connection error: %s', e)
                await self.emit_disconnected()
                await asyncio.sleep(retry_sleep)
                retry_sleep *= self._http_config.retry_multiplier

        raise DatasourceError('Websocket connection failed', self.name)

    @property
    def realtime(self) -> bool:
        return self._config.ws_url is not None

    async def subscribe(self) -> None:
        if not self.realtime:
            return

        missing_subscriptions = self._subscriptions.missing_subscriptions
        if not missing_subscriptions:
            return

        self._logger.info('Subscribing to %s channels', len(missing_subscriptions))
        for subscription in missing_subscriptions:
            if isinstance(subscription, SubstrateNodeSubscription):
                await self._subscribe(subscription)

    async def emit_head(self, head: HeadBlock) -> None:
        for fn in self._on_head_callbacks:
            await fn(self, head)

    async def emit_events(self, events: tuple[SubstrateEventData, ...]) -> None:
        for fn in self._on_event_callbacks:
            await fn(self, events)

    def call_on_head(self, fn: HeadCallback) -> None:
        self._on_head_callbacks.add(fn)

    def call_on_events(self, fn: EventCallback) -> None:
        self._on_event_callbacks.add(fn)

    async def _on_message(self, message: Message) -> None:
        if not isinstance(message, WebsocketMessage):
            raise FrameworkException(f'Unknown message type: {type(message)}')

        data = message.data

        if 'id' in data:

            # NOTE: Save subscription id
            if self._pending_subscription:
                self._subscription_ids[data['result']] = self._pending_subscription
                self._requests[data['id']] = (self._requests[data['id']][0], data)
                self._requests[data['id']][0].set()

                # NOTE: Possibly unreliable logic from evm_node, and possibly too time consuming for message handling
                level = await self.get_head_level()
                self._subscriptions.set_sync_level(self._pending_subscription, level)

                # NOTE: Set None to identify possible subscriptions conflicts
                self._pending_subscription = None
            else:
                raise Exception
        elif 'method' in data and data['method'].startswith('chain_'):
            subscription_id = data['params']['subscription']
            if subscription_id not in self._subscription_ids:
                raise FrameworkException(f'{self.name}: Unknown subscription ID: {subscription_id}')
            subscription = self._subscription_ids[subscription_id]
            await self._handle_subscription(subscription, data['params']['result'])
        else:
            raise DatasourceError(f'Unknown message: {data}', self.name)

    async def get_head_level(self) -> int:
        head = await self._jsonrpc_request('chain_getFinalizedHead', [])
        header = await self._jsonrpc_request('chain_getHeader', [head])
        return int(header['number'], 16)

    async def get_block_hash(self, height: int) -> str:
        return await self._jsonrpc_request('chain_getBlockHash', [height])

    async def get_block_header(self, hash: str) -> BlockHeader:
        response = await self._jsonrpc_request('chain_getHeader', [hash])
        return {'hash': hash,
                'number': int(response['number'], 16),
                'prevRoot': response['parentHash']}

    async def get_metadata_header(self, height: int) -> MetadataHeader:
        block_hash = await self.get_block_hash(height)
        rt = await self._jsonrpc_request('chain_getRuntimeVersion', [block_hash])
        return MetadataHeader(
            spec_name=rt['specName'],
            spec_version=rt['specVersion'],
            block_number=height,
            block_hash=block_hash,
        )

    async def get_metadata_header_batch(self, heights: list[int]) -> list[MetadataHeader]:
        return await asyncio.gather(*[self.get_metadata_header(h) for h in heights])

    async def get_full_block(self, hash: str) -> dict:
        return await self._jsonrpc_request('chain_getBlock', [hash])

    async def get_events(self, block_hash: str) -> tuple[SubstrateEventDataDict, ...]:
        events = await self._interface.get_events(block_hash)

        res_events: list[SubstrateEventDataDict] = []
        for event in events:
            event: dict = event.decode()
            res_events.append({
                'name': f'{event['module_id']}.{event['event_id']}',
                'index': event['event_index'],
                'extrinsicIndex': event['extrinsic_idx'],
                'callAddress': None,
                'args': None,
                'decoded_args': event['attributes'],
            })

        return tuple(res_events)

    async def find_metadata_versions(
        self,
        from_block: int | None = None,
        to_block: int | None = None,
    ) -> list[MetadataHeader]:
        height = await self.get_head_level()

        first_block = from_block or 0
        last_block = min(to_block, height) if to_block is not None else height
        if first_block > last_block:
            raise StopAsyncIteration

        queue: list[tuple[MetadataVersion, MetadataVersion]] = []
        versions: dict[str, MetadataVersion] = {}

        beg, end = await self.get_metadata_header_batch([first_block, last_block])
        versions[beg.key] = beg

        if not equal_specs(beg, end):
            versions[end.key] = end
            queue.append((beg, end))

        step = 0
        while queue:
            batch = queue[: self._http_config.batch_size]
            queue = queue[self._http_config.batch_size :]

            step += 1
            _logger.info('step %s, %s versions found so far', step, len(versions))

            heights = [b.block_number + math.floor((e.block_number - b.block_number) / 2) for b, e in batch]
            new_versions = await self.get_metadata_header_batch(heights)
            for (b, e), m in zip(batch, new_versions, strict=False):
                if not equal_specs(b, m):
                    versions[m.key] = m
                if not equal_specs(b, m) and m.block_number - b.block_number > 1:
                    queue.append((b, m))
                if not equal_specs(m, e) and e.block_number - m.block_number > 1:
                    queue.append((m, e))

        return sorted(versions.values(), key=lambda x: x.block_number)

    async def get_raw_metadata(self, block_hash: str) -> str:
        return await self._jsonrpc_request('state_getMetadata', [block_hash])  # type: ignore[no-any-return]

    async def get_dev_metadata_version(self) -> MetadataVersion | None:
        genesis = await self.get_metadata_header(0)
        height = await self.get_head_level()
        last = await self.get_metadata_header(height)
        if genesis == last:
            return genesis
        return None

    async def _subscribe(self, subscription: SubstrateNodeSubscription) -> None:
        self._logger.debug('Subscribing to %s', subscription)
        self._pending_subscription = subscription
        response = await self._jsonrpc_request(subscription.method, params=[], ws=True)
        self._subscription_ids[response] = subscription

    async def _handle_subscription(self, subscription: SubstrateNodeSubscription, data: Any) -> None:
        if isinstance(subscription, SubstrateNodeHeadSubscription):
            self._emitter_queue.put_nowait(SubscriptionMessage(head=data, fetch_events=True))
        else:
            raise NotImplementedError

    async def _emitter_loop(self) -> None:
        while True:
            level_data: SubscriptionMessage = await self._emitter_queue.get()

            level = int(level_data.head['number'], 16)
            self._logger.info('New head: %s', level)
            await self.emit_head(level_data.head)

            # NOTE: subscribing to finalized head, no rollback required

            if level_data.fetch_events:
                block_hash = await self.get_block_hash(level)
                event_dicts = await self.get_events(block_hash)
                block_header = await self.get_block_header(block_hash)
                events = tuple(SubstrateEventData(**event_dict, header=block_header) for event_dict in event_dicts)
                await self.emit_events(events)


# FIXME: Not used, should be a subscan replacement
async def fetch_metadata(
    datasource: SubstrateNodeDatasource,
    storage: MetadataStorage,
    from_block: int | None = None,
    to_block: int | None = None,
) -> None:
    matched = 0
    for version in storage.versions:
        _logger.info('checking %s block %s against current chain', version.key, version.block_number)
        current = await datasource.get_metadata_header(version.block_number)
        if current and current.block_hash and version.block_hash.startswith(current.block_hash):
            matched += 1
        else:
            _logger.info('record mismatch')
            break

    if matched > 0:
        if matched != len(storage.versions):
            storage.versions = storage.versions[:matched]
            storage.save_file()
        last_known = storage.versions[-1]
        from_block = max(last_known.block_number, from_block or 0)
        _logger.info('exploring chain from block %s, from_block')
        new_versions = (await datasource.find_metadata_versions(from_block, to_block))[1:]
        _logger.info('%s new versions found', len(new_versions))
    elif not storage.versions:
        from_block = from_block or 0
        _logger.info('exploring chain from block %s', from_block)
        new_versions = await datasource.find_metadata_versions(from_block, to_block)
        _logger.info('%s new versions found', len(new_versions))
    else:
        last_known = storage.versions[-1]
        new_version = await datasource.get_dev_metadata_version()
        if new_version is None or (
            new_version.spec_name == last_known.spec_name and last_known.spec_version > new_version.spec_version
        ):
            raise ValueError("Output file already contains data for a different chain, don't know how to proceed.")
        if new_version.spec_name == last_known.spec_name and new_version.spec_version == last_known.spec_version:
            _logger.info('replacing metadata for %s, assuming it came from dev runtime', last_known.key)
            storage.versions = storage.versions[:-1]
            storage.save_file()
        new_versions = [new_version]

    for header in new_versions:
        version = copy(header)
        version.metadata = await datasource.get_raw_metadata(version.block_hash)
        storage.versions.append(version)
        _logger.info('saved %s block %s', version.key, version.block_number)

    storage.save_file()
