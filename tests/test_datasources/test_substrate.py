import pytest

from dipdup.runtimes import extract_subsquid_payload

path_1 = [
    [
        {
            'parents': 0,
            'interior': {
                '__kind': 'X2',
                'value': [
                    {
                        '__kind': 'PalletInstance',
                        'value': 50,
                    },
                    {
                        '__kind': 'GeneralIndex',
                        'value': '1337',
                    },
                ],
            },
        },
        84640,
    ],
    [
        {
            'parents': 1,
            'interior': {
                '__kind': 'Here',
            },
        },
        122612710,
    ],
]
path_2 = [
    {
        'interior': {
            '__kind': 'X3',
            'value': [
                {'__kind': 'Parachain', 'value': 1000},
                {'__kind': 'GeneralIndex', 'value': 50},
                {'__kind': 'GeneralIndex', 'value': 42069},
            ],
        },
        'parents': 1,
    }
]

path_3 = [
    {
        'interior': {
            '__kind': 'X3',
            'value': [
                {'__kind': 'Parachain', 'value': 2004},
                {'__kind': 'PalletInstance', 'value': 110},
                {'__kind': 'AccountKey20', 'key': 39384093},
            ],
        },
        'parents': 1,
    }
]

subsquid_general_key_with_value_payload_example = {
    'parents': 1,
    'interior': {
        '__kind': 'X2',
        'value': [
            {'__kind': 'Parachain', 'value': 2030},
            {
                '__kind': 'GeneralKey',
                'value': '0x02c80084af223c8b598536178d9361dc55bfda6818',
            },
        ],
    },
}
subsquid_general_key_with_data_and_length_payload_example = {
    'parents': 1,
    'interior': {
        '__kind': 'X2',
        'value': [
            {'__kind': 'Parachain', 'value': 2030},
            {
                '__kind': 'GeneralKey',
                'data': '0x0809000000000000000000000000000000000000000000000000000000000000',
                'length': 2,
            },
        ],
    },
}


processed_path_1 = (
    (
        {
            'parents': 0,
            'interior': {
                'X2': (
                    {'PalletInstance': 50},
                    {'GeneralIndex': '1337'},
                ),
            },
        },
        84640,
    ),
    (
        {
            'parents': 1,
            'interior': 'Here',
        },
        122612710,
    ),
)

processed_path_2 = (
    {
        'parents': 1,
        'interior': {
            'X3': (
                {'Parachain': 1000},
                {'GeneralIndex': 50},
                {'GeneralIndex': 42069},
            ),
        },
    },
)

processed_path_3 = (
    {
        'parents': 1,
        'interior': {
            'X3': (
                {'Parachain': 2004},
                {'PalletInstance': 110},
                {'AccountKey20': 39384093},
            ),
        },
    },
)
node_general_key_with_value_payload_example = {
    'parents': 1,
    'interior': {
        'X2': (
            {'Parachain': 2030},
            {'GeneralKey': '0x02c80084af223c8b598536178d9361dc55bfda6818'},
        ),
    },
}
node_general_key_with_data_and_length_payload_example = {
    'parents': 1,
    'interior': {
        'X2': (
            {'Parachain': 2030},
            {
                'GeneralKey': {
                    'data': '0x0809000000000000000000000000000000000000000000000000000000000000',
                    'length': 2,
                }
            },
        ),
    },
}


@pytest.mark.parametrize(
    'subsquid_payload, expected_node_payload',
    (
        (path_1, processed_path_1),
        (path_2, processed_path_2),
        (path_3, processed_path_3),
        (
            subsquid_general_key_with_value_payload_example,
            node_general_key_with_value_payload_example,
        ),
        (
            subsquid_general_key_with_data_and_length_payload_example,
            node_general_key_with_data_and_length_payload_example,
        ),
    ),
)
def test_extract_subsquid_payload(subsquid_payload, expected_node_payload) -> None:
    assert extract_subsquid_payload(subsquid_payload) == expected_node_payload
