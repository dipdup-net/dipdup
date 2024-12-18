from decimal import Decimal

from dipdup.context import HandlerContext
from dipdup.models.starknet import StarknetEvent
from tortoise.exceptions import DoesNotExist

from demo_starknet_events import models as models
from demo_starknet_events.types.stark_usdt.starknet_events.transfer import TransferPayload


async def on_transfer(
    ctx: HandlerContext,
    event: StarknetEvent[TransferPayload],
) -> None:
    amount = Decimal(event.payload.value) / (10**6)
    if not amount:
        return

    address_from = f'0x{event.payload.from_:x}'
    await on_balance_update(
        address=address_from,
        balance_update=-amount,
        level=event.data.level,
    )
    address_to = f'0x{event.payload.to:x}'
    await on_balance_update(
        address=address_to,
        balance_update=amount,
        level=event.data.level,
    )


async def on_balance_update(
    address: str,
    balance_update: Decimal,
    level: int,
) -> None:
    try:
        holder = await models.Holder.cached_get(pk=address)
    except DoesNotExist:
        holder = models.Holder(
            address=address,
            balance=0,
            turnover=0,
            tx_count=0,
            last_seen=None,
        )
        holder.cache()
    holder.balance += balance_update
    holder.turnover += abs(balance_update)
    holder.tx_count += 1
    holder.last_seen = level
    await holder.save()
