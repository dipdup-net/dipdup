from demo_tezos_etherlink.models import Deposit
from demo_tezos_etherlink.types.rollup.tezos_parameters.default import DefaultParameter as RollupDefaultParameter
from demo_tezos_etherlink.types.rollup.tezos_storage import RollupStorage
from demo_tezos_etherlink.types.ticket_helper.tezos_parameters.default import DefaultParameter
from demo_tezos_etherlink.types.ticket_helper.tezos_storage import TicketHelperStorage
from demo_tezos_etherlink.types.ticketer.tezos_parameters.deposit import DepositParameter
from demo_tezos_etherlink.types.ticketer.tezos_storage import Fa2
from demo_tezos_etherlink.types.ticketer.tezos_storage import TicketerStorage
from demo_tezos_etherlink.types.ticketer.tezos_storage import Token
from demo_tezos_etherlink.types.ticketer.tezos_storage import Token1
from dipdup.context import HandlerContext
from dipdup.models.tezos import TezosTransaction


async def on_deposit(
    ctx: HandlerContext,
    deposit: TezosTransaction[DepositParameter, TicketerStorage],
    default: TezosTransaction[DefaultParameter, TicketHelperStorage],
    rollup_default: TezosTransaction[RollupDefaultParameter, RollupStorage],
) -> None:
    match deposit.storage.token:
        case Token(fa12=str(address)):
            pass
        case Token1(fa2=Fa2(address=str(address))):
            pass
        case _:
            raise ValueError

    await Deposit.create(level=deposit.data.level, token=address, amount=default.parameter.amount)
