import logging
from collections import deque
from collections.abc import Iterable
from typing import Any

from starknet_py.serialization._context import DeserializationContext
from starknet_py.serialization.data_serializers._common import deserialize_to_dict

from dipdup.config.starknet_events import StarknetEventsHandlerConfig
from dipdup.models.starknet import StarknetEvent
from dipdup.models.starknet import StarknetEventData
from dipdup.package import DipDupPackage
from dipdup.utils import parse_object
from dipdup.utils import pascal_to_snake
from dipdup.utils import snake_to_pascal

_logger = logging.getLogger(__name__)

MatchedEventsT = tuple[StarknetEventsHandlerConfig, StarknetEvent[Any]]


def match_events(
    package: DipDupPackage,
    handlers: Iterable[StarknetEventsHandlerConfig],
    events: Iterable[StarknetEventData],
    event_identifiers: dict[str, dict[str, str]],
) -> deque[MatchedEventsT]:
    """Try to match event events with all index handlers."""
    matched_handlers: deque[MatchedEventsT] = deque()

    # TODO: Prepare matching parameters before the function call
    matching_data = tuple(
        (
            handler_config,
            event_identifiers[handler_config.contract.module_name][handler_config.name],
            handler_config.contract.address,
        )
        for handler_config in handlers
    )

    for event in events:
        if not event.keys:
            continue

        for handler_config, identifier, address in matching_data:
            if address and address != event.from_address:
                continue
            if identifier != event.keys[0]:
                continue

            arg = prepare_event_handler_args(package, handler_config, event)
            matched_handlers.append((handler_config, arg))
            break

    _logger.debug('%d handlers matched', len(matched_handlers))
    return matched_handlers


def prepare_event_handler_args(
    package: DipDupPackage,
    handler_config: StarknetEventsHandlerConfig,
    matched_event: StarknetEventData,
) -> StarknetEvent[Any]:
    typename = handler_config.contract.module_name

    type_ = package.get_type(
        typename=typename,
        module=f'starknet_events.{pascal_to_snake(handler_config.name)}',
        name=snake_to_pascal(handler_config.name) + 'Payload',
    )

    serializer = package._cairo_abis.get_event_abi(
        typename=typename,
        name=handler_config.name,
    )['serializer']
    data = [int(x, 16) for x in matched_event.keys[1:] + matched_event.data]

    # holding context for error building
    with DeserializationContext.create(data) as context:
        data_dict = deserialize_to_dict(serializer.serializers, context)

    typed_payload = parse_object(type_=type_, data=data_dict)
    return StarknetEvent(
        data=matched_event,
        payload=typed_payload,
    )
