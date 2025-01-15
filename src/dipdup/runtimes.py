import logging
import re
from functools import cache
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import orjson

from dipdup.config.substrate import SubstrateRuntimeConfig
from dipdup.exceptions import FrameworkException
from dipdup.package import DipDupPackage
from dipdup.utils import sorted_glob

if TYPE_CHECKING:
    from aiosubstrate import SubstrateInterface
    from scalecodec.base import RuntimeConfigurationObject  # type: ignore[import-untyped]

_logger = logging.getLogger(__name__)


@cache
def extract_args_name(description: str) -> tuple[str, ...]:
    pattern = r'\((.*?)\)|\[(.*?)\]'
    match = re.search(pattern, description)

    if not match:
        raise ValueError('No valid bracket pairs found in the description')

    args_str = match.group(1) or match.group(2)
    return tuple(arg.strip('\\') for arg in args_str.split(', '))


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
            else:
                raise FrameworkException(f'Event `{qualname}` not found in `{self._name}` spec')

        return self._events[qualname]


def get_event_arg_names(event_abi: dict[str, Any]) -> tuple[str, ...]:
    arg_names = event_abi.get('args_name', [])
    arg_names = [a for a in arg_names if a]

    # NOTE: Old metadata
    if not arg_names:
        arg_names = extract_args_name(event_abi['docs'][0])

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
    def abi_path(self) -> Path:
        return self._package.abi.joinpath(self._config.name)

    @cached_property
    def runtime_config(self) -> 'RuntimeConfigurationObject':
        if self._interface:
            return self._interface.runtime_config

        from scalecodec.base import RuntimeConfigurationObject

        # FIXME: Generic configuration for cases when node datasources are not available
        runtime_config = RuntimeConfigurationObject()
        runtime_config.update_type_registry(get_type_registry('legacy'))
        runtime_config.update_type_registry(get_type_registry('core'))
        runtime_config.update_type_registry(get_type_registry(self._config.type_registry or self._config.name))

        return runtime_config

    def get_spec_version(self, name: str) -> SubstrateSpecVersion:
        if name not in self._spec_versions:
            _logger.info('loading spec version `%s`', name)

            metadata_path = self.abi_path.joinpath(f'v{name}.json')

            if not metadata_path.is_file():
                metadata_path = self._package.abi_local.joinpath(self._config.name, f'v{name}.json')

            if not metadata_path.is_file():
                # FIXME: Using last known version to help with missing abis
                available = sorted_glob(self.abi_path, 'v*.json')
                last_known = next(i for i in available if int(i.stem[1:]) >= int(name[1:]))
                _logger.debug('using last known version `%s`', last_known.name)
                self._spec_versions[name] = self.get_spec_version(last_known.stem[1:])
            else:
                metadata = orjson.loads(metadata_path.read_bytes())
                self._spec_versions[name] = SubstrateSpecVersion(
                    name=f'v{name}',
                    metadata=metadata,
                )

        return self._spec_versions[name]

    def decode_event_args(
        self,
        name: str,
        args: list[Any] | dict[str, Any],
        spec_version: str,
    ) -> dict[str, Any]:
        from scalecodec.base import ScaleBytes
        from scalecodec.exceptions import RemainingScaleBytesNotEmptyException

        spec_obj = self.get_spec_version(spec_version)
        event_abi = spec_obj.get_event_abi(
            qualname=name,
        )
        arg_types = event_abi.get('args_type_name') or event_abi['args']

        if isinstance(args, list):
            arg_names = get_event_arg_names(event_abi)

            # NOTE: Optionals
            args, unprocessed_args = [], [*args]
            for arg_type in arg_types:
                if arg_type.startswith('option<'):
                    args.append(None)
                else:
                    args.append(unprocessed_args.pop(0))

            args = dict(zip(arg_names, args, strict=True))
        else:
            arg_names = event_abi['args_name']

        payload = {}
        for (key, value), type_ in zip(args.items(), arg_types, strict=True):
            if isinstance(value, int):
                payload[key] = value
                continue
            if isinstance(value, dict) and '__kind' in value:
                payload[key] = value['__kind']
                continue

            scale_obj = self.runtime_config.create_scale_object(
                type_string=type_,
                data=ScaleBytes(value),
                metadata=spec_obj._metadata,
            )

            # FIXME: padding
            try:
                scale_obj.decode(check_remaining=False)
            except RemainingScaleBytesNotEmptyException:
                padded_value = value + ('00' * (scale_obj.data.offset - scale_obj.data.length))
                print(padded_value)
                scale_obj = self.runtime_config.create_scale_object(
                    type_string=type_,
                    data=ScaleBytes(padded_value),
                    metadata=spec_obj._metadata,
                )
                scale_obj.decode(check_remaining=False)

            payload[key] = scale_obj.value_serialized

        return payload
