from collections import defaultdict
from pathlib import Path
from typing import Any
from typing import cast

import eth_utils
import orjson

from dipdup.codegen import CodeGenerator
from dipdup.config import AbiDatasourceConfig
from dipdup.config.evm_subsquid_events import SubsquidEventsIndexConfig
from dipdup.config.evm_subsquid_operations import SubsquidOperationsIndexConfig
from dipdup.datasources import AbiDatasource
from dipdup.exceptions import ConfigurationError
from dipdup.exceptions import FrameworkException
from dipdup.package import PYTHON_MARKER
from dipdup.package import DipDupPackage
from dipdup.package import EventAbiExtra
from dipdup.utils import touch

_abi_type_map: dict[str, str] = {
    'int': 'integer',
    'uint': 'integer',
    'address': 'string',
    'fixed': 'number',
    'ufixed': 'number',
    'bytes': 'string',
    'bool': 'boolean',
    'string': 'string',
    # TODO: arrays and tuples
    # https://docs.soliditylang.org/en/develop/abi-spec.html#types
    'tuple': 'object',
}


def _convert_type(abi_type: str) -> str:
    if abi_type in _abi_type_map:
        return _abi_type_map[abi_type]
    for k, v in _abi_type_map.items():
        if abi_type.startswith(k):
            return v
    raise FrameworkException(f'`{abi_type}` ABI type is not supported')


def _convert_name(name: str) -> str:
    return name.lstrip('_')


def jsonschema_from_abi(abi: dict[str, Any]) -> dict[str, Any]:
    return {
        '$schema': 'http://json-schema.org/draft/2019-09/schema#',
        'type': 'object',
        'properties': {_convert_name(i['name']): {'type': _convert_type(i['type'])} for i in abi['inputs']},
        'required': [_convert_name(i['name']) for i in abi['inputs']],
        'additionalProperties': False,
    }


def convert_abi(package: DipDupPackage, events: set[str], functions: set[str]) -> None:
    for abi_path in package.abi.glob('**/abi.json'):
        abi = orjson.loads(abi_path.read_bytes())
        event_extras: defaultdict[str, EventAbiExtra] = defaultdict(EventAbiExtra)  # type: ignore[arg-type]

        for abi_item in abi:
            if abi_item['type'] == 'function':
                name = abi_item['name']
                if name not in functions:
                    continue
                schema = jsonschema_from_abi(abi_item)
                schema_path = package.schemas / abi_path.parent.stem / 'evm_functions' / f'{abi_item["name"]}.json'
            elif abi_item['type'] == 'event':
                name = abi_item['name']
                extra = event_extras[name]
                if extra:
                    raise NotImplementedError('wow much overload many signatures')
                extra['name'] = name
                extra['topic0'] = topic_from_abi(abi_item)
                extra['inputs'] = inputs_from_abi(abi_item)
                if name not in events:
                    continue

                schema = jsonschema_from_abi(abi_item)
                schema_path = package.schemas / abi_path.parent.stem / 'evm_events' / f'{abi_item["name"]}.json'
            else:
                continue

            touch(schema_path)
            schema_path.write_bytes(orjson.dumps(schema, option=orjson.OPT_INDENT_2))

        if event_extras:
            event_extras_path = package.abi / abi_path.parent.stem / 'events.json'
            touch(event_extras_path)
            event_extras_path.write_bytes(orjson.dumps(event_extras, option=orjson.OPT_INDENT_2))


def inputs_from_abi(event: dict[str, Any]) -> tuple[str, ...]:
    if event.get('type') != 'event':
        raise FrameworkException(f'`{event["name"]}` is not an event')

    return tuple(i['type'] for i in event['inputs'])


def topic_from_abi(event: dict[str, Any]) -> str:
    if event.get('type') != 'event':
        raise FrameworkException(f'`{event["name"]}` is not an event')

    signature = f'{event["name"]}({",".join([i["type"] for i in event["inputs"]])})'
    return '0x' + eth_utils.crypto.keccak(text=signature).hex()


class SubsquidCodeGenerator(CodeGenerator):
    async def generate_abi(self) -> None:
        for index_config in self._config.indexes.values():
            if isinstance(index_config, SubsquidEventsIndexConfig):
                await self._fetch_abi(index_config)
            elif isinstance(index_config, SubsquidOperationsIndexConfig):
                raise NotImplementedError

    async def generate_schemas(self) -> None:
        events: set[str] = set()
        functions: set[str] = set()

        for index_config in self._config.indexes.values():
            if isinstance(index_config, SubsquidEventsIndexConfig):
                for handler_config in index_config.handlers:
                    events.add(handler_config.name)
            elif isinstance(index_config, SubsquidOperationsIndexConfig):
                raise NotImplementedError

        convert_abi(self._package, events, functions)

    # FIXME: tzkt copypaste
    async def generate_types(self, force: bool = False) -> None:
        """Generate typeclasses from fetched JSONSchemas: contract's storage, parameters, big maps and events."""

        self._logger.info('Creating `types` package')
        touch(self._package.types / PYTHON_MARKER)

        for path in self._package.schemas.glob('**/*.json'):
            await self._generate_type(path, force)

    async def generate_hooks(self) -> None:
        pass

    async def generate_event_hooks(self) -> None:
        pass

    async def generate_handlers(self) -> None:
        pass

    async def _fetch_abi(self, index_config: SubsquidEventsIndexConfig) -> None:
        datasource_configs = index_config.abi or self._config.abi_datasources

        for handler_config in index_config.handlers:
            abi_path = self._package.abi / handler_config.contract.module_name / 'abi.json'
            if abi_path.exists():
                continue

            address = handler_config.contract.address

            for datasource_config in datasource_configs:
                if not isinstance(datasource_config, AbiDatasourceConfig):
                    raise ConfigurationError('`abi` must be a list of ABI datasources')

                datasource = cast(AbiDatasource[Any], self._datasources[datasource_config.name])
                abi_json = await datasource.get_abi(address)
                if abi_json:
                    break
            else:
                raise ConfigurationError(f'ABI for contract `{address}` not found')

            touch(abi_path)
            abi_path.write_bytes(orjson.dumps(abi_json, option=orjson.OPT_INDENT_2))

    def get_typeclass_name(self, schema_path: Path) -> str:
        module_name = schema_path.stem
        # FIXME: Prefixes, postfixes?
        # if schema_path.parent.name == 'evm_events':
        #     class_name = f'{module_name}_event'
        # elif schema_path.parent.name == 'evm_functions':
        #     class_name = f'{module_name}_function'
        # else:
        #     class_name = module_name
        return module_name
