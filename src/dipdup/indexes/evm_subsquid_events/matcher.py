import logging
from collections import deque
from collections.abc import Iterable
from itertools import cycle
from typing import Any

from eth_abi.abi import decode as decode_abi
from eth_utils.hexadecimal import decode_hex

from dipdup.config.evm_logs import EvmLogsHandlerConfig
from dipdup.models.evm import EvmLog
from dipdup.models.evm import EvmLogData
from dipdup.package import DipDupPackage
from dipdup.utils import parse_object
from dipdup.utils import pascal_to_snake
from dipdup.utils import snake_to_pascal

_logger = logging.getLogger(__name__)

MatchedEventsT = tuple[EvmLogsHandlerConfig, EvmLog[Any]]


def decode_indexed_topics(indexed_inputs: tuple[str, ...], topics: tuple[str, ...]) -> tuple[Any, ...]:
    indexed_bytes = b''.join(decode_hex(topic) for topic in topics[1:])
    return decode_abi(indexed_inputs, indexed_bytes)


def decode_event_data(
    data: str,
    topics: tuple[str, ...],
    inputs: tuple[tuple[str, bool], ...],
) -> tuple[Any, ...]:
    """Decode event data from hex string"""
    # NOTE: Indexed and non-indexed inputs can go in arbitrary order. We need
    # NOTE: to decode them separately and then merge back.
    indexed_values = iter(decode_indexed_topics(tuple(n for n, i in inputs if i), topics))

    non_indexed_bytes = decode_hex(data)
    if non_indexed_bytes:
        non_indexed_values = iter(decode_abi(tuple(n for n, i in inputs if not i), non_indexed_bytes))
    else:
        # NOTE: Node truncates trailing zeros in event data
        non_indexed_values = cycle((0,))

    values: deque[Any] = deque()
    for _, indexed in inputs:
        if indexed:
            values.append(next(indexed_values))
        else:
            values.append(next(non_indexed_values))
    return tuple(values)


def prepare_event_handler_args(
    package: DipDupPackage,
    handler_config: EvmLogsHandlerConfig,
    matched_event: EvmLogData | EvmLogData,
) -> EvmLog[Any]:
    typename = handler_config.contract.module_name
    inputs = package.get_converted_abi(typename)['events'][handler_config.name]['inputs']

    type_ = package.get_type(
        typename=typename,
        module=f'evm_logs.{pascal_to_snake(handler_config.name)}',
        name=snake_to_pascal(handler_config.name),
    )

    data = decode_event_data(
        data=matched_event.data,
        topics=tuple(matched_event.topics),
        inputs=inputs,
    )

    typed_payload = parse_object(
        type_=type_,
        data=data,
        plain=True,
    )
    return EvmLog(
        data=matched_event,
        payload=typed_payload,
    )


def match_events(
    package: DipDupPackage,
    handlers: Iterable[EvmLogsHandlerConfig],
    events: Iterable[EvmLogData | EvmLogData],
    topics: dict[str, dict[str, str]],
) -> deque[MatchedEventsT]:
    """Try to match contract events with all index handlers."""
    matched_handlers: deque[MatchedEventsT] = deque()

    for event in events:
        if not event.topics:
            continue

        for handler_config in handlers:
            typename = handler_config.contract.module_name
            name = handler_config.name
            if topics[typename][name] != event.topics[0]:
                continue

            address = handler_config.contract.address
            if address and address != event.address:
                continue

            arg = prepare_event_handler_args(package, handler_config, event)
            matched_handlers.append((handler_config, arg))
            break

    _logger.debug('%d handlers matched', len(matched_handlers))
    return matched_handlers
