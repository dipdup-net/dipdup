from __future__ import annotations

import logging
from collections import defaultdict
from functools import cache
from typing import TYPE_CHECKING
from typing import Any
from typing import TypedDict

import orjson

from dipdup.abi import AbiManager
from dipdup.exceptions import ConfigurationError
from dipdup.exceptions import FrameworkException
from dipdup.utils import json_dumps
from dipdup.utils import touch

if TYPE_CHECKING:
    from pathlib import Path

    from dipdup.package import DipDupPackage

_abi_type_map: dict[str, str] = {
    'int': 'integer',
    'uint': 'integer',
    'address': 'string',
    'fixed': 'number',
    'ufixed': 'number',
    'bytes': 'string',
    'bool': 'boolean',
    'string': 'string',
    'tuple': 'object',
}


_logger = logging.getLogger(__name__)


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
    properties, required = {}, []
    for item in abi['inputs']:
        name = _convert_name(item['name'])
        if item['type'] == 'tuple':
            properties[name] = {
                'type': 'object',
                'properties': {
                    _convert_name(i['name']): {'type': _convert_type(i['type'])} for i in item['components']
                },
            }
        else:
            properties[name] = {'type': _convert_type(item['type'])}
        required.append(name)

    return {
        '$schema': 'http://json-schema.org/draft/2019-09/schema#',
        'type': 'object',
        'properties': properties,
        'required': required,
    }


class EvmEventAbi(TypedDict):
    name: str
    topic0: str
    inputs: tuple[tuple[str, bool], ...]
    topic_count: int


class EvmMethodAbi(TypedDict):
    name: str
    sighash: str
    signature: str
    inputs: tuple[dict[str, str], ...]
    outputs: tuple[dict[str, str], ...]


class EvmAbi(TypedDict):
    events: list[EvmEventAbi]
    methods: list[EvmMethodAbi]


def convert_abi(package: DipDupPackage) -> dict[str, EvmAbi]:
    abi_by_typename: dict[str, EvmAbi] = {}

    for abi_path in package.evm_abi_paths:
        converted_abi = _convert_abi(abi_path)
        abi_by_typename[abi_path.parent.stem] = converted_abi

    return abi_by_typename


def _convert_abi(abi_path: Path) -> EvmAbi:
    abi = orjson.loads(abi_path.read_bytes())
    events: list[EvmEventAbi] = []
    methods: list[EvmMethodAbi] = []

    for abi_item in abi:
        if abi_item['type'] == 'function':
            methods.append(
                EvmMethodAbi(
                    name=abi_item['name'],
                    sighash=sighash_from_abi(abi_item),
                    signature=signature_from_abi(abi_item),
                    inputs=abi_item['inputs'],
                    outputs=abi_item['outputs'],
                )
            )
        elif abi_item['type'] == 'event':
            inputs = []
            for item in abi_item['inputs']:
                if (type_ := item['type']) == 'tuple':
                    type_ = '(' + ','.join(c['type'] for c in item['components']) + ')'
                inputs.append((type_, item['indexed']))

            events.append(
                EvmEventAbi(
                    name=abi_item['name'],
                    topic0=topic0_from_abi(abi_item),
                    inputs=tuple(inputs),
                    topic_count=len([i for i in inputs if i[1]]),
                )
            )

    return EvmAbi(
        events=events,
        methods=methods,
    )


def abi_to_jsonschemas(
    package: DipDupPackage,
    events: set[str],
    methods: set[str],
) -> None:
    # NOTE: path used only for contract name receiving, indicating design problem
    for abi_path in package.evm_abi_paths:
        abi = orjson.loads(abi_path.read_bytes())
        method_count: defaultdict[str, int] = defaultdict(int)

        for abi_item in abi:
            if abi_item['type'] == 'function':
                name = abi_item['name']
                if name not in methods:
                    continue

                if count := method_count[name]:
                    _logger.warning('Method `%s` is not unique, typeclass renamed to `%s`', name, f'{name}_{count}')
                    method_count[name] += 1
                    abi_item[name] = name = f'{name}_{count}'
                else:
                    method_count[name] += 1

                schema = jsonschema_from_abi(abi_item)
                schema_path = package.schemas / 'evm' / abi_path.parent.stem / 'evm_transactions' / f'{name}.json'
            elif abi_item['type'] == 'event':
                name = abi_item['name']
                if name not in events:
                    continue
                schema = jsonschema_from_abi(abi_item)
                schema_path = package.schemas / 'evm' / abi_path.parent.stem / 'evm_events' / f'{name}.json'
            else:
                continue

            touch(schema_path)
            schema_path.write_bytes(json_dumps(schema))


def sighash_from_abi(abi_item: dict[str, Any]) -> str:
    from web3 import Web3

    if abi_item.get('type') != 'function':
        raise FrameworkException(f"`{abi_item['name']}` is not a function; can't get sighash")

    signature = f'{abi_item["name"]}({",".join([i["type"] for i in abi_item["inputs"]])})'
    return '0x' + Web3.keccak(text=signature).hex()[:8]


def topic0_from_abi(event: dict[str, Any]) -> str:
    import eth_utils

    if event.get('type') != 'event':
        raise FrameworkException(f'`{event["name"]}` is not an event')

    types = []
    from eth_utils.abi import collapse_if_tuple

    for input in event['inputs']:
        types.append(collapse_if_tuple(input))

    signature = f'{event["name"]}({",".join(types)})'
    return '0x' + eth_utils.crypto.keccak(text=signature).hex()


def signature_from_abi(
    abi_item: dict[str, Any],
    abi_type: str = 'function',
) -> str:
    if abi_item.get('type') != abi_type:
        raise FrameworkException(f'`{abi_item["name"]}` is not a {abi_type}')
    return f'{abi_item["name"]}({",".join([i["name"] for i in abi_item["inputs"]])})'


class EvmAbiManager(AbiManager):
    def __init__(self, package: DipDupPackage) -> None:
        super().__init__(package)
        self._abis: dict[str, EvmAbi] = {}
        self.get_event_abi = cache(self.get_event_abi)  # type: ignore[method-assign]
        self.get_method_abi = cache(self.get_method_abi)  # type: ignore[method-assign]

    def load(self) -> None:
        self._abis = convert_abi(self._package)

    def get_event_abi(
        self,
        typename: str,
        name: str,
    ) -> EvmEventAbi:
        typename_abi = self._abis[typename]
        for event_abi in typename_abi['events']:
            if name != event_abi['name']:
                continue
            return event_abi

        raise FrameworkException(f'Event `{name}` not found in `{typename}`')

    def get_method_abi(
        self,
        typename: str,
        name: str | None = None,
        signature: str | None = None,
    ) -> EvmMethodAbi:
        typename_abi = self._abis[typename]

        if name:
            name_count = sum(1 for i in typename_abi['methods'] if i['name'] == name)
            if name_count > 1:
                msg = f'Method with name `{name}` is not unique in `{typename}`. Use `signature` filter instead.'
                raise ConfigurationError(msg)

        for method_abi in typename_abi['methods']:
            if name and name != method_abi['name']:
                continue
            if signature and signature != method_abi['signature']:
                continue
            return method_abi

        raise FrameworkException(f'Method `{name}` not found in `{typename}`')
