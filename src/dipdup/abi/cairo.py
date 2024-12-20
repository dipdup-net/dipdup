from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING
from typing import Any
from typing import TypedDict

import orjson

from dipdup.abi import AbiManager
from dipdup.exceptions import FrameworkException
from dipdup.utils import json_dumps
from dipdup.utils import touch

if TYPE_CHECKING:
    from starknet_py.abi.v2 import Abi  # type: ignore[import-untyped]
    from starknet_py.cairo.data_types import CairoType  # type: ignore[import-untyped]
    from starknet_py.cairo.data_types import EventType
    from starknet_py.serialization import PayloadSerializer  # type: ignore[import-untyped]

    from dipdup.package import DipDupPackage


class CairoEventAbi(TypedDict):
    name: str
    event_identifier: str
    members: dict[str, CairoType]
    serializer: PayloadSerializer


class CairoAbi(TypedDict):
    events: list[CairoEventAbi]


def _convert_type(type_: CairoType) -> dict[str, Any]:
    # TODO: Support all types
    if type_.__class__.__name__ in {'EventType', 'StructType'}:
        if type_.name == 'Uint256':
            return {'type': 'integer'}
        if type_.name == 'core::byte_array::ByteArray':
            return {'type': 'string'}
        return {
            'type': 'object',
            'properties': {key: _convert_type(value) for key, value in type_.types.items()},
            'required': tuple(type_.types.keys()),
            'additionalProperties': False,
        }

    if type_.__class__.__name__ == 'ArrayType':
        return {
            'type': 'array',
            'items': _convert_type(type_.inner_type),
        }

    simple_type = {
        'FeltType': 'integer',
        'UintType': 'integer',
        'BoolType': 'boolean',
    }[type_.__class__.__name__]
    return {'type': simple_type}


def _jsonschema_from_event(event: EventType) -> dict[str, Any]:
    # TODO: Unpack nested types (starknet.py could do that)
    return {'$schema': 'http://json-schema.org/draft/2019-09/schema#', **_convert_type(event)}


def sn_keccak(x: str) -> str:
    from Crypto.Hash import keccak

    # NOTE: Create keccak256 hash in bytes and return hex representation of the first 250 bits.
    keccak_hash = keccak.new(data=x.encode('ascii'), digest_bits=256).digest()
    return f'0x{int.from_bytes(keccak_hash, "big") & (1 << 250) - 1:x}'


@cache
def _loaded_abis(package: DipDupPackage) -> dict[str, Abi]:

    from starknet_py.abi.v2 import AbiParser
    from starknet_py.abi.v2 import AbiParsingError

    result = {}
    for abi_path in package.cairo_abi_paths:
        abi = orjson.loads(abi_path.read_bytes())

        try:
            parsed_abi = AbiParser(abi).parse()
        except AbiParsingError as e:
            raise e

        parsed_abi.events = {k.split('::')[-1]: v for k, v in parsed_abi.events.items()}
        result[abi_path.parent.stem] = parsed_abi
    return result


def convert_abi(package: DipDupPackage) -> dict[str, CairoAbi]:
    from starknet_py.serialization import serializer_for_event

    abi_by_typename: dict[str, CairoAbi] = {}

    for contract_typename, parsed_abi in _loaded_abis(package).items():
        converted_abi: CairoAbi = {
            'events': [],
        }

        for name, event_type in parsed_abi.events.items():
            if name in converted_abi['events']:
                raise NotImplementedError('Multiple events with the same name are not supported')
            converted_abi['events'].append(
                CairoEventAbi(
                    name=name,
                    event_identifier=sn_keccak(name),
                    members=event_type.types,
                    serializer=serializer_for_event(event_type),
                )
            )
        abi_by_typename[contract_typename] = converted_abi

    return abi_by_typename


def abi_to_jsonschemas(
    package: DipDupPackage,
    events: set[str],
) -> None:
    for contract_typename, parsed_abi in _loaded_abis(package).items():
        for event_name in events:
            if event_name not in parsed_abi.events:
                continue

            schema = _jsonschema_from_event(parsed_abi.events[event_name])
            schema_path = package.schemas / 'starknet' / contract_typename / 'starknet_events' / f'{event_name}.json'
            touch(schema_path)
            schema_path.write_bytes(json_dumps(schema))


class CairoAbiManager(AbiManager):
    def __init__(self, package: DipDupPackage) -> None:
        super().__init__(package)
        self._abis: dict[str, CairoAbi] = {}
        self.get_event_abi = cache(self.get_event_abi)  # type: ignore[method-assign]

    def load(self) -> None:
        self._abis = convert_abi(self._package)

    def get_event_abi(
        self,
        typename: str,
        name: str,
    ) -> CairoEventAbi:
        typename_abi = self._abis[typename]
        for event_abi in typename_abi['events']:
            if name != event_abi['name']:
                continue
            return event_abi

        raise FrameworkException(f'Event `{name}` not found in `{typename}`')
