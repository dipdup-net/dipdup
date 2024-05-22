from pathlib import Path
from typing import Any

import orjson
from Crypto.Hash import keccak
from starknet_py.abi.v2 import AbiParser  # type: ignore[import-not-found]
from starknet_py.abi.v2 import AbiParsingError
from starknet_py.cairo.data_types import CairoType  # type: ignore[import-not-found]
from starknet_py.cairo.data_types import EventType
from starknet_py.cairo.data_types import FeltType
from starknet_py.cairo.data_types import UintType

from dipdup.codegen import CodeGenerator
from dipdup.config import HandlerConfig
from dipdup.config.starknet_events import StarknetEventsIndexConfig
from dipdup.package import ConvertedCairoAbi
from dipdup.package import ConvertedEventCairoAbi
from dipdup.package import DipDupPackage
from dipdup.utils import json_dumps
from dipdup.utils import snake_to_pascal
from dipdup.utils import touch

_abi_type_map = {FeltType: 'string', UintType: 'integer'}


def _convert_type(type_: CairoType) -> str:
    return _abi_type_map[type(type_)]


def _jsonschema_from_event(event: EventType) -> dict[str, Any]:
    return {
        '$schema': 'http://json-schema.org/draft/2019-09/schema#',
        'type': 'object',
        'properties': {key: _convert_type(value) for key, value in event.types.items()},
        'required': tuple(event.types.keys()),
        'additionalProperties': False,
    }

def sn_keccak(x: str) -> str:
    return f'0x{int.from_bytes(keccak.new(data=x.encode("ascii"), digest_bits=256).digest(), "big") & (1 << 248) - 1:x}'

def convert_abi(package: DipDupPackage) -> dict[str, ConvertedCairoAbi]:
    abi_by_typename: dict[str, ConvertedCairoAbi] = {}

    for abi_path in package.abi.glob('**/abi.json'):
        abi = orjson.loads(abi_path.read_bytes())
        converted_abi: ConvertedCairoAbi = {
            'events': {},
        }

        for abi_item in abi:
            if abi_item['type'] == 'event':
                name = abi_item['name']
                if name in converted_abi['events']:
                    raise NotImplementedError('Multiple events with the same name are not supported')
                members = tuple((i['type'], i['indexed']) for i in abi_item['inputs'])
                converted_abi['events'][name] = ConvertedEventCairoAbi(
                    name=name,
                    event_identifier=sn_keccak(name),
                    members=members,
                )
        abi_by_typename[abi_path.parent.stem] = converted_abi

    return abi_by_typename


def abi_to_jsonschemas(
    package: DipDupPackage,
    events: set[str],
) -> None:
    # load abi to json and then parse with starknet.py
    # select objects to generate types
    # convert types in to schema
    # write schema
    for abi_path in package.abi.glob('**/abi.json'):
        abi = orjson.loads(abi_path.read_bytes())

        try:
            parsed_abi = AbiParser(abi).parse()
        except AbiParsingError as e:
            # TODO: try pass with  different version of protocol
            raise e

        parsed_abi.events = {k.split('::')[-1]: v for k, v in parsed_abi.events}

        for ev_name in events:
            if ev_name not in parsed_abi.events:
                continue

            schema = _jsonschema_from_event(parsed_abi.events[ev_name])
            schema_path = package.schemas / abi_path.parent.stem / 'starknet_events' / f'{ev_name}.json'
            touch(schema_path)
            schema_path.write_bytes(json_dumps(schema))


class StarknetCodeGenerator(CodeGenerator):
    async def generate_abi(self) -> None:
        # for now abi can only be put manually
        ...

    async def generate_schemas(self) -> None:
        self._cleanup_schemas()

        handler_config: HandlerConfig
        events: set[str] = set()

        for index_config in self._config.indexes.values():
            if isinstance(index_config, StarknetEventsIndexConfig):
                for handler_config in index_config.handlers:
                    events.add(handler_config.name)

        abi_to_jsonschemas(self._package, events)

    async def generate_hooks(self) -> None:
        pass

    async def generate_system_hooks(self) -> None:
        pass

    async def generate_handlers(self) -> None:
        pass

    def get_typeclass_name(self, schema_path: Path) -> str:
        module_name = schema_path.stem
        if schema_path.parent.name == 'starknet_events':
            class_name = f'{module_name}_payload'
        else:
            class_name = module_name
        return snake_to_pascal(class_name)

    async def _generate_type(self, schema_path: Path, force: bool) -> None:
        markers = {
            'starknet_events',
        }
        if not set(schema_path.parts).intersection(markers):
            return
        await super()._generate_type(schema_path, force)
