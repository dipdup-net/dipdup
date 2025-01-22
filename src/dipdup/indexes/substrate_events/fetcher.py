import asyncio
from collections.abc import AsyncIterator
from collections.abc import Iterable
from contextlib import suppress
from typing import Any

from dipdup.datasources.substrate_node import SubstrateNodeDatasource
from dipdup.datasources.substrate_subsquid import SubstrateSubsquidDatasource
from dipdup.indexes.substrate_node import SubstrateNodeFetcher
from dipdup.indexes.substrate_subsquid import SubstrateSubsquidFetcher
from dipdup.models.substrate import SubstrateEventData

# NOTE: Don't increase buffer beyond this limit when fetching event data from three channels
EVENTS_QUEUE_LIMIT = 50


class SubstrateSubsquidEventFetcher(SubstrateSubsquidFetcher[SubstrateEventData]):
    def __init__(
        self,
        name: str,
        datasources: tuple[SubstrateSubsquidDatasource, ...],
        first_level: int,
        last_level: int,
        names: tuple[str, ...],
    ) -> None:
        super().__init__(
            name=name,
            datasources=datasources,
            first_level=first_level,
            last_level=last_level,
        )
        self._names = names

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[SubstrateEventData, ...]]]:
        async for level, events in self.readahead_by_level(self.fetch_events()):
            yield level, events

    async def fetch_events(self) -> AsyncIterator[tuple[SubstrateEventData, ...]]:
        async for events in self.random_datasource.iter_events(
            first_level=self._first_level,
            last_level=self._last_level,
            names=self._names,
        ):
            yield tuple(SubstrateEventData.from_subsquid(event) for event in events)


class SubstrateNodeEventFetcher(SubstrateNodeFetcher[SubstrateEventData]):
    def __init__(
        self,
        name: str,
        datasources: tuple[SubstrateNodeDatasource, ...],
        first_level: int,
        last_level: int,
    ) -> None:
        super().__init__(
            name=name,
            datasources=datasources,
            first_level=first_level,
            last_level=last_level,
        )

    async def fetch_by_level(self) -> AsyncIterator[tuple[int, tuple[SubstrateEventData, ...]]]:
        async for level, events in self.readahead_by_level(self.fetch_events()):
            yield level, events

    # TODO: Make this code more generic, something like chained `FetcherChannel` class
    async def fetch_events(self) -> AsyncIterator[tuple[SubstrateEventData, ...]]:
        node = self.get_random_node()
        batch_size = node._http_config.batch_size

        queues: dict[str, asyncio.Queue[Any]] = {
            'levels': asyncio.Queue(),
            'hashes': asyncio.Queue(),
            'headers': asyncio.Queue(),
            'events': asyncio.Queue(),
        }

        for level in range(self._first_level, self._last_level + 1):
            await queues['levels'].put(level)

        async def _hashes_loop() -> None:
            async def _batch(levels: Iterable[int]) -> None:
                block_hashes = await asyncio.gather(
                    *(node.get_block_hash(level) for level in levels),
                )
                for block_hash in block_hashes:
                    await queues['hashes'].put(block_hash)
                if queues['hashes'].qsize() >= EVENTS_QUEUE_LIMIT:
                    await asyncio.sleep(1)

            batch = []
            while queues['levels'].qsize() > 0:
                batch.append(await queues['levels'].get())
                if len(batch) >= batch_size:
                    await _batch(batch)
                    batch = []

            if batch:
                await _batch(batch)

        async def _headers_loop() -> None:
            async def _batch(hashes: Iterable[str]) -> None:
                block_headers = await asyncio.gather(
                    *(node.get_block_header(hash_) for hash_ in hashes),
                )
                for block_header in block_headers:
                    await queues['headers'].put(block_header)
                if queues['headers'].qsize() >= EVENTS_QUEUE_LIMIT:
                    await asyncio.sleep(1)

            batch = []
            while True:
                block_hash = await queues['hashes'].get()
                batch.append(block_hash)
                if len(batch) >= batch_size:
                    await _batch(batch)
                    batch = []

                if queues['levels'].qsize() == 0 and queues['hashes'].qsize() == 0:
                    break

            if batch:
                await _batch(batch)

        async def _events_loop() -> None:
            async def _batch(headers: Iterable[dict[str, Any]]) -> None:
                block_events = await asyncio.gather(
                    *(node.get_events(header['hash']) for header in headers),
                )
                for header, events in zip(headers, block_events, strict=True):
                    await queues['events'].put((header, events))

            batch = []
            while True:
                block_header = await queues['headers'].get()
                batch.append(block_header)
                if len(batch) >= batch_size:
                    await _batch(batch)
                    batch = []

                if queues['levels'].qsize() == 0 and queues['hashes'].qsize() == 0 and queues['headers'].qsize() == 0:
                    break

            if batch:
                await _batch(batch)

        async def _log_loop() -> None:
            while True:
                await asyncio.sleep(1)
                self._logger.debug(
                    'queues: levels=%d hashes=%d headers=%d events=%d',
                    queues['levels'].qsize(),
                    queues['hashes'].qsize(),
                    queues['headers'].qsize(),
                    queues['events'].qsize(),
                )

        tasks = (
            asyncio.create_task(_hashes_loop()),
            asyncio.create_task(_headers_loop()),
            asyncio.create_task(_events_loop()),
            asyncio.create_task(_log_loop()),
        )

        while True:
            if sum(queues[q].qsize() for q in queues) == 0 and all(t.done() for t in tasks[:-1]):
                break

            for t in tasks:
                if t.done() or t.cancelled():
                    await t

            with suppress(asyncio.TimeoutError):
                while True:
                    header, events = await asyncio.wait_for(queues['events'].get(), timeout=1)
                    yield tuple(SubstrateEventData.from_node(event, header) for event in events)

        tasks[-1].cancel()
