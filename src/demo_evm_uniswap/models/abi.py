from pathlib import Path
from typing import Any
from typing import cast

import orjson


def get_abi(path: str) -> dict[str, Any]:
    """Get ABI without context to cache in the module"""
    package_dir = Path(__file__).parent.parent
    abi_path = package_dir / 'abi' / f"{path.replace('.', '/')}.json"
    return cast(dict[str, Any], orjson.loads(abi_path.read_bytes()))