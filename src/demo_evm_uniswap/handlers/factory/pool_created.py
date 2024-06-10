from contextlib import suppress
from typing import cast

from demo_evm_uniswap import models as models
from demo_evm_uniswap.models.token import WHITELIST_TOKENS
from demo_evm_uniswap.models.token import ERC20Token
from demo_evm_uniswap.types.factory.evm_events.pool_created import PoolCreated
from dipdup.config.evm import EvmContractConfig
from dipdup.context import HandlerContext
from dipdup.models.evm_subsquid import SubsquidEvent
from tortoise.exceptions import OperationalError

POOL_BLACKLIST = {'0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248'}
POOL_WHITELIST = {
    '0x7bea39867e4169dbe237d55c8242a8f2fcdcc387',
    '0x7858e59e0c01ea06df3af3d20ac7b0003275d4bf',
    '0xbb256c2f1b677e27118b0345fd2b3894d2e6d487',
    '0x4e68ccd3e89f51c3074ca5072bbac773960dfa36',
    '0x788f0399b9f012926e255d9f22ceea845b8f7a32',
    '0xfaace66bd25abff62718abd6db97560e414ec074',
    '0x86e69d1ae728c9cd229f07bbf34e01bf27258354',
    '0x85498e26aa6b5c7c8ac32ee8e872d95fb98640c4',
    '0xbfa7b27ac817d57f938541e0e86dbec32a03ce53',
    '0xb2cd930798efa9b6cb042f073a2ccea5012e7abf',
    '0x8ad599c3a0ff1de082011efddc58f1908eb6e6d8',
    '0xf15054bc50c39ad15fdc67f2aedd7c2c945ca5f6',
    '0x2f62f2b4c5fcd7570a709dec05d68ea19c82a9ec',
    '0x2efec2097beede290b2eed63e2faf5ecbbc528fc',
    '0xc2ceaa15e6120d51daac0c90540922695fcb0fc7',
    '0x1d42064fc4beb5f8aaf85f4617ae8b3b5b8bd801',
}
WETH_ADDRESS = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'


async def create_token(ctx: HandlerContext, address: str, pool_id: str) -> None:
    with suppress(Exception):
        await models.Token.cached_get(address)
        return

    web3 = ctx.get_evm_node_datasource('mainnet_subsquid').web3
    erc20_iface = ERC20Token.from_address(web3, address)
    token = models.Token(
        id=address,
        symbol=await erc20_iface.get_symbol(),
        name=await erc20_iface.get_name(),
        decimals=await erc20_iface.get_decimals(),
        total_supply=await erc20_iface.get_total_supply(),
        derived_eth=1 if address == WETH_ADDRESS else 0,
        whitelist_pools=[pool_id] if address in WHITELIST_TOKENS else [],
    )
    token.cache()
    await token.save()


async def pool_created(
    ctx: HandlerContext,
    event: SubsquidEvent[PoolCreated],
) -> None:
    if event.payload.pool not in POOL_WHITELIST:
        ctx.logger.info('Pool %s is not whitelisted', event.payload.pool)
        return

    factory_address = cast(EvmContractConfig, ctx.config.get_contract('factory')).address
    factory, _ = await models.Factory.get_or_create(id=factory_address)
    factory.pool_count += 1
    await factory.save()

    pool_id = event.payload.pool
    try:
        token0 = event.payload.token0
        await create_token(ctx, token0, pool_id)
    except Exception as e:
        ctx.logger.warning('Failed to get token %s for pool %s: %s', token0, pool_id, e)
        return  # skip this pool
    try:
        token1 = event.payload.token1
        await create_token(ctx, token1, pool_id)
    except Exception as e:
        ctx.logger.warning('Failed to get token %s for pool %s: %s', token1, pool_id, e)
        return  # skip this pool

    pool = models.Pool(
        id=pool_id,
        fee_tier=int(event.payload.fee),
        created_at_timestamp=event.data.timestamp,
        created_at_block_number=int(event.data.level),
        token0_id=token0,
        token1_id=token1,
    )
    # NOTE: Could present after wipe with immune_tables
    with suppress(OperationalError):
        await pool.save()
        pool.cache()
