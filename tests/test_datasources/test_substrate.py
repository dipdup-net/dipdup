
from dipdup.runtimes import extract_subsquid_payload


path = [
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

processed_path = (
    (
        {
            'parents': 0,
            'interior': {
                'X2': (
                    {'PalletInstance': 50},
                    {'GeneralIndex': 1337},
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


def test_extract_subsquid_payload():

    assert extract_subsquid_payload(path) == processed_path
