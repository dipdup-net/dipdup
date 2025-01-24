from collections.abc import Callable
from typing import Any

from aiosubstrate import SubstrateInterface

from dipdup.datasources import JsonRpcDatasource


class SubstrateInterfaceProxy(SubstrateInterface):
    def __init__(self, datasource: JsonRpcDatasource[Any]) -> None:
        super().__init__(datasource.url)  # type: ignore[no-untyped-call]
        self._datasource = datasource

    async def http_request(
        self,
        method: str,
        params: list[Any],
    ) -> Any:
        return await self._datasource._jsonrpc_request(
            method=method,
            params=params,
            raw=True,
            ws=False,
        )

    async def websocket_request(
        self,
        method: str,
        params: Any,
        result_handler: Callable[..., Any] | None = None,
    ) -> Any:
        assert not result_handler
        return await self._datasource._jsonrpc_request(
            method=method,
            params=params,
            raw=True,
            ws=True,
        )
