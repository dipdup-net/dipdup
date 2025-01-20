import logging
from collections import defaultdict
from pathlib import Path
from typing import Any
from typing import cast

import orjson

from dipdup.codegen import CodeGenerator
from dipdup.config import DipDupConfig
from dipdup.config.substrate import SubstrateIndexConfig
from dipdup.config.substrate_events import SubstrateEventsIndexConfig
from dipdup.config.substrate_subscan import SubstrateSubscanDatasourceConfig
from dipdup.datasources import Datasource
from dipdup.datasources.substrate_node import SubstrateNodeDatasource
from dipdup.datasources.substrate_subscan import SubstrateSubscanDatasource
from dipdup.exceptions import ConfigurationError
from dipdup.package import DipDupPackage
from dipdup.runtimes import SubstrateRuntime
from dipdup.runtimes import extract_args_name
from dipdup.runtimes import extract_tuple_inner_types
from dipdup.runtimes import get_type_key
from dipdup.utils import json_dumps
from dipdup.utils import pascal_to_snake
from dipdup.utils import snake_to_pascal
from dipdup.utils import sorted_glob
from dipdup.utils import write

_logger = logging.getLogger(__name__)


def scale_type_to_jsonschema(
    type_registry: dict[str, Any],
    type_string: str,
) -> dict[str, Any]:
    type_key = get_type_key(type_string)
    if {type_string, type_key} & set(type_registry['types']):
        type_def = type_registry['types'][type_key]
        if isinstance(type_def, str):
            return scale_type_to_jsonschema(type_registry, type_def)
        if isinstance(type_def, dict):
            if 'type' in type_def:
                return scale_type_to_jsonschema(type_registry, type_def['type'])
            if '_enum' in type_def:
                return {
                    'description': type_string,
                    'type': 'string',
                    'enum': (
                        list(type_def['_enum'].keys()) if isinstance(type_def['_enum'], dict) else type_def['_enum']
                    ),
                }
            if '_struct' in type_def:
                return {
                    'description': type_string,
                    'type': 'object',
                    'properties': {
                        k: scale_type_to_jsonschema(type_registry, v) for k, v in type_def['_struct'].items()
                    },
                }

    # Handle primitives, default to str
    schema: dict[str, Any] = {
        'description': type_string,
        'type': 'string',
    }

    if type_string.lower() in ('u8', 'u16', 'u32', 'u64', 'u128', 'i8', 'i16', 'i32', 'i64', 'i128'):
        schema['type'] = 'integer'
    elif type_string == 'bool':
        schema['type'] = 'boolean'
    elif type_string in ['String', 'str']:
        schema['type'] = 'string'
    # FIXME: We need to parse weird values like `Tuple:staging_xcm:v4:location:Locationstaging_xcm:v4:location:Location`; mind the missing delimeters
    elif type_string.startswith('Tuple:'):
        inner_types = extract_tuple_inner_types(type_string, type_registry)
        schema['type'] = 'array'
        schema['items'] = [scale_type_to_jsonschema(type_registry, t) for t in inner_types]

    elif type_string.startswith('Vec<'):
        inner_type = type_string[4:-1]
        schema['type'] = 'array'
        schema['items'] = scale_type_to_jsonschema(type_registry, inner_type)
    elif type_string.startswith('Option<'):
        inner_type = type_string[7:-1]
        schema['oneOf'] = [{'type': 'null'}, scale_type_to_jsonschema(type_registry, inner_type)]

    return schema


