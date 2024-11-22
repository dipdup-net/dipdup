import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import orjson as json
import pytest
from aiohttp import web
from aiohttp.pytest_plugin import AiohttpClient
from tortoise import Tortoise

from dipdup.config import DipDupConfig
from dipdup.config import HasuraConfig
from dipdup.config import PostgresDatabaseConfig
from dipdup.database import tortoise_wrapper
from dipdup.exceptions import UnsupportedAPIError
from dipdup.hasura import HasuraGateway
from dipdup.models import ReindexingAction
from dipdup.models import ReindexingReason
from dipdup.test import create_dummy_dipdup
from dipdup.test import run_hasura_container
from dipdup.test import run_postgres_container

if TYPE_CHECKING:
    from aiohttp.test_utils import TestClient


async def test_configure_hasura() -> None:
    if os.uname().sysname != 'Linux' or 'microsoft' in os.uname().release:  # check for WSL, Windows, mac and else
        pytest.skip('Test is not supported for os archetecture', allow_module_level=True)

    config_path = Path(__file__).parent / 'configs' / 'demo_tezos_nft_marketplace.yml'

    config = DipDupConfig.load([config_path])
    config.database = await run_postgres_container()
    config.hasura = await run_hasura_container(config.database.host)
    config.advanced.reindex[ReindexingReason.schema_modified] = ReindexingAction.ignore
    config.initialize()

    async with AsyncExitStack() as stack:
        dipdup = await create_dummy_dipdup(config, stack)
        hasura_gateway = await dipdup._set_up_hasura(stack)
        assert isinstance(hasura_gateway, HasuraGateway)

        await hasura_gateway.configure(force=True)

        config.hasura.camel_case = True
        await hasura_gateway.configure(force=True)


@pytest.mark.parametrize('hasura_version', ['v1.0.0', 'v2.15.0'])
async def test_unsupported_versions(hasura_version: str, aiohttp_client: AiohttpClient) -> None:
    async def healthcheck_response(request: web.Request) -> web.Response:
        return web.Response(
            content_type='application/json',
        )

    async def version_response(request: web.Request) -> web.Response:
        return web.Response(
            body=json.dumps({'version': hasura_version}),
            content_type='application/json',
        )

    fake_api = web.Application()
    fake_api.router.add_get('/healthz', healthcheck_response)
    fake_api.router.add_get('/v1/version', version_response)
    fake_client: TestClient[Any, Any] = await aiohttp_client(fake_api)

    fake_client_url = f'http://{fake_client.server.host}:{fake_client.server.port}'
    hasura_config = HasuraConfig(url=fake_client_url)
    postgres_config = PostgresDatabaseConfig(kind='postgres', host='localhost')

    hasura_gateway = HasuraGateway('demo_tezos_nft_marketplace', hasura_config, postgres_config)

    with pytest.raises(UnsupportedAPIError):
        async with hasura_gateway:
            async with tortoise_wrapper('sqlite://:memory:', 'demo_tezos_nft_marketplace.models'):
                await Tortoise.generate_schemas()
                await hasura_gateway.configure()
