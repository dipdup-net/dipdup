from enum import Enum
from typing import NotRequired
from typing import TypedDict

from dipdup.models import MessageType


class SubsquidMessageType(MessageType, Enum):
    evm_blocks = 'evm_blocks'
    evm_logs = 'evm_logs'
    evm_traces = 'evm_traces'
    evm_transactions = 'evm_transactions'
    starknet_events = 'starknet_events'
    substrate_events = 'substrate_events'


FieldSelection = dict[str, dict[str, bool]]


class AbstractSubsquidQuery(TypedDict):
    fromBlock: int
    toBlock: NotRequired[int]
    includeAllBlocks: NotRequired[bool]
