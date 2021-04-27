import demo_hic_et_nunc.models as models
from demo_hic_et_nunc.types.hen_minter.parameter.cancel_swap import CancelSwap as CancelSwapParameter
from demo_hic_et_nunc.types.hen_minter.storage import Storage as HenMinterStorage
from dipdup.models import OperationHandlerContext, OperationContext


async def on_cancel_swap(
    ctx: OperationHandlerContext,
    cancel_swap: OperationContext[CancelSwapParameter, HenMinterStorage],
) -> None:
    swap = await models.Swap.filter(id=int(cancel_swap.parameter.__root__)).get()
    swap.status = models.SwapStatus.CANCELED
    await swap.save()
