# generated by DipDup 8.0.0b1

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
    routing_info: str
    rollup: str


class TicketHelperStorage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    token: Token | Token1
    ticketer: str
    context: Context | None = None
    metadata: dict[str, str]
