# generated by DipDup 8.1.2

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class Token(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    fa12: str


class Fa2(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    address: str
    nat: str


class Token1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    fa2: Fa2


class Context(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    receiver: str
    rollup: str


class TicketHelperStorage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    token: Token | Token1
    ticketer: str
    erc_proxy: str
    context: Context | None = None
    metadata: dict[str, str]
