from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any
from typing import Generic
from typing import Literal
from typing import Self
from typing import TypeVar

from pydantic import BaseModel

from dipdup.fetcher import HasLevel
from dipdup.subscriptions import Subscription

if TYPE_CHECKING:
    from starknet_py.net.client_models import EmittedEvent


@dataclass(frozen=True)
class StarknetSubscription(Subscription):
    name: Literal['starknet'] = 'starknet'

    def get_params(self) -> list[Any]:
        return [self.name]


@dataclass(frozen=True)
class StarknetTransactionData(HasLevel):
    level: int
    block_hash: str
    transaction_index: int
    transaction_hash: str
    timestamp: int

    # Address of the contract for contract-related transactions
    contract_address: str | None
    entry_point_selector: str | None
    calldata: tuple[str, ...] | None
    max_fee: str | None
    version: str
    signature: tuple[str, ...] | None
    nonce: str | None
    # transaction type enum
    type: str
    sender_address: str | None
    class_hash: str | None
    compiled_class_hash: str | None
    contract_address_salt: str | None
    constructor_calldata: tuple[str, ...] | None

    @classmethod
    def from_subsquid_json(cls, transaction_json: dict[str, Any], header: dict[str, Any]) -> Self:
        return cls(
            level=header['number'],
            block_hash=header['hash'],
            transaction_index=transaction_json['transactionIndex'],
            transaction_hash=transaction_json['transactionHash'],
            timestamp=header['timestamp'],
            contract_address=transaction_json['contractAddress'],
            entry_point_selector=transaction_json.get('entryPointSelector'),
            calldata=tuple(transaction_json.get('calldata', []) or []),
            max_fee=transaction_json.get('maxFee'),
            version=transaction_json['version'],
            signature=tuple(transaction_json.get('signature', []) or []),
            nonce=transaction_json.get('nonce'),
            type=transaction_json['type'],
            sender_address=transaction_json.get('senderAddress'),
            class_hash=transaction_json.get('classHash'),
            compiled_class_hash=transaction_json.get('compiledClassHash'),
            contract_address_salt=transaction_json.get('contractAddressSalt'),
            constructor_calldata=tuple(transaction_json.get('constructorCalldata', []) or []),
        )


@dataclass(frozen=True)
class StarknetEventData(HasLevel):
    level: int
    block_hash: str
    # FIXME: No block header without a separate request
    transaction_index: int | None
    transaction_hash: str
    timestamp: int | None

    from_address: str
    keys: tuple[str, ...]
    data: tuple[str, ...]

    @classmethod
    def from_subsquid_json(
        cls,
        event_json: dict[str, Any],
        transaction_json: dict[str, Any],
        header: dict[str, Any],
    ) -> Self:
        return cls(
            level=header['number'],
            block_hash=header['hash'],
            transaction_index=transaction_json['transactionIndex'],
            transaction_hash=transaction_json['transactionHash'],
            timestamp=header['timestamp'],
            from_address=event_json['fromAddress'],
            keys=tuple(event_json['keys']),
            data=tuple(event_json['data']),
        )

    @classmethod
    def from_node_json(
        cls,
        event_json: dict[str, Any],
        transaction_index: int | None,
        timestamp: int | None,
    ) -> Self:
        return cls(
            level=event_json['block_number'],
            block_hash=hex(event_json['block_hash']),
            transaction_index=transaction_index,
            transaction_hash=hex(event_json['transaction_hash']),
            timestamp=timestamp,
            from_address=hex(event_json['from_address']),
            keys=tuple(hex(i) for i in event_json['keys']),
            data=tuple(hex(i) for i in event_json['data']),
        )

    @classmethod
    def from_starknetpy(
        cls,
        event: 'EmittedEvent',
        transaction_index: int | None,
        timestamp: int | None,
    ) -> Self:
        return cls(
            level=event.block_number,  # type: ignore[arg-type]
            block_hash=hex(event.block_hash),  # type: ignore[arg-type]
            transaction_index=transaction_index,
            transaction_hash=hex(event.transaction_hash),
            timestamp=timestamp,
            from_address=hex(event.from_address),
            keys=tuple(hex(i) for i in event.keys),
            data=tuple(hex(i) for i in event.data),
        )


PayloadT = TypeVar('PayloadT', bound=BaseModel)


@dataclass(frozen=True)
class StarknetEvent(Generic[PayloadT]):
    data: StarknetEventData
    payload: PayloadT
