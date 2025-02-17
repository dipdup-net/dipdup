from decimal import Decimal

from demo_substrate_events import models as models
from demo_substrate_events.types.assethub.substrate_events.assets_transferred import AssetsTransferredPayload
from dipdup.context import HandlerContext
from dipdup.models.substrate import SubstrateEvent
from tortoise.exceptions import DoesNotExist


async def sql_update(
    ctx: HandlerContext,
    address: str,
    amount: Decimal,
    level: int,
) -> None:
    await ctx.execute_sql_query(
        'update_balance',
        address,
        str(amount),
        level,
    )


# NOTE: Not used, just for demonstration purposes
async def orm_update(
    ctx: HandlerContext,
    address: str,
    amount: Decimal,
    level: int,
) -> None:
    try:
        holder = await models.Holder.cached_get(pk=address)
    except DoesNotExist:
        holder = models.Holder(address=address)
        holder.cache()
    holder.balance += amount
    holder.turnover += abs(amount)
    holder.tx_count += 1
    holder.last_seen = level
    await holder.save()


async def on_transfer(
    ctx: HandlerContext,
    event: SubstrateEvent[AssetsTransferredPayload],
) -> None:
    amount = Decimal(event.payload['amount'])
    if not amount:
        return

    await sql_update(ctx, event.payload['from'], -amount, event.data.level)
    await sql_update(ctx, event.payload['to'], amount, event.data.level)
