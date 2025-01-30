import asyncio
from typing import TYPE_CHECKING, Any

from dipdup.config import HttpConfig
from dipdup.config.starknet_node import StarknetNodeDatasourceConfig
from dipdup.datasources import IndexDatasource

if TYPE_CHECKING:
    from starknet_py.net.client_models import EventsChunk

    from dipdup.datasources._starknetpy import StarknetpyClient


class StarknetNodeDatasource(IndexDatasource[StarknetNodeDatasourceConfig]):
    NODE_LAST_MILE = 128

    _default_http_config = HttpConfig(
        batch_size=1000,
    )

    def __init__(self, config: StarknetNodeDatasourceConfig, merge_subscriptions: bool = False) -> None:
        super().__init__(config, merge_subscriptions)
        self._starknetpy: StarknetpyClient | None = None

    @property
    def starknetpy(self) -> 'StarknetpyClient':
        from dipdup.datasources._starknetpy import StarknetpyClient

        if self._starknetpy is None:
            self._starknetpy = StarknetpyClient(self)
        return self._starknetpy

    async def initialize(self) -> None:
        level = await self.get_head_level()
        self.set_sync_level(None, level)

    async def run(self) -> None:
        if self.ws_available:
            raise NotImplementedError('Realtime mode is not supported yet; remove `ws_url` from datasource config')

        while True:
            level = await self.get_head_level()
            self.set_sync_level(None, level)
            await asyncio.sleep(self._http_config.polling_interval)

    @property
    def ws_available(self) -> bool:
        return self._config.ws_url is not None

    async def subscribe(self) -> None:
        if self.ws_available:
            raise NotImplementedError('Realtime mode is not supported yet; remove `ws_url` from datasource config')

    async def get_head_level(self) -> int:
        return await self.starknetpy.get_block_number()

    async def get_events(
        self,
        address: str | None,
        keys: list[list[str | int]] | None,
        first_level: int,
        last_level: int,
        continuation_token: str | None = None,
    ) -> 'EventsChunk':
        return await self.starknetpy.get_events(
            address=address,
            keys=keys,
            from_block_number=first_level,
            to_block_number=last_level,
            chunk_size=self._http_config.batch_size,
            continuation_token=continuation_token,
        )
    
    async def get_abi(self, address: str) -> dict[str, Any]:
        class_at_response = await self.starknetpy.get_class_at(address, block_number='latest')
        parsed_abi = None
        if isinstance(class_at_response.abi, str):
            parsed_abi = class_at_response.parsed_abi
        else:
            parsed_abi = class_at_response.abi

        return parsed_abi
