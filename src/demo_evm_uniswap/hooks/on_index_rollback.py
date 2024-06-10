from dipdup.context import HookContext
from dipdup.index import Index


async def on_index_rollback(
    ctx: HookContext,
    index: Index,  # type: ignore[type-arg]
    from_level: int,
    to_level: int,
) -> None:
    await ctx.execute_sql('on_index_rollback')
    await ctx.rollback(
        index=index.name,
        from_level=from_level,
        to_level=to_level,
    )