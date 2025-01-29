import logging
from copy import copy
from functools import cache
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import orjson

from dipdup.config.substrate import SubstrateRuntimeConfig
from dipdup.exceptions import FrameworkException
from dipdup.package import DipDupPackage
from dipdup.utils import pascal_to_snake
from dipdup.utils import sorted_glob

if TYPE_CHECKING:
    from aiosubstrate import SubstrateInterface
    from scalecodec.base import RuntimeConfigurationObject  # type: ignore[import-untyped]

_logger = logging.getLogger(__name__)


@cache
def extract_args_name(docs: tuple[str, ...]) -> tuple[str, ...]:
    docs_str = ''.join(docs).replace('\\n', '').replace('\n', '')

    # find the last bracket pair, [] or ()
    open_bracket = max(docs_str.rfind('['), docs_str.rfind('('))
    close_bracket = max(docs_str.rfind(']'), docs_str.rfind(')'))
    slice = docs_str[open_bracket + 1 : close_bracket]

    return tuple(arg.strip('\\ ') for arg in slice.split(','))


def get_type_key(type_: str) -> str:
    return type_.split(':')[-1].lower()


def extract_tuple_inner_types(type_: str, registry: dict[str, Any]) -> list[str]:
    inner = type_[6:]
    inner_types = []

    if '<' in inner:
        raise NotImplementedError('Cannot parse nested structures in tuples')

    # NOTE: Read inner types until there's a match in the type registry
    buffer = ''
    for i in range(len(inner)):
        buffer += inner[i]
        type_key = get_type_key(buffer)

        if type_key not in registry['types']:
            continue
        if i < len(inner) - 1 and inner[i + 1] == ':':
            continue

        # FIXME: ???
        # inner_types.append(buffer)
        inner_types.append(type_key)
        buffer = ''

    if buffer or not inner_types:
        raise NotImplementedError('Cannot parse tuple with mixed types')

    return inner_types


@cache
def get_type_registry(name_or_path: str | Path) -> 'RuntimeConfigurationObject':
    from scalecodec.type_registry import load_type_registry_preset  # type: ignore[import-untyped]

    if isinstance(name_or_path, str):
        # NOTE: User path has higher priority
        for path in (
            Path(f'type_registries/{name_or_path}.json'),
            Path(name_or_path),
        ):
            if not path.is_file():
                continue
            name_or_path = path

    if isinstance(name_or_path, Path):
        return orjson.loads(name_or_path.read_bytes())
    return load_type_registry_preset(name_or_path)


class SubstrateSpecVersion:
    def __init__(self, name: str, metadata: list[dict[str, Any]]) -> None:
        self._name = name
        self._metadata = metadata
        self._events: dict[str, dict[str, Any]] = {}

    def get_event_abi(self, qualname: str) -> dict[str, Any]:
        if qualname not in self._events:
            pallet, name = qualname.split('.')
            found = False
            for item in self._metadata:
                if found:
                    break
                if item['name'] != pallet:
                    continue
                for event in item.get('events', ()):
                    if event['name'] != name:
                        continue
                    self._events[qualname] = event
                    found = True

            if not found:
                raise FrameworkException(f'Event `{qualname}` not found in `{self._name}` spec')

        return self._events[qualname]


def get_event_arg_names(event_abi: dict[str, Any]) -> tuple[str, ...]:
    arg_names = event_abi.get('args_name', [])
    arg_names = [a for a in arg_names if a]

    # NOTE: Old metadata
    if not arg_names:
        arg_names = extract_args_name(tuple(event_abi['docs']))

    return tuple(arg_names)


