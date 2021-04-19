import asyncio
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from typing import Optional

import aiohttp
from tortoise import Tortoise

from dipdup import __version__

_logger = logging.getLogger(__name__)


def snake_to_camel(value: str) -> str:
    return ''.join(map(lambda x: x[0].upper() + x[1:], value.split('_')))


def camel_to_snake(name):
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()


@asynccontextmanager
async def tortoise_wrapper(url: str, models: Optional[str] = None):
    try:
        modules = {'int_models': ['dipdup.models']}
        if models:
            modules['models'] = [models]
        for _ in range(60):
            try:
                await Tortoise.init(
                    db_url=url,
                    modules=modules,  # type: ignore
                )
            except ConnectionRefusedError:
                await asyncio.sleep(1)
            else:
                break
        yield
    finally:
        await Tortoise.close_connections()


@asynccontextmanager
async def http_request(method: str, **kwargs):
    async with aiohttp.ClientSession() as session:
        headers = {
            **kwargs.pop('headers', {}),
            'User-Agent': f'dupdup/{__version__}',
        }
        async with getattr(session, method)(
            skip_auto_headers={'User-Agent'},
            headers=headers,
            **kwargs,
        ) as response:
            request_string = kwargs['url'] + '?' + '&'.join([f'{key}={value}' for key, value in kwargs.get('params', {}).items()])
            _logger.debug('Calling `%s`', request_string)
            yield response


async def reindex():
    await Tortoise._drop_databases()  # pylint: disable=protected-access
    os.execl(sys.executable, sys.executable, *sys.argv)
