# generated by DipDup 8.2.0rc1

from __future__ import annotations

from pydantic import BaseModel


class TransferInput(BaseModel):
    to: str
    value: int
