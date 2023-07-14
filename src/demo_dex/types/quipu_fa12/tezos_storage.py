# generated by datamodel-codegen:
#   filename:  tezos_storage.json

from __future__ import annotations

from typing import Dict
from typing import Optional

from pydantic import BaseModel
from pydantic import ConfigDict


class Ledger(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    allowances: Dict[str, str]
    balance: str
    frozen_balance: str


class UserRewards(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    reward: str
    reward_paid: str


class Voters(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    candidate: Optional[str] = None
    last_veto: str
    veto: str
    vote: str


class Storage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    baker_validator: str
    current_candidate: Optional[str] = None
    current_delegated: Optional[str] = None
    last_update_time: str
    last_veto: str
    ledger: Dict[str, Ledger]
    period_finish: str
    reward: str
    reward_paid: str
    reward_per_sec: str
    reward_per_share: str
    tez_pool: str
    token_address: str
    token_pool: str
    total_reward: str
    total_supply: str
    total_votes: str
    user_rewards: Dict[str, UserRewards]
    veto: str
    vetos: Dict[str, str]
    voters: Dict[str, Voters]
    votes: Dict[str, str]


class QuipuFa12Storage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    dex_lambdas: Dict[str, str]
    metadata: Dict[str, str]
    storage: Storage
    token_lambdas: Dict[str, str]
