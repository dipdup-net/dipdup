# generated by DipDup 8.2.0

from __future__ import annotations

from typing import TypedDict

"""
Some assets were transferred. [asset_id, from, to, amount]
"""
V601 = TypedDict(
    'V601',
    {
        'asset_id': int,
        'from': str,
        'to': str,
        'amount': int,
    },
)
