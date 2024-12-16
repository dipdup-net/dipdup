from dipdup.context import HookContext


async def on_reindex(
    ctx: HookContext,
) -> None:
    await ctx.execute_sql_script('on_reindex')
