from contextlib import suppress
from decimal import Decimal

from eth_typing import ChecksumAddress
from eth_utils.address import to_checksum_address
from web3 import AsyncWeb3

from demo_evm_uniswap import models as models
from demo_evm_uniswap.models.abi import get_abi
from demo_evm_uniswap.models.repo import models_repo

MINIMUM_ETH_LOCKED = Decimal('60')
STABLE_COINS = {
    '0x6b175474e89094c44da98b954eedeac495271d0f',
    '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
    '0xdac17f958d2ee523a2206206994597c13d831ec7',
    '0x0000000000085d4780b73119b644ae5ecd22b376',
    '0x956f47f50a910163d8bf957cf5846d573e7f87ca',
    '0x4dd28568d05f09b02220b09c2cb307bfd837cb95',
}
WETH_ADDRESS = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
WHITELIST_TOKENS = {
    WETH_ADDRESS,
    '0x6b175474e89094c44da98b954eedeac495271d0f',  # DAI
    '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',  # USDC
    '0xdac17f958d2ee523a2206206994597c13d831ec7',  # USDT
    '0x0000000000085d4780b73119b644ae5ecd22b376',  # TUSD
    '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599',  # WBTC
    '0x5d3a536e4d6dbd6114cc1ead35777bab948e3643',  # cDAI
    '0x39aa39c021dfbae8fac545936693ac917d5e7563',  # cUSDC
    '0x86fadb80d8d2cff3c3680819e4da99c10232ba0f',  # EBASE
    '0x57ab1ec28d129707052df4df418d58a2d46d5f51',  # sUSD
    '0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2',  # MKR
    '0xc00e94cb662c3520282e6f5717214004a7f26888',  # COMP
    '0x514910771af9ca656af840dff83e8264ecf986ca',  # LINK
    '0xc011a73ee8576fb46f5e1c5751ca3b9fe0af2a6f',  # SNX
    '0x0bc529c00c6401aef6d220be8c6ea1667f6ad93e',  # YFI
    '0x111111111117dc0aa78b770fa6a738034120c302',  # 1INCH
    '0xdf5e0e81dff6faf3a7e52ba697820c5e32d806a8',  # yCurv
    '0x956f47f50a910163d8bf957cf5846d573e7f87ca',  # FEI
    '0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0',  # MATIC
    '0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9',  # AAVE
    '0xfe2e637202056d30016725477c5da089ab0a043a',  # sETH2
}


def convert_token_amount(amount: int, decimals: int) -> Decimal:
    if decimals == 0:
        return Decimal(amount)
    return Decimal(amount) / Decimal(10) ** decimals


class ERC20Token:
    def __init__(self, address: ChecksumAddress, web3: AsyncWeb3):
        self.web3 = web3
        self.address = address
        self.contract = self.web3.eth.contract(
            address=self.address,
            abi=get_abi('erc20.ERC20'),
            )

    @classmethod
    def from_address(cls, web3: AsyncWeb3, token_address: str | bytes) -> 'ERC20Token':
        address = to_checksum_address(token_address)
        return ERC20Token(address, web3)

    async def get_symbol(self) -> str:
        # FIXME: https://github.com/ethereum/web3.py/issues/2658
        with suppress(Exception):
            symbol = await self.contract.functions.symbol().call()
            return str(symbol).replace('\x00', '')

        with suppress(Exception):
            contract = self.web3.eth.contract(
                address=self.address,
                abi=get_abi('erc20.ERC20SymbolBytes'),
            )
            symbol = await contract.functions.symbol().call() 
            return bytes(symbol).decode('utf-8').replace('\x00', '')

        token = StaticTokenDefinition.from_address(self.address)
        if token:
            return token.symbol

        return 'unknown'

    async def get_name(self) -> str:
        with suppress(Exception):
            name = await self.contract.functions.name().call()
            return str(name).replace('\x00', '')

        with suppress(Exception):
            contract = self.web3.eth.contract(
                address=self.address,
                abi=get_abi('erc20.ERC20NameBytes'),
            )
            name = await contract.functions.name().call()
            return bytes(name).decode('utf-8').replace('\x00', '')

        token = StaticTokenDefinition.from_address(self.address)
        if token:
            return token.name

        return 'unknown'

    async def get_decimals(self) -> int:
        with suppress(Exception):
            return await self.contract.functions.decimals().call()  # type: ignore[no-any-return]

        token = StaticTokenDefinition.from_address(self.address)
        if token:
            return token.decimals

        raise ValueError(f'Cannot get decimals for token {self.address}')

    async def get_total_supply(self) -> int:
        # with suppress(Exception):
        #     return await self.contract.functions.totalSupply().call()

        return 0


class StaticTokenDefinition:
    def __init__(self, address: str, symbol: str, name: str, decimals: int):
        self.address = address
        self.symbol = symbol
        self.name = name
        self.decimals = decimals

    @staticmethod
    def get_static_definitions() -> list['StaticTokenDefinition']:
        return [
            StaticTokenDefinition('0xe0b7927c4af23765cb51314a0e0521a9645f0e2a', 'DGD', 'DGD', 9),
            StaticTokenDefinition('0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9', 'AAVE', 'Aave Token', 18),
            StaticTokenDefinition('0xeb9951021698b42e4399f9cbb6267aa35f82d59d', 'LIF', 'Lif', 18),
            StaticTokenDefinition('0xbdeb4b83251fb146687fa19d1c660f99411eefe3', 'SVD', 'savedroid', 18),
            StaticTokenDefinition('0xbb9bc244d798123fde783fcc1c72d3bb8c189413', 'TheDAO', 'TheDAO', 16),
            StaticTokenDefinition('0x38c6a68304cdefb9bec48bbfaaba5c5b47818bb2', 'HPB', 'HPBCoin', 18),
        ]

    @staticmethod
    def from_address(token_address: ChecksumAddress) -> 'StaticTokenDefinition | None':
        static_definitions = StaticTokenDefinition.get_static_definitions()
        for static_definition in static_definitions:
            if to_checksum_address(static_definition.address) == token_address:
                return static_definition
        return None


async def token_derive_eth(token: models.Token) -> Decimal:
    if token.id == WETH_ADDRESS:
        return Decimal(1)

    eth_usd = await models_repo.get_eth_usd_rate()

    if token.id in STABLE_COINS:
        return Decimal(1) / eth_usd if eth_usd else Decimal()

    largest_liquidity_eth = Decimal()
    price_so_far = Decimal()

    for pool_address in token.whitelist_pools:
        pool = await models.Pool.cached_get(pool_address)
        if pool.liquidity == 0:
            continue

        if token.id == pool.token0:
            other_token = await models.Token.cached_get(pool.token1_id)
            eth_locked = pool.total_value_locked_token1 * other_token.derived_eth
            if eth_locked > largest_liquidity_eth and eth_locked > MINIMUM_ETH_LOCKED:
                largest_liquidity_eth = eth_locked
                price_so_far = pool.token1_price * other_token.derived_eth

        elif token.id == pool.token1:
            other_token = await models.Token.cached_get(pool.token0_id)
            eth_locked = pool.total_value_locked_token0 * other_token.derived_eth
            if eth_locked > largest_liquidity_eth and eth_locked > MINIMUM_ETH_LOCKED:
                largest_liquidity_eth = eth_locked
                price_so_far = pool.token0_price * other_token.derived_eth

    return price_so_far
