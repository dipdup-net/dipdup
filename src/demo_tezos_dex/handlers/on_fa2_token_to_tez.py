from decimal import Decimal

import demo_tezos_dex.models as models
from demo_tezos_dex.types.fa2_token.tezos_parameters.transfer import TransferParameter
from demo_tezos_dex.types.fa2_token.tezos_storage import Fa2TokenStorage
from demo_tezos_dex.types.quipu_fa2.tezos_parameters.token_to_tez_payment import TokenToTezPaymentParameter
from demo_tezos_dex.types.quipu_fa2.tezos_storage import QuipuFa2Storage
from dipdup.context import HandlerContext
from dipdup.models.tezos import TezosOperationData
from dipdup.models.tezos import TezosTransaction


async def on_fa2_token_to_tez(
    ctx: HandlerContext,
    token_to_tez_payment: TezosTransaction[TokenToTezPaymentParameter, QuipuFa2Storage],
    transfer: TezosTransaction[TransferParameter, Fa2TokenStorage],
    transaction_0: TezosOperationData,
) -> None:
    decimals = int(ctx.template_values['decimals'])
    symbol = ctx.template_values['symbol']
    trader = token_to_tez_payment.data.sender_address

    min_tez_quantity = Decimal(token_to_tez_payment.parameter.min_out) / (10**decimals)
    token_quantity = Decimal(token_to_tez_payment.parameter.amount) / (10**decimals)
    assert transaction_0.amount is not None
    tez_quantity = Decimal(transaction_0.amount) / (10**6)
    assert min_tez_quantity <= tez_quantity, token_to_tez_payment.data.hash

    trade = models.Trade(
        symbol=symbol,
        trader=trader,
        side=models.TradeSide.SELL,
        quantity=token_quantity,
        price=token_quantity / tez_quantity,
        slippage=1 - (min_tez_quantity / tez_quantity),
        level=transfer.data.level,
        timestamp=transfer.data.timestamp,
    )
    await trade.save()
