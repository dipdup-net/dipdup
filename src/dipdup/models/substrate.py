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


class BlockHeaderSubsquid(TypedDict):
    number: int
    hash: str
    parentHash: str
    stateRoot: str
    extrinsicsRoot: str
    digest: str
    specName: str
    specVersion: int
    implName: str
    implVersion: int
    timestamp: int
    validator: str


class SubstrateEventDataSubsquid(TypedDict):
    name: str
    index: int
    extrinsicIndex: int
    callAddress: list[str]
    args: list[Any]
    header: BlockHeaderSubsquid


class BlockHeader(TypedDict):
    hash: str
    number: int
    prev_root: str


class SubstrateEventDataDict(TypedDict):
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
    # we receive decoded args from node datasource and encoded from subsquid datasource
    args: list[Any] | None = None
    decoded_args: dict[str, Any] | None = None
    header: BlockHeader
    header_extra: BlockHeaderSubsquid | None

    @property
    def level(self) -> int:  # type: ignore[override]
        return self.header['number']

    @classmethod
    def from_node(cls, event_dict: SubstrateEventDataDict, header: BlockHeader) -> Self:
        return cls(
            **event_dict,
            call_address=None,
            args=None,
            header=header,
            header_extra=None,
        )

    @classmethod
    def from_subsquid(cls, event_dict: SubstrateEventDataSubsquid) -> Self:
        return cls(
            name=event_dict['name'],
            index=event_dict['index'],
            extrinsic_index=event_dict['extrinsicIndex'],
            call_address=event_dict['callAddress'],
            args=event_dict['args'],
            decoded_args=None,
            header={
                'hash': event_dict['header']['hash'],
                'number': event_dict['header']['number'],
                'prev_root': event_dict['header']['parentHash'],
            },
            header_extra=event_dict['header'],
        )


class HeadBlock(TypedDict):
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

    # TODO: could be used in other models with typed payload
    @cached_property
    def payload(self) -> PayloadT:
        if self.data.decoded_args is not None:
            return cast(PayloadT, self.data.decoded_args)

        # NOTE: both from subsquid
        assert self.data.args is not None and self.data.header_extra is not None
        return cast(
            PayloadT,
            self.runtime.decode_event_args(
                name=self.name,
                args=self.data.args,
                spec_version=str(self.data.header_extra['specVersion']),
            ),
        )

    @property
    def level(self) -> int:
        return self.data.level

    @property
    def name(self) -> str:
        return self.data.name
