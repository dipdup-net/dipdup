import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from _pytest.fixtures import SubRequest
from pydantic import ValidationError

from dipdup.config import DipDupConfig
from dipdup.config import HasuraConfig
from dipdup.config import HttpConfig
from dipdup.config import PostgresDatabaseConfig
from dipdup.config import ResolvedHttpConfig
from dipdup.config.evm_transactions import EvmTransactionsHandlerConfig
from dipdup.config.tezos import TezosContractConfig
from dipdup.config.tezos_operations import TezosOperationsIndexConfig
from dipdup.config.tezos_tzkt import TezosTzktDatasourceConfig
from dipdup.models.tezos import TezosOperationType
from dipdup.models.tezos_tzkt import HeadSubscription
from dipdup.models.tezos_tzkt import OriginationSubscription
from dipdup.models.tezos_tzkt import TransactionSubscription
from dipdup.yaml import DipDupYAMLConfig

TEST_CONFIGS = Path(__file__).parent.parent / 'configs'


@pytest.fixture(params=list(Path.glob(TEST_CONFIGS, 'demo_*.yml')))
def demo_dipdup_config(request: SubRequest) -> Generator[Path, None, None]:
    yield request.param


def create_config(merge_subs: bool = False, origs: bool = False) -> DipDupConfig:
    path = TEST_CONFIGS / 'dipdup.yaml'
    config = DipDupConfig.load([path])
    if origs:
        config.indexes['hen_mainnet'].types += (TezosOperationType.origination,)  # type: ignore
    config.datasources['tzkt_mainnet'].merge_subscriptions = merge_subs  # type: ignore
    config.initialize()
    return config


async def test_load_initialize() -> None:
    config = create_config()
    index_config = config.indexes['hen_mainnet']
    assert isinstance(index_config, TezosOperationsIndexConfig)

    assert isinstance(config, DipDupConfig)
    destination = index_config.handlers[0].pattern[0].destination  # type: ignore[union-attr]
    assert destination == config.contracts['HEN_minter']


async def test_operation_subscriptions() -> None:
    index_config = create_config(False, False).indexes['hen_mainnet']
    assert isinstance(index_config, TezosOperationsIndexConfig)
    assert index_config.get_subscriptions() == {
        TransactionSubscription(address='KT1Hkg5qeNhfwpKW4fXvq7HGZB9z2EnmCCA9'),
        HeadSubscription(),
    }

    index_config = create_config(True, False).indexes['hen_mainnet']
    assert isinstance(index_config, TezosOperationsIndexConfig)
    assert index_config.get_subscriptions() == {TransactionSubscription(), HeadSubscription()}

    index_config = create_config(False, True).indexes['hen_mainnet']
    assert isinstance(index_config, TezosOperationsIndexConfig)
    assert index_config.get_subscriptions() == {
        TransactionSubscription(address='KT1Hkg5qeNhfwpKW4fXvq7HGZB9z2EnmCCA9'),
        OriginationSubscription(),
        HeadSubscription(),
    }

    index_config = create_config(True, True).indexes['hen_mainnet']
    assert isinstance(index_config, TezosOperationsIndexConfig)
    assert index_config.get_subscriptions() == {
        TransactionSubscription(),
        OriginationSubscription(),
        HeadSubscription(),
    }


async def test_validators() -> None:
    with pytest.raises(ValidationError):
        TezosContractConfig(kind='tezos', address='KT1lalala')
    with pytest.raises(ValidationError):
        TezosContractConfig(kind='tezos', address='lalalalalalalalalalalalalalalalalala')
    with pytest.raises(ValidationError):
        TezosTzktDatasourceConfig(kind='tezos.tzkt', url='not_an_url')


async def test_reserved_keywords() -> None:
    assert (
        EvmTransactionsHandlerConfig(  # type: ignore[comparison-overlap]
            callback='test',
            from_='from',  # type: ignore[arg-type]
        ).from_
        == 'from'
    )

    # FIXME: Can't use `from_` field alias in dataclasses
    raw_config, _ = DipDupYAMLConfig.load(paths=[TEST_CONFIGS / 'demo_tezos_token_transfers_4.yml'])
    assert raw_config['indexes']['tzbtc_holders_mainnet']['handlers'][1]['from_'] == 'tzbtc_mainnet'

    config = DipDupConfig.load([TEST_CONFIGS / 'demo_tezos_token_transfers_4.yml'])
    assert config.indexes['tzbtc_holders_mainnet'].handlers[1].from_ == 'tzbtc_mainnet'  # type: ignore[misc,union-attr]


async def test_dump() -> None:
    config = create_config()

    tmp_path = Path(tempfile.mkstemp(suffix='yaml')[1])
    tmp_path.write_text(config.dump())

    config = DipDupConfig.load([tmp_path], environment=False)
    config.initialize()


async def test_secrets() -> None:
    db_config = PostgresDatabaseConfig(
        kind='postgres',
        host='localhost',
        password='SeCrEt=)',
    )
    hasura_config = HasuraConfig(
        url='https://localhost',
        admin_secret='SeCrEt=)',
    )
    assert 'localhost' in str(db_config)
    assert 'SeCrEt=)' not in str(db_config)
    assert 'localhost' in str(hasura_config)
    assert 'SeCrEt=)' not in str(hasura_config)


async def test_http_config() -> None:
    config = ResolvedHttpConfig.create(
        HttpConfig(
            retry_count=10,
            retry_sleep=10,
        ),
        HttpConfig(
            retry_count=20,
            replay_path='replays',
        ),
    )
    assert config == ResolvedHttpConfig(
        retry_count=20,
        retry_sleep=10,
        retry_multiplier=2.0,
        ratelimit_rate=0,
        ratelimit_period=0,
        ratelimit_sleep=0,
        connection_limit=100,
        connection_timeout=60,
        batch_size=10000,
        replay_path='replays',
    )


async def test_load_demo_config(demo_dipdup_config: Path) -> None:
    DipDupConfig.load([demo_dipdup_config])
