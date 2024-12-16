from dataclasses import dataclass
from typing import Any
from typing import Generic
from typing import Self
from typing import TypeVar

from pydantic import BaseModel

from dipdup.fetcher import HasLevel


@dataclass(frozen=True)
class EvmEventData(HasLevel):
    address: str
    block_hash: str
    data: str
    level: int
    log_index: int
    removed: bool
    timestamp: int
    topics: tuple[str, ...]
    transaction_hash: str
    transaction_index: int

    @classmethod
    def from_node_json(cls, event_json: dict[str, Any], timestamp: int) -> 'EvmEventData':
        # NOTE: Skale Nebula
        if 'removed' not in event_json:
            event_json['removed'] = False

        return cls(
            address=event_json['address'],
            block_hash=event_json['blockHash'],
            data=event_json['data'],
            level=int(event_json['blockNumber'], 16),
            log_index=int(event_json['logIndex'], 16),
            topics=event_json['topics'],
            transaction_hash=event_json['transactionHash'],
            transaction_index=int(event_json['transactionIndex'], 16),
            removed=event_json['removed'],
            timestamp=timestamp,
        )

    @classmethod
    def from_subsquid_json(cls, event_json: dict[str, Any], header: dict[str, Any]) -> Self:
        return cls(
            address=event_json['address'],
            block_hash=header['hash'],
            data=event_json['data'],
            level=header['number'],
            log_index=event_json['logIndex'],
            timestamp=header['timestamp'],
            topics=tuple(event_json['topics']),
            removed=False,
            transaction_hash=event_json['transactionHash'],
            transaction_index=event_json['transactionIndex'],
        )


@dataclass(frozen=True)
class EvmTransactionData(HasLevel):
    access_list: tuple[dict[str, Any], ...] | None
    block_hash: str
    chain_id: int | None
    contract_address: str | None
    cumulative_gas_used: int | None
    effective_gas_price: int | None
    from_: str
    gas: int
    gas_price: int
    gas_used: int | None
    hash: str
    input: str
    level: int
    max_fee_per_gas: int | None
    max_priority_fee_per_gas: int | None
    nonce: int
    r: str | None
    s: str | None
    status: int | None
    timestamp: int
    to: str | None
    # FIXME: Missing in some nodes. Which ones?
    transaction_index: int | None
    type: int | None
    # FIXME: Missing in some nodes. Which ones?
    value: int | None
    v: int | None
    y_parity: bool | None

    @property
    def sighash(self) -> str:
        return self.input[:10]

    @classmethod
    def from_node_json(
        cls,
        transaction_json: dict[str, Any],
        timestamp: int,
    ) -> Self:
        return cls(
            access_list=tuple(transaction_json['accessList']) if 'accessList' in transaction_json else None,
            block_hash=transaction_json['blockHash'],
            chain_id=int(transaction_json['chainId'], 16) if 'chainId' in transaction_json else None,
            contract_address=None,
            cumulative_gas_used=None,
            effective_gas_price=None,
            from_=transaction_json['from'],
            gas=int(transaction_json['gas'], 16),
            gas_price=int(transaction_json['gasPrice'], 16),
            gas_used=None,
            hash=transaction_json['hash'],
            input=transaction_json['input'],
            level=int(transaction_json['blockNumber'], 16),
            max_fee_per_gas=int(transaction_json['maxFeePerGas'], 16) if 'maxFeePerGas' in transaction_json else None,
            max_priority_fee_per_gas=(
                int(transaction_json['maxPriorityFeePerGas'], 16)
                if 'maxPriorityFeePerGas' in transaction_json
                else None
            ),
            nonce=int(transaction_json['nonce'], 16),
            r=transaction_json.get('r'),
            s=transaction_json.get('s'),
            status=1,
            timestamp=timestamp,
            to=transaction_json.get('to'),
            transaction_index=(
                int(transaction_json['transactionIndex'], 16) if 'transactionIndex' in transaction_json else None
            ),
            type=int(transaction_json['type'], 16) if 'type' in transaction_json else None,
            value=int(transaction_json['value'], 16) if 'value' in transaction_json else None,
            v=int(transaction_json['v'], 16) if 'v' in transaction_json else None,
            y_parity=None,
        )

    @classmethod
    def from_subsquid_json(
        cls,
        transaction_json: dict[str, Any],
        header: dict[str, Any],
    ) -> Self:
        cumulative_gas_used = (
            int(transaction_json['cumulativeGasUsed'], 16) if transaction_json['cumulativeGasUsed'] else None
        )
        effective_gas_price = (
            int(transaction_json['effectiveGasPrice'], 16) if transaction_json['effectiveGasPrice'] else None
        )
        max_fee_per_gas = int(transaction_json['maxFeePerGas'], 16) if transaction_json['maxFeePerGas'] else None
        max_priority_fee_per_gas = (
            int(transaction_json['maxPriorityFeePerGas'], 16) if transaction_json['maxPriorityFeePerGas'] else None
        )
        v = int(transaction_json['v'], 16) if transaction_json['v'] else None
        y_parity = bool(int(transaction_json['yParity'], 16)) if transaction_json['yParity'] else None
        return cls(
            # FIXME: 500
            # access_list=tuple(transaction_json['accessList']) if transaction_json['accessList'] else None,
            access_list=None,
            block_hash=header['hash'],
            chain_id=transaction_json['chainId'],
            contract_address=transaction_json['contractAddress'],
            cumulative_gas_used=cumulative_gas_used,
            effective_gas_price=effective_gas_price,
            from_=transaction_json['from'],
            gas=int(transaction_json['gas'], 16),
            gas_price=int(transaction_json['gasPrice'], 16),
            gas_used=int(transaction_json['gasUsed'], 16),
            hash=transaction_json['hash'],
            input=transaction_json['input'],
            level=header['number'],
            max_fee_per_gas=max_fee_per_gas,
            max_priority_fee_per_gas=max_priority_fee_per_gas,
            nonce=transaction_json['nonce'],
            r=transaction_json['r'],
            s=transaction_json['s'],
            # sighash=transaction_json['sighash'],
            status=transaction_json['status'],
            timestamp=header['timestamp'],
            to=transaction_json['to'],
            transaction_index=transaction_json['transactionIndex'],
            type=transaction_json['type'],
            value=int(transaction_json['value'], 16),
            v=v,
            y_parity=y_parity,
        )


PayloadT = TypeVar('PayloadT', bound=BaseModel)
InputT = TypeVar('InputT', bound=BaseModel)


@dataclass(frozen=True)
class EvmEvent(Generic[PayloadT]):
    data: EvmEventData
    payload: PayloadT


@dataclass(frozen=True)
class EvmTransaction(Generic[InputT]):
    data: EvmTransactionData
    input: InputT
