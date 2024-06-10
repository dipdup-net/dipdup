from demo_evm_uniswap import models
from demo_evm_uniswap.models.pool import PoolUpdateSign
from demo_evm_uniswap.models.pool import pool_update
from demo_evm_uniswap.types.pool.evm_events.burn import Burn
from dipdup.context import HandlerContext
from dipdup.models.evm_subsquid import SubsquidEvent


async def burn(
    ctx: HandlerContext,
    event: SubsquidEvent[Burn],
) -> None:
    pool = await models.Pool.cached_get_or_none(event.data.address)
    if not pool:
        return
    await pool_update(ctx, pool, event, PoolUpdateSign.BURN)
