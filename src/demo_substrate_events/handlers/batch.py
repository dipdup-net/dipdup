from collections.abc import Iterable

from dipdup.context import HandlerContext
from dipdup.index import MatchedHandler


async def batch(
    ctx: HandlerContext,
    handlers: Iterable[MatchedHandler],
) -> None:
    for handler in handlers:
        await ctx.fire_matched_handler(handler)
