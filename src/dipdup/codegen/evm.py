from pathlib import Path
from typing import Any
from typing import cast

from dipdup.codegen import CodeGenerator
from dipdup.config import EvmIndexConfigU
from dipdup.config import HandlerConfig
from dipdup.config.abi_etherscan import AbiEtherscanDatasourceConfig
from dipdup.config.evm import EvmContractConfig
from dipdup.config.evm import EvmIndexConfig
from dipdup.config.evm_events import EvmEventsHandlerConfig
from dipdup.config.evm_events import EvmEventsIndexConfig
from dipdup.config.evm_transactions import EvmTransactionsHandlerConfig
from dipdup.config.evm_transactions import EvmTransactionsIndexConfig
from dipdup.datasources import AbiDatasource
from dipdup.exceptions import AbiNotAvailableError
from dipdup.exceptions import ConfigurationError
from dipdup.exceptions import DatasourceError
from dipdup.utils import json_dumps
from dipdup.utils import snake_to_pascal
from dipdup.utils import touch


class EvmCodeGenerator(CodeGenerator):
    kind = 'evm'

    async def generate_abis(self) -> None:
        for index_config in self._config.indexes.values():
            if isinstance(index_config, EvmIndexConfig):
                await self._fetch_abi(index_config)

    async def generate_schemas(self) -> None:
        from dipdup.abi.evm import abi_to_jsonschemas

        self._cleanup_schemas()

        handler_config: HandlerConfig
        events: set[str] = set()
        methods: set[str] = set()

        for index_config in self._config.indexes.values():
            if isinstance(index_config, EvmEventsIndexConfig):
                for handler_config in index_config.handlers:
                    events.add(handler_config.name)
            elif isinstance(index_config, EvmTransactionsIndexConfig):
                for handler_config in index_config.handlers:
                    if handler_config.typed_contract:
                        # FIXME: Can break when there are multiple signatures for the same method. Forbidden in validation.
                        methods.add(handler_config.cropped_method)

        abi_to_jsonschemas(self._package, events, methods)

    async def generate_hooks(self) -> None:
        pass

    async def generate_system_hooks(self) -> None:
        pass

    async def generate_handlers(self) -> None:
        pass

    async def _fetch_abi(self, index_config: EvmIndexConfigU) -> None:
        datasource_configs = tuple(c for c in index_config.datasources if isinstance(c, AbiEtherscanDatasourceConfig))

        contract: EvmContractConfig | None = None

        for handler_config in index_config.handlers:
            if isinstance(handler_config, EvmEventsHandlerConfig):
                contract = handler_config.contract
            elif isinstance(handler_config, EvmTransactionsHandlerConfig):
                contract = handler_config.typed_contract

            if not contract:
                continue

            abi_path = self._package.abi / contract.module_name / 'abi.json'
            if abi_path.exists():
                continue
            if not datasource_configs:
                raise ConfigurationError('No EVM ABI datasources found')

            address = contract.address or contract.abi
            if not address:
                raise ConfigurationError(f'`address` or `abi` must be specified for contract `{contract.module_name}`')

            for datasource_config in datasource_configs:

                datasource = cast(AbiDatasource[Any], self._datasources[datasource_config.name])
                try:
                    abi_json = await datasource.get_abi(address)
                    break
                except DatasourceError as e:
                    self._logger.warning('Failed to fetch ABI from `%s`: %s', datasource_config.name, e)
            else:
                raise AbiNotAvailableError(
                    address=address,
                    typename=contract.module_name,
                )

            touch(abi_path)
            abi_path.write_bytes(json_dumps(abi_json))

    def get_typeclass_name(self, schema_path: Path) -> str:
        module_name = schema_path.stem
        if schema_path.parent.name == 'evm_events':
            class_name = f'{module_name}_payload'
        elif schema_path.parent.name == 'evm_transactions':
            class_name = f'{module_name}_input'
        else:
            class_name = module_name
        return snake_to_pascal(class_name)

    async def _generate_type(self, schema_path: Path, force: bool) -> None:
        markers = {
            'evm_events',
            'evm_transactions',
        }
        if not set(schema_path.parts).intersection(markers):
            return
        await super()._generate_type(schema_path, force)
