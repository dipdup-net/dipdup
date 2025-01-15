from dataclasses import dataclass
from functools import cached_property
from typing import Any
from typing import Generic
from typing import Self
from typing import TypedDict
from typing import TypeVar
from typing import cast

from dipdup.fetcher import HasLevel
from dipdup.runtimes import SubstrateRuntime
from dipdup.runtimes import get_event_arg_names


class _BlockHeader(TypedDict):
    hash: str
    number: int
    parentHash: str
    stateRoot: str
    extrinsicsRoot: str
    digest: dict[str, dict[str, list[str]]]


class _BlockHeaderExtra(TypedDict):
    hash: str
    number: int
    parentHash: str
    stateRoot: str
    extrinsicsRoot: str
    digest: dict[str, dict[str, list[str]]]

    specName: str
    specVersion: int
    implName: str
    implVersion: int
    timestamp: int
    validator: str


class _SubstrateSubsquidEventResponse(TypedDict):
    name: str
    index: int
    extrinsicIndex: int
    callAddress: list[str]
    args: list[Any]
    header: _BlockHeaderExtra


class _SubstrateNodeEventResponse(TypedDict):
    name: str
    index: int
    extrinsic_index: int
    decoded_args: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class SubstrateEventData(HasLevel):
    # TODO: there are more fields in event data: phase, topics
    name: str
    index: int
    extrinsic_index: int
    call_address: list[str] | None
    args: list[Any] | None = None
    decoded_args: dict[str, Any] | None = None
    header: _BlockHeader
    header_extra: _BlockHeaderExtra | None

    @property
    def level(self) -> int:  # type: ignore[override]
        return self.header['number']

    @classmethod
    def from_node(cls, event_dict: _SubstrateNodeEventResponse, header: _BlockHeader) -> Self:
        return cls(
            **event_dict,
            call_address=None,
            args=None,
            header=header,
            header_extra=None,
        )

    @classmethod
    def from_subsquid(cls, event_dict: _SubstrateSubsquidEventResponse) -> Self:
        return cls(
            name=event_dict['name'],
            index=event_dict['index'],
            extrinsic_index=event_dict['extrinsicIndex'],
            call_address=event_dict['callAddress'],
            args=event_dict['args'],
            decoded_args=None,
            header=event_dict['header'],
            header_extra=event_dict['header'],
        )


class SubstrateHeadBlockData(TypedDict):
    parentHash: str
    number: str
    stateRoot: str
    extrinsicsRoot: str
    digest: dict[str, Any]


PayloadT = TypeVar('PayloadT')


@dataclass(frozen=True)
class SubstrateEvent(Generic[PayloadT]):
    data: SubstrateEventData
    runtime: SubstrateRuntime

    # TODO: Use lazy decoding in other models with typed payload
    @cached_property
    def payload(self) -> PayloadT:
        # NOTE: We receive decoded args from node datasource and encoded from subsquid datasource
        if self.data.decoded_args is not None:
            spec_version = self.runtime.get_spec_version(self.runtime.runtime_config.active_spec_version_id)
            abi = spec_version.get_event_abi(self.data.name)
            arg_names = get_event_arg_names(abi)
            payload = dict(zip(arg_names, self.data.decoded_args, strict=False))
        elif self.data.args is not None and self.data.header_extra is not None:
            payload = self.runtime.decode_event_args(
                name=self.data.name,
                args=self.data.args,
                spec_version=str(self.data.header_extra['specVersion']),
            )
        else:
            raise NotImplementedError
        return cast(PayloadT, payload)

    @property
    def level(self) -> int:
        return self.data.level

    @property
    def name(self) -> str:
        return self.data.name
