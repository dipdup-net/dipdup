from dipdup.config.substrate_node import SubstrateNodeDatasourceConfig
from dipdup.datasources.substrate_node import SubstrateNodeDatasource
from dipdup.runtimes import extract_tuple_inner_types
from dipdup.runtimes import get_type_registry


def get_dummy_node() -> 'SubstrateNodeDatasource':
    config = SubstrateNodeDatasourceConfig(
        kind='substrate.node',
        url='https://polkadot-asset-hub-rpc.polkadot.io',
    )
    config._name = 'test'
    return SubstrateNodeDatasource(config)


async def test_extract_tuple_inner_types() -> None:
    datasource = get_dummy_node()

    runtime_config = datasource._interface.runtime_config
    runtime_config.update_type_registry(get_type_registry('legacy'))
    runtime_config.update_type_registry(get_type_registry('statemint'))

    types = (
        # 'Tuple:staging_xcm:v4:location:Locationstaging_xcm:v4:location:Location',
        'Tuple:staging_xcm:v3:multilocation:MultiLocationstaging_xcm:v3:multilocation:MultiLocation',
        'Tuple:U128U8U128',
    )
    expected_inner_types = (
        # ['location', 'location'],
        ['multilocation', 'multilocation'],
        ['u128', 'u8', 'u128'],
    )

    for type_, expected_types in zip(types, expected_inner_types, strict=True):
        result = extract_tuple_inner_types(type_, datasource._interface.runtime_config.type_registry)
        assert result == expected_types
