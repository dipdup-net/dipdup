from dipdup.context import HookContext


async def on_daily_update(
    ctx: HookContext,
) -> None:
    await ctx.execute_sql('on_daily_update')
