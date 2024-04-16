import logging
from collections import deque
from collections.abc import Iterable

from dipdup.config.tezos_token_transfers import TezosTzktTokenTransfersHandlerConfig
from dipdup.models.tezos_tzkt import TezosTzktTokenTransferData

_logger = logging.getLogger('dipdup.matcher')

MatchedTokenTransfersT = tuple[TezosTzktTokenTransfersHandlerConfig, TezosTzktTokenTransferData]


def match_token_transfer(
    handler_config: TezosTzktTokenTransfersHandlerConfig,
    token_transfer: TezosTzktTokenTransferData,
) -> bool:
    """Match single token transfer with pattern"""
    if handler_config.contract:
        if handler_config.contract.address != token_transfer.contract_address:
            return False
    if handler_config.token_id is not None:
        if handler_config.token_id != token_transfer.token_id:
            return False
    if handler_config.from_:
        if handler_config.from_.address != token_transfer.from_address:
            return False
    if handler_config.to:
        if handler_config.to.address != token_transfer.to_address:
            return False
    return True


def match_token_transfers(
    handlers: Iterable[TezosTzktTokenTransfersHandlerConfig], token_transfers: Iterable[TezosTzktTokenTransferData]
) -> deque[MatchedTokenTransfersT]:
    """Try to match token transfers with all index handlers."""

    matched_handlers: deque[MatchedTokenTransfersT] = deque()

    for token_transfer in token_transfers:
        for handler_config in handlers:
            token_transfer_matched = match_token_transfer(handler_config, token_transfer)
            if not token_transfer_matched:
                continue
            _logger.debug('%s: `%s` handler matched!', token_transfer.level, handler_config.callback)
            matched_handlers.append((handler_config, token_transfer))

    return matched_handlers
