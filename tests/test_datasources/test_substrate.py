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


def test_extract_subsquid_payload() -> None:

    assert extract_subsquid_payload(path_1) == processed_path_1
    assert extract_subsquid_payload(path_2) == processed_path_2
    assert extract_subsquid_payload(path_3) == processed_path_3
