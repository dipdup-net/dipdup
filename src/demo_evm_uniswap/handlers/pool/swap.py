from decimal import Decimal

from demo_evm_uniswap import models as models
from demo_evm_uniswap.models.repo import USDC_WETH_03_POOL
from demo_evm_uniswap.models.repo import get_ctx_factory
from demo_evm_uniswap.models.repo import models_repo
from demo_evm_uniswap.models.token import WHITELIST_TOKENS
from demo_evm_uniswap.models.token import convert_token_amount
from demo_evm_uniswap.models.token import token_derive_eth
from demo_evm_uniswap.types.pool.evm_events.swap import Swap
from dipdup.context import HandlerContext
from dipdup.models.evm_subsquid import SubsquidEvent

POOL_BLACKLIST = {'0x9663f2ca0454accad3e094448ea6f77443880454'}
Q192 = Decimal(2**192)


def get_tracked_amount_usd(
    token0: models.Token, token1: models.Token, amount0: Decimal, amount1: Decimal, eth_usd: Decimal
) -> Decimal:
    price0_usd = token0.derived_eth * eth_usd
    price1_usd = token1.derived_eth * eth_usd

    # both are whitelist tokens, return sum of both amounts
    if token0.id in WHITELIST_TOKENS and token1.id in WHITELIST_TOKENS:
        return amount0 * price0_usd + amount1 * price1_usd

    # take double value of the whitelisted token amount
    if token0.id in WHITELIST_TOKENS and token1.id not in WHITELIST_TOKENS:
        return amount0 * price0_usd * Decimal('2')

    # take double value of the whitelisted token amount
    if token0.id not in WHITELIST_TOKENS and token1.id in WHITELIST_TOKENS:
        return amount1 * price1_usd * Decimal('2')

    # neither token is on white list, tracked amount is 0
    return Decimal()


def sqrt_price_x96_to_token_prices(
    sqrt_price_x96: int, token0: models.Token, token1: models.Token
) -> tuple[Decimal, Decimal]:
    num = Decimal(sqrt_price_x96 * sqrt_price_x96)
    price1 = (num / Q192) * (Decimal(10) ** token0.decimals) / (Decimal(10) ** token1.decimals)
    price0 = Decimal(1) / price1
    return price0, price1


async def swap(
    ctx: HandlerContext,
    event: SubsquidEvent[Swap],
) -> None:
    factory = await get_ctx_factory(ctx)
    pool = await models.Pool.cached_get_or_none(event.data.address)
    if not pool:
        return
    token0 = await models.Token.cached_get(pool.token0_id)
    token1 = await models.Token.cached_get(pool.token1_id)

    amount0 = convert_token_amount(event.payload.amount0, token0.decimals)
    amount1 = convert_token_amount(event.payload.amount1, token1.decimals)
    amount0_abs = abs(amount0)
    amount1_abs = abs(amount1)

    amount0_eth = amount0_abs * token0.derived_eth
    amount1_eth = amount1_abs * token1.derived_eth

    eth_usd = await models_repo.get_eth_usd_rate()
    amount0_usd = amount0_eth * eth_usd
    amount1_usd = amount1_eth * eth_usd

    # get amount that should be tracked only - div 2 because can't count both input and output as volume
    amount_total_usd_tracked = get_tracked_amount_usd(token0, token1, amount0_abs, amount1_abs, eth_usd) / Decimal('2')
    amount_total_eth_tracked = amount_total_usd_tracked / eth_usd if eth_usd else Decimal()
    amount_total_usd_untracked = (amount0_usd + amount1_usd) / Decimal('2')

    fees_eth = amount_total_eth_tracked * pool.fee_tier / Decimal('1000000')
    fees_usd = amount_total_usd_tracked * pool.fee_tier / Decimal('1000000')

    # global updates
    factory.tx_count += 1
    factory.total_volume_eth += amount_total_eth_tracked
    factory.total_volume_usd += amount_total_usd_tracked
    factory.untracked_volume_usd += amount_total_usd_untracked
    factory.total_fees_eth += fees_eth
    factory.total_fees_usd += fees_usd

    # reset aggregate tvl before individual pool tvl updates
    current_pool_tvl_eth = pool.total_value_locked_eth
    factory.total_value_locked_eth -= current_pool_tvl_eth

    # pool volume
    pool.volume_token0 += amount0_abs
    pool.volume_token1 += amount1_abs
    pool.volume_usd += amount_total_usd_tracked
    pool.untracked_volume_usd += amount_total_usd_untracked
    pool.fees_usd += fees_usd
    pool.tx_count += 1

    # Update the pool with the new active liquidity, price, and tick.
    pool.liquidity = Decimal(event.payload.liquidity)
    pool.tick = int(event.payload.tick)
    pool.sqrt_price = Decimal(event.payload.sqrtPriceX96)
    pool.total_value_locked_token0 += amount0
    pool.total_value_locked_token1 += amount1

    # update token0 data
    token0.volume += amount0_abs
    token0.total_value_locked += amount0
    token0.volume_usd += amount_total_usd_tracked
    token0.untracked_volume_usd += amount_total_usd_untracked
    token0.fees_usd += fees_usd
    token0.tx_count += 1

    # update token1 data
    token1.volume += amount1_abs
    token1.total_value_locked += amount1
    token1.volume_usd += amount_total_usd_tracked
    token1.untracked_volume_usd += amount_total_usd_untracked
    token1.fees_usd += fees_usd
    token1.tx_count += 1

    # updated pool rates
    price0, price1 = sqrt_price_x96_to_token_prices(int(pool.sqrt_price), token0, token1)
    pool.token0_price = price0
    pool.token1_price = price1
    await pool.save()

    # update USD pricing
    if pool.id == USDC_WETH_03_POOL:
        models_repo.update_eth_usd_rate(price0)

    token0.derived_eth = await token_derive_eth(token0)
    token1.derived_eth = await token_derive_eth(token1)

    # Things affected by new USD rates
    pool.total_value_locked_eth = (
        pool.total_value_locked_token0 * token0.derived_eth + pool.total_value_locked_token1 * token1.derived_eth
    )
    pool.total_value_locked_usd = pool.total_value_locked_eth * eth_usd

    factory.total_value_locked_eth += pool.total_value_locked_eth
    factory.total_value_locked_usd = factory.total_value_locked_eth * eth_usd

    token0.total_value_locked_usd = token0.total_value_locked * token0.derived_eth * eth_usd
    token1.total_value_locked_usd = token1.total_value_locked * token1.derived_eth * eth_usd

    swap_tx = await models.Swap.create(
        id=f'{event.data.transaction_hash}#{event.data.log_index}',
        transaction_hash=event.data.transaction_hash,
        pool=pool,
        token0=token0,
        token1=token1,
        sender=event.payload.sender,
        recipient=event.payload.recipient,
        origin=event.payload.sender,  # FIXME: transaction origin
        timestamp=event.data.timestamp,
        amount0=amount0,
        amount1=amount1,
        amount_usd=amount_total_usd_tracked,
        tick=event.payload.tick,
        sqrt_price_x96=event.payload.sqrtPriceX96,
        log_index=event.data.log_index,
    )
    await swap_tx.save()

    await factory.save()
    await pool.save()
    await token0.save()
    await token1.save()
