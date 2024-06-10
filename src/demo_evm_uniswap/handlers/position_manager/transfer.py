import demo_evm_uniswap.models as models
from demo_evm_uniswap.models.position import save_position_snapshot
from demo_evm_uniswap.models.repo import models_repo
from demo_evm_uniswap.types.position_manager.evm_events.transfer import Transfer
from dipdup.context import HandlerContext
from dipdup.models.evm_subsquid import SubsquidEvent
from eth_utils.address import to_normalized_address


async def transfer(
    ctx: HandlerContext,
    event: SubsquidEvent[Transfer],
) -> None:
    if event.payload.from_ == '0x0000000000000000000000000000000000000000':
        idx = f'{event.data.level}.{event.data.transaction_index}.{event.data.log_index}'
        pending_position = models_repo.get_pending_position(idx)
        if pending_position is None:
            ctx.logger.warning('Skipping position %s (must be blacklisted pool)', event.payload.tokenId)
            return

        position = models.Position(id=event.payload.tokenId, **pending_position)
    else:
        pos = await models.Position.get_or_none(id=event.payload.tokenId)
        if pos is None:
            ctx.logger.warning('Skipping position %s (must be blacklisted pool)', event.payload.tokenId)
            return
        position = pos

    position.owner = to_normalized_address(event.payload.to)
    await position.save()
    await save_position_snapshot(position, event.data.level, event.data.timestamp)
