import asyncio
import logging
import math
from copy import copy
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING
from scalecodec.base import RuntimeConfigurationObject
from scalecodec.base import ScaleBytes

import orjson
import pysignalr.exceptions

from dipdup.config import HttpConfig
from dipdup.config.substrate import SubstrateDatasourceConfigU
from dipdup.datasources import JsonRpcDatasource
from dipdup.exceptions import DatasourceError
from dipdup.models.substrate import SubstrateEventData
from dipdup.models.substrate_node import SubstrateNodeSubscription
from dipdup.pysignalr import Message
from dipdup.runtimes import SubstrateRuntime

if TYPE_CHECKING:
    from scalecodec.base import ScaleDecoder

_logger = logging.getLogger(__name__)


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

    async def run(self) -> None:
        if self.realtime:
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

    async def initialize(self) -> None:
        level = await self.get_head_level()
        self.set_sync_level(None, level)

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

    async def subscribe(self) -> None:
        if not self.realtime:
            return

        # TODO: Ensure substrate subscriptions list made correctly
        missing_subscriptions = self._subscriptions.missing_subscriptions
        if not missing_subscriptions:
            return

        self._logger.info('Subscribing to %s channels', len(missing_subscriptions))
        for subscription in missing_subscriptions:
            if isinstance(subscription, SubstrateNodeSubscription):
                await self._subscribe(subscription)

    async def _on_message(self, message: Message) -> None:
        raise NotImplementedError

    async def get_head_level(self) -> int:
        head = await self._jsonrpc_request('chain_getFinalizedHead', [])
        header = await self._jsonrpc_request('chain_getHeader', [head])
        return int(header['number'], 16)

    async def get_metadata_header(self, height: int) -> MetadataHeader:
        block_hash = await self.get_block_hash(height)
        rt = await self._jsonrpc_request('chain_getRuntimeVersion', [block_hash])
        return MetadataHeader(
            spec_name=rt['specName'],
            spec_version=rt['specVersion'],
            block_number=height,
            block_hash=block_hash,
        )
    
    async def get_full_block_by_level(self, height: int) -> dict:
        block_hash = await self.get_block_hash(height)
        return await self.get_full_block(block_hash)

    async def get_events_storage(self, hash: str) -> dict:
        return await self._jsonrpc_request('state_getStorageAt', [
            '0x26aa394eea5630e07c48ae0c9558cef780d41e5e16056765bc8461851072c9d7',
            hash
        ])

    async def get_events(self, height: int, decoder: SubstrateRuntime) -> tuple[SubstrateEventData]:
        # TODO: get info for storage request for events
        block_hash = await self.get_block_hash(height)
        header = await self._jsonrpc_request('chain_getHeader', [block_hash])
        #spec_version = header['specVersion']# for event decoding
        event_data = await self.get_events_storage(block_hash)
        runtime_config = decoder.runtime_config
        spec = decoder.get_spec_version('v701')

        # take type from runtime config

        # add runtime metadata using metadata kwarg
        scale_object = runtime_config.create_scale_object(
            'Vec<EventRecord>', metadata=spec._metadata
        )
        event_bytes = ScaleBytes(event_data)
        event = scale_object.decode(event_bytes)

        async for line in block:
            block_data = orjson.loads(line)
            
            # Extract events from onInitialize
            for event in block_data.get('onInitialize', {}).get('events', []):
                SubstrateEventData(method=event['method'], data=event['data'])
            
            # Extract events from extrinsics
            for extrinsic in block_data.get('extrinsics', []):
                for event in extrinsic.get('events', []):
                    SubstrateEventData(method=event['method'], data=event['data'])
            
            # Extract events from onFinalize
            for event in block_data.get('onFinalize', {}).get('events', []):
                SubstrateEventData(method=event['method'], data=event['data'])
        
        return tuple()

    async def get_block_hash(self, height: int) -> str:
        return await self._jsonrpc_request('chain_getBlockHash', [height])
    
    async def get_full_block(self, hash: str) -> dict:
        return await self._jsonrpc_request('chain_getBlock', [hash])

    async def get_metadata_header_batch(self, heights: list[int]) -> list[MetadataHeader]:
        return await asyncio.gather(*[self.get_metadata_header(h) for h in heights])

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
        ... # TODO: make subscription request to node using subscription.method


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
