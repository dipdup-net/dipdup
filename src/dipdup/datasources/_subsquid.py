import asyncio
from copy import copy
from typing import Any
from typing import Generic
from typing import TypeVar
from typing import cast

from dipdup.config import HttpConfig
from dipdup.datasources import Datasource
from dipdup.datasources import DatasourceConfigT
from dipdup.datasources import IndexDatasource
from dipdup.exceptions import DatasourceError
from dipdup.exceptions import FrameworkException
from dipdup.http import safe_exceptions
from dipdup.models import Head
from dipdup.models._subsquid import AbstractSubsquidQuery
from dipdup.sys import fire_and_forget

QueryT = TypeVar('QueryT', bound=AbstractSubsquidQuery)


class AbstractSubsquidWorker(Datasource[Any], Generic[QueryT]):
    async def run(self) -> None:
        raise FrameworkException('Subsquid worker datasource should not be run')

    async def query(self, query: QueryT) -> list[dict[str, Any]]:
        self._logger.debug('Worker query: %s', query)
        response = await self.request(
            'post',
            url='',
            json=query,
        )
        return cast(list[dict[str, Any]], response)


class AbstractSubsquidDatasource(
    IndexDatasource[DatasourceConfigT],
    Generic[DatasourceConfigT, QueryT],
):
    _default_http_config = HttpConfig(
        polling_interval=1.0,
    )

    def __init__(self, config: Any) -> None:
        self._started = asyncio.Event()
        self._last_level: int = 0
        super().__init__(config, False)

    async def run(self) -> None:
        await self._started.wait()

        # NOTE: If node datasource is missing, just poll API in reasonable intervals.
        while True:
            await asyncio.sleep(self._http_config.polling_interval)
            await self.initialize()

    async def start(self) -> None:
        self._started.set()

    async def subscribe(self) -> None:
        pass

    # FIXME: Heavily copy-pasted from `HTTPGateway._retry_request`
    async def query_worker(self, query: QueryT, current_level: int) -> list[dict[str, Any]]:
        retry_sleep = self._http_config.retry_sleep
        attempt = 1
        last_attempt = self._http_config.retry_count + 1

        while True:
            try:
                # NOTE: Request a fresh worker after each failed attempt
                worker_datasource = await self._get_worker(current_level)
                async with worker_datasource:
                    return await worker_datasource.query(query)
            except safe_exceptions as e:
                self._logger.warning('Worker query attempt %s/%s failed: %s', attempt, last_attempt, e)
                if attempt == last_attempt:
                    raise e

                self._logger.info('Waiting %s seconds before retry', retry_sleep)
                await asyncio.sleep(retry_sleep)

                attempt += 1
                retry_sleep *= self._http_config.retry_multiplier

    async def initialize(self) -> None:
        curr_level = self._last_level
        level = self._last_level = await self.get_head_level()

        if not level:
            raise DatasourceError('Subsquid is not ready yet', self.name)
        if level == curr_level:
            return

        self.set_sync_level(None, level)
        fire_and_forget(
            Head.update_or_create(
                name=self.name,
                defaults={
                    'level': level,
                    'hash': '',
                    'timestamp': 0,
                },
            ),
        )

    async def get_head_level(self) -> int:
        response = await self.request('get', 'height')
        return int(response)

    async def _fetch_worker(self, level: int) -> DatasourceConfigT:
        worker_url = (
            await self._http.request(
                'get',
                f'{self._config.url}/{level}/worker',
            )
        ).decode()

        worker_config: DatasourceConfigT = copy(self._config)
        worker_config.url = worker_url
        if not worker_config.http:
            worker_config.http = self._default_http_config

        # NOTE: Fail immediately; retries are handled one level up
        if worker_config.http:
            worker_config.http.retry_count = 0

        return worker_config

    async def _get_worker(self, level: int) -> AbstractSubsquidWorker[Any]:
        return AbstractSubsquidWorker(await self._fetch_worker(level))
