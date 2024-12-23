# generated by DipDup 8.2.0rc1

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class Content(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    nat: str
    bytes: str | None = None


class Ticket(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    address: str
    content: Content
    amount: str


class WithdrawParameter(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    receiver: str
    ticket: Ticket
