from decimal import Decimal

from demo_evm_uniswap import models as models


async def tick_get_or_create(tick_idx: int, pool: models.Pool, level: int, timestamp: int) -> models.Tick:
    tick, _ = await models.Tick.get_or_create(
        id=f'{pool.id}#{tick_idx}',
        defaults={
            'pool': pool,
            'tick_idx': tick_idx,
            'created_at_timestamp': timestamp,
            'created_at_block_number': level,
            'price0': Decimal('1.0001') ** tick_idx,
            'price1': 1 / Decimal('1.0001') ** tick_idx,
        },
    )
    return tick
