from collections.abc import AsyncIterator

from dipdup.config.substrate_subsquid import SubstrateSubsquidDatasourceConfig
from dipdup.datasources._subsquid import AbstractSubsquidDatasource
from dipdup.models._subsquid import AbstractSubsquidQuery
from dipdup.models.substrate import _SubstrateSubsquidEventResponse

Query = AbstractSubsquidQuery


class SubstrateSubsquidDatasource(AbstractSubsquidDatasource[SubstrateSubsquidDatasourceConfig, Query]):
    async def iter_events(
        self,
        first_level: int,
        last_level: int,
        names: tuple[str, ...],
    ) -> AsyncIterator[tuple[_SubstrateSubsquidEventResponse, ...]]:
        current_level = first_level

        while current_level <= last_level:
            query: Query = {  # type: ignore[typeddict-unknown-key]
                'fields': {
                    'event': {
                        'name': True,
                        'args': True,
                    },
                    'block': {
                        'hash': True,
                        'parentHash': True,
                        'stateRoot': True,
                        'extrinsicsRoot': True,
                        'digest': True,
                        'specName': True,
                        'specVersion': True,
                        'implName': True,
                        'implVersion': True,
                        'timestamp': True,
                        'validator': True,
                    },
                },
                'events': [
                    {
                        'name': list(names),
                    },
                ],
                'fromBlock': current_level,
                'toBlock': last_level,
                'type': 'substrate',
            }
            response = await self.query_worker(query, current_level)

            for level_item in response:
                for event_item in level_item['events']:
                    event_item['header'] = level_item['header']
                yield tuple(level_item['events'])
                current_level = level_item['header']['number'] + 1