class SubstrateRuntime:
    def __init__(
        self,
        config: SubstrateRuntimeConfig,
        package: DipDupPackage,
        interface: 'SubstrateInterface | None',
    ) -> None:
        self._config = config
        self._package = package
        self._interface = interface
        # TODO: Unload not used
        self._spec_versions: dict[str, SubstrateSpecVersion] = {}

    @property
    def abi_paths(self) -> tuple[Path, Path]:
        return (
            self._package.abi.joinpath(self._config.name),
            self._package.abi_local.joinpath(self._config.name),
        )

    @cached_property
    def runtime_config(self) -> 'RuntimeConfigurationObject':
        if self._interface:
            runtime_config = self._interface.runtime_config

            # FIXME: Substrate interface doesn't update registry when needed
            runtime_config.update_type_registry(get_type_registry('legacy'))
        else:
            from scalecodec.base import RuntimeConfigurationObject

            # FIXME: Generic configuration for cases when node datasources are not available
            runtime_config = RuntimeConfigurationObject()
            runtime_config.update_type_registry(get_type_registry('legacy'))
            runtime_config.update_type_registry(get_type_registry('core'))
            runtime_config.update_type_registry(get_type_registry(self._config.type_registry or self._config.name))

        return runtime_config

    def get_spec_version(self, name: str) -> SubstrateSpecVersion:
        if name in self._spec_versions:
            return self._spec_versions[name]

        _logger.info('loading spec version `%s`', name)

        metadata_paths = (
            self.abi_paths[0].joinpath(f'v{name}.json'),
            self.abi_paths[1].joinpath(f'v{name}.json'),
        )

        if metadata_paths[0].is_file():
            metadata_path = metadata_paths[0]
        elif metadata_paths[1].is_file():
            metadata_path = metadata_paths[1]
        else:
            # NOTE: Using the last known version from the package; ABIs we use are expected to be the same
            available = sorted_glob(self.abi_paths[0], 'v*.json')
            metadata_path = next(i for i in available[::-1] if int(i.stem[1:]) <= int(name))
            _logger.debug('using last known version `%s`', metadata_path.name)

        metadata = orjson.loads(metadata_path.read_bytes())
        spec_version = SubstrateSpecVersion(
            name=f'v{name}',
            metadata=metadata,
        )
        self._spec_versions[name] = spec_version
        return spec_version

    def decode_event_args(
        self,
        name: str,
        args: list[Any] | dict[str, Any],
        spec_version: str,
    ) -> dict[str, Any]:
        from scalecodec.base import ScaleBytes

        spec_obj = self.get_spec_version(spec_version)
        event_abi = spec_obj.get_event_abi(name)

        # FIXME: Do we need original type names?
        # arg_types = event_abi.get('args_type_name') or event_abi['args']
        arg_types = event_abi['args']
        arg_names = get_event_arg_names(event_abi)

        if isinstance(args, list):
            # FIXME: Optionals are processed incorrectly now
            args, unprocessed_args = [], [*args]
            for arg_type in arg_types:
                if arg_type.lower().startswith('option<'):
                    args.append(None)
                else:
                    args.append(unprocessed_args.pop(0))

            args = dict(zip(arg_names, args, strict=True))

        payload = {}

        def parse(value: Any, type_: str) -> Any:
            if isinstance(value, int):
                return value

            if isinstance(value, str) and value[:2] != '0x':
                return int(value)

            # FIXME: Tuple type string have neither brackets no delimeters... Could be a Subscan thing, need to check.
            if isinstance(value, list) and type_.startswith('Tuple:'):
                inner_types = extract_tuple_inner_types(
                    type_=type_,
                    registry=self.runtime_config.type_registry,
                )
                return [parse(v, t) for v, t in zip(value, inner_types, strict=True)]

            # NOTE: Scale decoder expects vec length at the beginning; Subsquid strips it
            if type_.startswith('Vec<'):
                if isinstance(value, str):
                    value_len = len(value[2:]) * 2
                    value = f'0x{value_len:02x}{value[2:]}'
                elif isinstance(value, list):
                    inner = type_[4:-1]
                    return [parse(v, inner) for v in value]
                else:
                    raise NotImplementedError('Unsupported Vec type')

            if not isinstance(value, str):
                return value

            scale_obj = self.runtime_config.create_scale_object(
                type_string=type_,
                data=ScaleBytes(value),
            )
            return scale_obj.process()

        for (key, value), type_ in zip(args.items(), arg_types, strict=True):
            payload[key] = parse(value, type_)

        # NOTE: Subsquid camelcases arg keys for some reason
        for key in copy(payload):
            if key not in arg_names:
                new_key = pascal_to_snake(key)
                payload[new_key] = payload.pop(key)

        # NOTE: Also, we need to unpack TypeScript structures to the original form
        payload = extract_subsquid_payload(payload)

        return payload  # noqa: RET504


def extract_subsquid_payload(data: Any) -> Any:
    if isinstance(data, list | tuple):
        return tuple(extract_subsquid_payload(item) for item in data)

    if isinstance(data, dict):

        if '__kind' in data:
            kind = data['__kind']
            if 'value' in data:
                value = data['value']
                if isinstance(value, list):
                    # Handle list of values
                    value = tuple(extract_subsquid_payload(item) for item in value)
                elif isinstance(value, str):
                    value = int(value)
                return {kind: value}
            # NOTE: Special case
            if 'key' in data:
                return {kind: data['key']}
            # If 'value' is not present, just use the kind
            return kind

        # Process other dictionaries
        return {key: extract_subsquid_payload(value) for key, value in data.items()}

    # Return primitive values as-is
    return data
