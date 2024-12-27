from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from decimal import Decimal
from typing import cast

import pytest

from dipdup.config import DipDupConfig
from dipdup.config.tezos_operations import TezosOperationsHandlerConfig
from dipdup.config.tezos_operations import TezosOperationsHandlerOriginationPatternConfig
from dipdup.config.tezos_operations import TezosOperationsIndexConfig
from dipdup.datasources.tezos_tzkt import TezosTzktDatasource
from dipdup.exceptions import FrameworkException
from dipdup.indexes.tezos_operations.fetcher import get_origination_filters
from dipdup.indexes.tezos_operations.fetcher import get_transaction_filters
from dipdup.indexes.tezos_operations.index import TezosOperationsIndex
from dipdup.models.tezos import TezosOperationType
from dipdup.models.tezos_tzkt import HeadSubscription
from dipdup.models.tezos_tzkt import TransactionSubscription
from dipdup.test import create_dummy_dipdup
from dipdup.test import spawn_index
from tests import TEST_CONFIGS
from tests import tzkt_replay


@pytest.fixture
async def tzkt() -> AsyncIterator[TezosTzktDatasource]:
    async with tzkt_replay() as tzkt:
        yield tzkt


@pytest.fixture
def index_config() -> TezosOperationsIndexConfig:
    config = DipDupConfig.load([TEST_CONFIGS / 'operation_filters.yml'], True)
    config.initialize()
    return cast(TezosOperationsIndexConfig, config.indexes['test'])


async def test_ignored_type_filter(
    tzkt: TezosTzktDatasource,
    index_config: TezosOperationsIndexConfig,
) -> None:
    index_config.types = ()
    addresses, hashes = await get_origination_filters(index_config, (tzkt,))
    assert not addresses
    assert not hashes

    addresses, hashes = await get_transaction_filters(index_config)
    assert not addresses
    assert not hashes


async def test_get_origination_filters(
    tzkt: TezosTzktDatasource,
    index_config: TezosOperationsIndexConfig,
) -> None:
    index_config.handlers = (
        TezosOperationsHandlerConfig(
            callback='address_origination',
            pattern=(
                TezosOperationsHandlerOriginationPatternConfig(
                    originated_contract=index_config.contracts[0],
                ),
            ),
        ),
    )
    addresses, hashes = await get_origination_filters(index_config, (tzkt,))
    assert addresses == {'KT1RJ6PbjHpwc3M5rw5s2Nbmefwbuwbdxton'}
    assert not hashes

    index_config.handlers = (
        TezosOperationsHandlerConfig(
            callback='hash_origination',
            pattern=(
                TezosOperationsHandlerOriginationPatternConfig(
                    originated_contract=index_config.contracts[1],
                ),
            ),
        ),
    )
    addresses, hashes = await get_origination_filters(index_config, (tzkt,))
    assert not addresses
    assert hashes == {-1585533315}

    index_config.handlers = (
        TezosOperationsHandlerConfig(
            callback='hash_address_origination',
            pattern=(
                TezosOperationsHandlerOriginationPatternConfig(
                    originated_contract=index_config.contracts[2],
                ),
            ),
        ),
    )
    # NOTE: Resolved earlier
    with pytest.raises(FrameworkException):
        await get_origination_filters(index_config, (tzkt,))

    index_config.handlers = (
        TezosOperationsHandlerConfig(
            callback='address_source',
            pattern=(
                TezosOperationsHandlerOriginationPatternConfig(
                    source=index_config.contracts[0],
                ),
            ),
        ),
    )
    addresses, hashes = await get_origination_filters(index_config, (tzkt,))
    assert not addresses
    assert hashes == set()


async def test_get_transaction_filters(tzkt: TezosTzktDatasource, index_config: TezosOperationsIndexConfig) -> None:
    index_config.types = (TezosOperationType.transaction,)
    index_config.contracts[2].code_hash = -680664524

    filters = await get_transaction_filters(index_config)
    assert filters == ({'KT1RJ6PbjHpwc3M5rw5s2Nbmefwbuwbdxton'}, {-680664524, -1585533315})

    index_config.types = ()
    filters = await get_transaction_filters(index_config)
    assert filters == (set(), set())


async def test_get_sync_level() -> None:
    config = DipDupConfig.load([TEST_CONFIGS / 'demo_tezos_token.yml'], True)
    async with AsyncExitStack() as stack:
        dipdup = await create_dummy_dipdup(config, stack)
        index = await spawn_index(dipdup, 'tzbtc_holders_mainnet')

        with pytest.raises(FrameworkException):
            index.get_sync_level()

        index.datasources[0].set_sync_level(None, 0)
        assert index.get_sync_level() == 0

        subs = index._config.get_subscriptions()
        assert subs == {
            HeadSubscription(),
            TransactionSubscription(address='KT1PWx2mnDueood7fEmfbBDKx1D9BAnnXitn'),
        }

        for i, sub in enumerate(subs):
            index.datasources[0].set_sync_level(sub, i + 1)
            assert index.get_sync_level() == i + 1


async def test_realtime() -> None:
    from demo_tezos_token import models

    config = DipDupConfig.load([TEST_CONFIGS / 'demo_tezos_token.yml'], True)
    async with AsyncExitStack() as stack:
        dipdup = await create_dummy_dipdup(config, stack)
        await dipdup._set_up_datasources(stack)

        dispatcher = dipdup._index_dispatcher
        index = cast(TezosOperationsIndex, await spawn_index(dipdup, 'tzbtc_holders_mainnet'))

        # NOTE: Start sync and realtime connection simultaneously.
        first_level = 1365000
        last_level = first_level + 500
        realtime_level = first_level + 1000

        fetcher = await index._create_fetcher(first_level, realtime_level)
        all_operations = {level: ops async for level, ops in fetcher.fetch_by_level()}

        assert len(all_operations) == 4

        # NOTE: Fill the queue while index is IndexStatus.new
        for _, operations in all_operations.items():
            await dispatcher._on_tzkt_operations(
                datasource=index.datasources[0],
                operations=operations,
            )

        assert len(index.queue) == 4
        assert await models.Holder.filter().count() == 0

        # NOTE: We don't want index with `last_level` to be disabled
        await index._enter_sync_state(last_level + 9999)
        await index._synchronize(last_level)
        await index._exit_sync_state(last_level)

        assert index.state.level == last_level
        holders = await models.Holder.all()
        balances = {h.address: h.balance for h in holders}
        # NOTE: A single transfer operation processed
        assert balances == {
            'tz1Rqx3aeJWzLm8S3nuQrTDdGHxucz2twWFL': Decimal('-0.01912431'),
            'tz1RA7UVfpxFML8XSBrtftszHh5fyn53D1DP': Decimal('0.01912431'),
        }

        # NOTE: Skipping the first 500 levels synced and processing the rest
        await index._process_queue()

        assert index.state.level == tuple(all_operations.keys())[-1]
        holders = await models.Holder.all()
        balances = {h.address: h.balance for h in holders}
        assert balances == {
            'tz1Rqx3aeJWzLm8S3nuQrTDdGHxucz2twWFL': Decimal('-0.01912431'),
            'tz1RA7UVfpxFML8XSBrtftszHh5fyn53D1DP': Decimal('0'),
            'KT1Ap287P1NzsnToSJdA4aqSNjPomRaHBZSr': Decimal('0'),
            'tz1aKTCbAUuea2RV9kxqRVRg3HT7f1RKnp6a': Decimal('0.01912431'),
        }
