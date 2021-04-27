import demo_tzcolors.models as models
from demo_tzcolors.types.tzcolors_auction.parameter.bid import Bid as BidParameter
from demo_tzcolors.types.tzcolors_auction.storage import Storage as TzcolorsAuctionStorage
from dipdup.models import OperationHandlerContext, OperationContext


async def on_bid(
    ctx: OperationHandlerContext,
    bid: OperationContext[BidParameter, TzcolorsAuctionStorage],
) -> None:
    auction = await models.Auction.filter(
        id=bid.parameter.__root__,
    ).get()

    bidder, _ = await models.Address.get_or_create(address=bid.data.sender_address)
    await models.Bid(
        auction=auction,
        bidder=bidder,
        bid_amount=bid.data.amount,
        level=bid.data.level,
        timestamp=bid.data.timestamp,
    ).save()

    auction.bidder = bidder
    auction.bid_amount += bid.data.amount  # type: ignore
    await auction.save()
