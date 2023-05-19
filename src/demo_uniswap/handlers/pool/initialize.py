from decimal import Decimal

from demo_uniswap import models
from demo_uniswap.types.pool.evm_events.initialize import Initialize
from demo_uniswap.utils.token import token_derive_eth
from dipdup.context import HandlerContext
from dipdup.models.evm_subsquid import SubsquidEvent


async def initialize(
    ctx: HandlerContext,
    event: SubsquidEvent[Initialize],
) -> None:
    pool = await models.Pool.cached_get(event.data.address)
    pool.sqrt_price = Decimal(event.payload.sqrtPriceX96)
    pool.tick = event.payload.tick
    await pool.save()

    token0 = await models.Token.cached_get(pool.token0_id)
    token1 = await models.Token.cached_get(pool.token1_id)
    token0.derived_eth = await token_derive_eth(token0)
    token1.derived_eth = await token_derive_eth(token1)
    await token0.save()
    await token1.save()
