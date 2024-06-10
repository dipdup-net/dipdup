from demo_evm_uniswap import models
from demo_evm_uniswap.models.pool import PoolUpdateSign
from demo_evm_uniswap.models.pool import pool_update
from demo_evm_uniswap.models.repo import models_repo
from demo_evm_uniswap.types.pool.evm_events.mint import Mint
from dipdup.context import HandlerContext
from dipdup.models.evm_subsquid import SubsquidEvent
from eth_utils.address import to_normalized_address

BLACKLISTED_POOLS = {'0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248'}


async def mint(
    ctx: HandlerContext,
    event: SubsquidEvent[Mint],
) -> None:
    pool = await models.Pool.cached_get_or_none(event.data.address)
    if not pool or pool.id in BLACKLISTED_POOLS:
        ctx.logger.debug('Pool.mint: skipping pool %s as it is blacklisted', event.data.address)
        return

    await pool_update(ctx, pool, event, PoolUpdateSign.MINT)

    pending_position = {
        'owner': to_normalized_address(event.payload.owner),
        'pool_id': pool.id,
        'token0_id': pool.token0_id,
        'token1_id': pool.token1_id,
        'tick_lower_id': f'{pool.id}#{event.payload.tickLower}',
        'tick_upper_id': f'{pool.id}#{event.payload.tickUpper}',
    }
    position_idx = f'{event.data.level}.{event.data.transaction_index}.{int(event.data.log_index) + 1}'
    models_repo.save_pending_position(position_idx, pending_position)
