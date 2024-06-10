from demo_evm_uniswap import models
from demo_evm_uniswap.models.position import save_position_snapshot
from demo_evm_uniswap.models.token import convert_token_amount
from demo_evm_uniswap.types.position_manager.evm_events.increase_liquidity import IncreaseLiquidity
from dipdup.context import HandlerContext
from dipdup.models.evm_subsquid import SubsquidEvent

BLACKLISTED_BLOCKS = {14317993}


async def increase_liquidity(
    ctx: HandlerContext,
    event: SubsquidEvent[IncreaseLiquidity],
) -> None:
    if event.data.level in BLACKLISTED_BLOCKS:
        ctx.logger.warning('Blacklisted level %d', event.data.level)
        return

    position = await models.Position.get_or_none(id=event.payload.tokenId)
    if position is None:
        ctx.logger.warning('Skipping position %s (must be blacklisted pool)', event.payload.tokenId)
        return

    # TODO: remove me
    # await position_validate(ctx, event.data.address, event.payload.tokenId, position)

    token0 = await models.Token.cached_get(position.token0_id)
    token1 = await models.Token.cached_get(position.token1_id)

    amount0 = convert_token_amount(event.payload.amount0, token0.decimals)
    amount1 = convert_token_amount(event.payload.amount1, token1.decimals)

    position.liquidity += event.payload.liquidity
    position.deposited_token0 += amount0
    position.deposited_token1 += amount1

    await position.save()
    await save_position_snapshot(position, event.data.level, event.data.timestamp)
