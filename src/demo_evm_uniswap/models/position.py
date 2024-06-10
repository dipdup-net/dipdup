from dipdup.context import HandlerContext
from eth_utils.address import to_checksum_address
from eth_utils.address import to_normalized_address

import demo_evm_uniswap.models as models
from demo_evm_uniswap.models.abi import get_abi


async def position_validate(
    ctx: HandlerContext, contract_address: str, position_id: int, position: models.Position,
) -> None:
    web3 = ctx.get_evm_node_datasource('mainnet_subsquid').web3
    manager = web3.eth.contract(
        address=to_checksum_address(contract_address),
        abi=get_abi('position_manager.abi'),
    )

    try:
        # nonce uint96,
        # operator address,
        # token0 address,
        # token1 address,
        # fee uint24,
        # tickLower int24,
        # tickUpper int24,
        # liquidity uint128,
        # feeGrowthInside0LastX128 uint256,
        # feeGrowthInside1LastX128 uint256,
        # tokensOwed0 uint128,
        # tokensOwed1 uint128
        response = await manager.functions.positions(position_id).call()
        _, owner, token0, token1, _, tick_lower, tick_upper, _, _, _, _, _ = response
    except Exception as e:
        ctx.logger.warning('Failed to eth_call %s with param %d: %s', contract_address, position_id, str(e))
        return

    token_0_id = to_normalized_address(token0)
    token_1_id = to_normalized_address(token1)
    assert (
        position.token0_id == token_0_id
        and position.token1_id == token_1_id
        and position.tick_lower_id == f'{position.pool_id}#{tick_lower}'
        and position.tick_upper_id == f'{position.pool_id}#{tick_upper}'
    ), (
        f'position #{position_id}:'
        f'\n\ttoken0: expected {token_0_id}, got {position.token0_id}'
        f'\n\ttoken1: expected {token_1_id}, got {position.token1_id}'
        f'\n\ttoken0: expected {tick_lower}, got {position.tick_lower_id}'
        f'\n\ttoken1: expected {tick_upper}, got {position.tick_upper_id}'
    )


async def save_position_snapshot(position: models.Position, level: int, timestamp: int) -> None:
    snapshot, exists = await models.PositionSnapshot.get_or_create(
        id=f'{position.id}#{level}',
        defaults={
            'owner': position.owner,
            'pool_id': position.pool_id,
            'position_id': position.id,
            'block_number': level,
            'timestamp': timestamp,
        },
    )  # TODO: less i/o, update only what's necessary
    snapshot.liquidity = position.liquidity
    snapshot.deposited_token0 = position.deposited_token0
    snapshot.deposited_token1 = position.deposited_token1
    snapshot.withdrawn_token0 = position.withdrawn_token0
    snapshot.withdrawn_token1 = position.withdrawn_token1
    snapshot.collected_fees_token0 = position.collected_fees_token0
    snapshot.collected_fees_token1 = position.collected_fees_token1
    await snapshot.save()
