import logging
from collections import deque
from collections.abc import Iterable
from typing import Any

import eth_abi.decoding
from eth_abi.abi import decode as decode_abi

from dipdup.config.evm_transactions import EvmTransactionsHandlerConfig
from dipdup.exceptions import FrameworkException
from dipdup.indexes.evm import get_sighash
from dipdup.models.evm import EvmTransaction
from dipdup.models.evm import EvmTransactionData
from dipdup.package import DipDupPackage
from dipdup.utils import parse_object
from dipdup.utils import pascal_to_snake
from dipdup.utils import snake_to_pascal

_logger = logging.getLogger(__name__)

MatchedTransactionsT = tuple[
    EvmTransactionsHandlerConfig,
    EvmTransaction[Any] | EvmTransactionData,
]


# NOTE: Completely disable padding validation. If data is in Subsquid, node was ok with it.
eth_abi.decoding.ByteStringDecoder.validate_padding_bytes = lambda *a, **kw: None  # type: ignore[method-assign]
eth_abi.decoding.FixedByteSizeDecoder.validate_padding_bytes = lambda *a, **kw: None  # type: ignore[method-assign]
eth_abi.decoding.SignedFixedDecoder.validate_padding_bytes = lambda *a, **kw: None  # type: ignore[method-assign]
eth_abi.decoding.SignedIntegerDecoder.validate_padding_bytes = lambda *a, **kw: None  # type: ignore[method-assign]
eth_abi.decoding.SingleDecoder.validate_padding_bytes = lambda *a, **kw: None  # type: ignore[method-assign]


def prepare_transaction_handler_args(
    package: DipDupPackage,
    handler_config: EvmTransactionsHandlerConfig,
    matched_transaction: EvmTransactionData,
) -> EvmTransaction[Any]:
    from eth_utils.hexadecimal import decode_hex

    method, contract = handler_config.method, handler_config.to
    if not method or not contract:
        raise FrameworkException('`method` and `to` are required for typed transaction handler')
    typename = contract.module_name

    inputs = package._evm_abis.get_method_abi(
        typename=typename,
        name=handler_config.method,
        signature=handler_config.signature,
    )['inputs']
    from eth_utils.abi import collapse_if_tuple

    data = decode_abi(
        types=tuple(collapse_if_tuple(input) for input in inputs),
        data=decode_hex(matched_transaction.input[10:]),
        strict=False,
    )

    type_ = package.get_type(
        typename=typename,
        module=f'evm_transactions.{pascal_to_snake(method)}',
        name=snake_to_pascal(method) + 'Input',
    )
    typed_input = parse_object(
        type_=type_,
        data=data,
        plain=True,
    )
    return EvmTransaction(
        data=matched_transaction,
        input=typed_input,
    )


def match_transactions(
    package: DipDupPackage,
    handlers: Iterable[EvmTransactionsHandlerConfig],
    transactions: Iterable[EvmTransactionData],
) -> deque[MatchedTransactionsT]:
    """Try to match contract transactions with all index handlers."""
    matched_handlers: deque[MatchedTransactionsT] = deque()

    for transaction in transactions:
        for handler_config in handlers:
            # NOTE: Don't match by `abi` contract field, it's only for codegen
            if (from_ := handler_config.from_) and from_.address not in (transaction.from_, None):
                continue
            if (to := handler_config.to) and to.address not in (transaction.to, None):
                continue
            if handler_config.method or handler_config.signature:
                sighash = get_sighash(
                    package=package,
                    method=handler_config.method,
                    signature=handler_config.signature,
                    to=to,
                )
                if sighash != transaction.sighash:
                    continue

            matched_handlers.append(
                (
                    handler_config,
                    (
                        prepare_transaction_handler_args(package, handler_config, transaction)
                        if handler_config.typed_contract
                        else transaction
                    ),
                )
            )
            break

    _logger.debug('%d handlers matched', len(matched_handlers))
    return matched_handlers
