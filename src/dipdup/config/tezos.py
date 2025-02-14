from __future__ import annotations

import random
from typing import Annotated
from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from pydantic.functional_validators import AfterValidator

from dipdup.config import Alias
from dipdup.config import ContractConfig
from dipdup.config import IndexConfig
from dipdup.config.tezos_tzkt import TezosTzktDatasourceConfig
from dipdup.exceptions import ConfigurationError
from dipdup.exceptions import FrameworkException
from dipdup.models.tezos_tzkt import HeadSubscription
from dipdup.subscriptions import Subscription

ADDRESS_LENGTH = 36
SMART_CONTRACT_PREFIX = 'KT1'
SMART_ROLLUP_PREFIX = 'sr1'
WALLET_PREFIXES = ('tz1', 'tz2', 'tz3')


def is_contract_address(address: str) -> bool:
    return len(address) == ADDRESS_LENGTH and address.startswith(SMART_CONTRACT_PREFIX)


def is_rollup_address(address: str) -> bool:
    return len(address) == ADDRESS_LENGTH and address.startswith(SMART_ROLLUP_PREFIX)


def is_wallet_address(address: str) -> bool:
    return len(address) == ADDRESS_LENGTH and address.startswith(WALLET_PREFIXES)


def _validate_tezos_address(v: str) -> str:
    # NOTE: It's a `config export` call with environment variable substitution disabled
    if '${' in v:
        return v

    if not (is_contract_address(v) or is_rollup_address(v) or is_wallet_address(v)):
        raise ValueError(f'`{v}` is not a valid Tezos address')

    return v


type TezosAddress = Annotated[str, AfterValidator(_validate_tezos_address)]


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosContractConfig(ContractConfig):
    """Tezos contract config.

    :param kind: Always `tezos`
    :param address: Contract address
    :param code_hash: Contract code hash or address to fetch it from
    :param typename: Alias for the contract script
    """

    kind: Literal['tezos'] = 'tezos'
    address: TezosAddress | None = None
    code_hash: int | TezosAddress | None = None
    typename: str | None = None

    def get_address(self) -> str:
        if self.address is None:
            raise ConfigurationError(f'`contracts.{self.name}`: `address` field is required`')
        return self.address

    @property
    def resolved_code_hash(self) -> int | None:
        if isinstance(self.code_hash, str):
            raise FrameworkException('`code_hash` was not resolved during startup')
        return self.code_hash


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class TezosIndexConfig(IndexConfig):
    """TzKT index config

    :param kind: starts with 'tezos'
    :param datasources: `tezos` datasources to use
    """

    datasources: tuple[Alias[TezosTzktDatasourceConfig], ...]

    @property
    def merge_subscriptions(self) -> bool:
        return any(d.merge_subscriptions for d in self.datasources)

    @property
    def random_datasource(self) -> TezosTzktDatasourceConfig:
        return random.choice(self.datasources)

    def get_subscriptions(self) -> set[Subscription]:
        return {HeadSubscription()}