def event_metadata_to_jsonschema(
    type_registry: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    description = '\n'.join(metadata['docs']).replace(r'\[', '[').replace(r'\]', ']')
    args_name = tuple(a for a in metadata.get('args_name', ()) if a)
    if not args_name:
        args_name = extract_args_name(tuple(metadata['docs']))

    schema = {
        '$schema': 'http://json-schema.org/draft-07/schema#',
        'title': metadata['name'],
        'description': description,
        'type': 'object',
        'properties': {},
        'required': args_name,
    }
    for arg_name, arg_type in zip(args_name, metadata['args'], strict=True):
        schema['properties'][arg_name] = scale_type_to_jsonschema(type_registry, arg_type)
        schema['properties'][arg_name]['description'] = arg_type

    return schema


class SubstrateCodeGenerator(CodeGenerator):
    kind = 'substrate'

    def __init__(
        self,
        config: DipDupConfig,
        package: DipDupPackage,
        datasources: dict[str, Datasource[Any]],
        include: set[str] | None = None,
    ) -> None:
        super().__init__(config, package, datasources, include)

        self._runtimes: dict[str, SubstrateRuntime] = {}

    async def generate_abis(self) -> None:
        processed = set()

        for index_config in self._config.indexes.values():
            if not isinstance(index_config, SubstrateIndexConfig):
                continue
            name = index_config.runtime.name
            if name in processed:
                continue

            for datasource_config in index_config.datasources:
                if isinstance(datasource_config, SubstrateSubscanDatasourceConfig):
                    datasource = cast(SubstrateSubscanDatasource, self._datasources[datasource_config.name])
                    break
            else:
                raise NotImplementedError('Codegen currently requires `substrate.subscan` datasource')

            runtime_list = await datasource.get_runtime_list()
            _logger.info('found %s runtimes', len(runtime_list))

            for spec in runtime_list[::-1]:
                spec_version = spec['spec_version']

                key = f'v{spec_version}'
                # NOTE: Important versions will be copied to project later
                abi_path = self._package.abi_local.joinpath(f'{name}/{key}.json')
                if abi_path.exists():
                    continue

                _logger.info('v%s metadata not found, fetching', spec_version)
                metadata = await datasource.get_runtime_metadata(spec_version)
                write(abi_path, json_dumps(metadata))

            processed.add(name)

    def get_target_events(self) -> dict[str, list[str]]:
        target_events: dict[str, list[str]] = {}

        for index_config in self._config.indexes.values():
            if isinstance(index_config, SubstrateEventsIndexConfig):
                runtime_name = index_config.runtime.name
                if runtime_name not in target_events:
                    target_events[runtime_name] = []
                for handler_config in index_config.handlers:
                    target_events[runtime_name].append(handler_config.name)

        return target_events

    async def generate_schemas(self) -> None:
        self._cleanup_schemas()

        target_events = self.get_target_events()

        if not target_events:
            return

        latest_dumps: defaultdict[str, bytes] = defaultdict(bytes)

        for runtime_name, events in target_events.items():
            for metadata_path in sorted_glob(self._package.abi_local, f'{runtime_name}/*.json'):
                metadata = orjson.loads(metadata_path.read_bytes())

                type_registry = self._get_runtime(runtime_name).runtime_config.type_registry

                for module in metadata:
                    for event_item in module.get('events', []):
                        qualname = f'{module["name"]}.{event_item["name"]}'
                        if qualname not in events:
                            continue
                        target_events[runtime_name].remove(qualname)

                        # FIXME: ignore when only docs changed?
                        dump = orjson.dumps({**event_item, 'name': ''})
                        if dump == latest_dumps[qualname]:
                            continue
                        latest_dumps[qualname] = dump

                        # TODO: Copy used abis to the project. This logic should be somewhere else.
                        write(self._package.abi.joinpath(runtime_name, metadata_path.name), metadata_path.read_bytes())

                        schema_path = (
                            self._package.schemas
                            / 'substrate'
                            / runtime_name
                            / 'substrate_events'
                            / pascal_to_snake(qualname.replace('.', ''))
                            / f'{metadata_path.stem.replace('.', '_')}.json'
                        )
                        if schema_path.exists():
                            continue

                        jsonschema = event_metadata_to_jsonschema(type_registry, event_item)

                        write(schema_path, json_dumps(jsonschema))

        for runtime_name, events in target_events.items():
            if events:
                msg = f'Runtime `{runtime_name}` misses following events: {', '.join(events)}'
                raise ConfigurationError(msg)

    async def _generate_types(self, force: bool = False) -> None:
        await super()._generate_types(force)

        target_events = self.get_target_events()

        for typeclass_dir in self._package.types.glob('**/substrate_events/*'):

            # NOTE: Find corresponding event
            try:
                events = target_events[typeclass_dir.parts[-3]]
            except KeyError:
                self._logger.info(
                    'No indexes in config use `%s` runtime; skipping `%s`', typeclass_dir.parts[-3], typeclass_dir.name
                )
                continue

            for event_name in events:
                if pascal_to_snake(event_name.replace('.', '')) == typeclass_dir.stem:
                    name = event_name
                    break
            else:
                raise Exception(f'Event not found for {typeclass_dir.stem}')

            # NOTE: Don't extract from typeclass path! XYK.Sell -> xyk_sell -> XykSellPayload; should be XYKSellPayload.
            typeclass_name = f'{snake_to_pascal(name)}Payload'

            versions = [p.stem[1:] for p in sorted_glob(typeclass_dir, '*.py') if p.name.startswith('v')]
            root_lines = [
                *(f'from .v{v} import V{v}' for v in versions),
                '',
                f'type {typeclass_name} = ' + ' | '.join(f'V{v}' for v in versions),
                '',
            ]

            write(typeclass_dir.joinpath('__init__.py'), '\n'.join(root_lines), overwrite=True)

    async def generate_hooks(self) -> None:
        pass

    async def generate_system_hooks(self) -> None:
        pass

    async def generate_handlers(self) -> None:
        pass

    def get_typeclass_name(self, schema_path: Path) -> str:
        module_name = schema_path.stem
        if schema_path.parent.name == 'substrate_events':
            class_name = f'{module_name}_payload'
        else:
            class_name = module_name
        return snake_to_pascal(class_name)

    async def _generate_type(self, schema_path: Path, force: bool) -> None:
        markers = {
            'substrate_events',
        }
        if not set(schema_path.parts).intersection(markers):
            return
        await super()._generate_type(schema_path, force)

    def _get_runtime(self, name: str) -> SubstrateRuntime:
        if name not in self._runtimes:
            self._runtimes[name] = SubstrateRuntime(
                config=self._config.runtimes[name],
                package=self._package,
                interface=next(
                    d for d in self._datasources.values() if isinstance(d, SubstrateNodeDatasource)
                )._interface,
            )
        return self._runtimes[name]
