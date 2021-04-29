# generated by datamodel-codegen:
#   filename:  mint.json

from __future__ import annotations

from typing import Dict

from pydantic import BaseModel


class MintParameter(BaseModel):
    address: str
    amount: str
    token_id: str
    token_info: Dict[str, str]
