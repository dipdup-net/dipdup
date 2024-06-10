from demo_evm_uniswap import models as models
from demo_evm_uniswap.types.pool.evm_events.flash import Flash
from dipdup.context import HandlerContext
from dipdup.models.evm_subsquid import SubsquidEvent


async def flash(
    ctx: HandlerContext,
    event: SubsquidEvent[Flash],
) -> None:
    ...
