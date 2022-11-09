import os
from unittest.mock import MagicMock

if os.environ.get('DEBUG'):
    from dipdup.cli import set_up_logging
    from dipdup.config import DipDupConfig
    from dipdup.config import LoggingValues

    set_up_logging()
    DipDupConfig.set_up_logging(MagicMock(logging=LoggingValues.verbose))


from contextlib import AsyncExitStack

from dipdup.config import DipDupConfig
from dipdup.config import SqliteDatabaseConfig
from dipdup.dipdup import DipDup


async def create_test_dipdup(config: DipDupConfig, stack: AsyncExitStack) -> DipDup:
    config.database = SqliteDatabaseConfig(kind='sqlite', path=':memory:')
    config.initialize(skip_imports=True)

    dipdup = DipDup(config)
    await dipdup._create_datasources()
    await dipdup._set_up_database(stack)
    await dipdup._set_up_hooks(set())
    await dipdup._initialize_schema()
    return dipdup
