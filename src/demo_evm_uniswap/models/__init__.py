from dipdup import fields
from dipdup.models import CachedModel
from dipdup.models import Model

ADDRESS_ZERO = '0x0000000000000000000000000000000000000000'


class Factory(CachedModel):
    id = fields.TextField(pk=True)
    # amount of pools created
    pool_count = fields.BigIntField(default=0)
    # amount of transactions all time
    tx_count = fields.BigIntField(default=0)
    # total volume all time in derived USD
    total_volume_usd = fields.DecimalField(decimal_places=2, max_digits=32, default=0)
    # total volume all time in derived ETH
    total_volume_eth = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # total swap fees all time in USD
    total_fees_usd = fields.DecimalField(decimal_places=2, max_digits=32, default=0)
    # total swap fees all time in USD
    total_fees_eth = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all volume even through less reliable USD values
    untracked_volume_usd = fields.DecimalField(decimal_places=2, max_digits=32, default=0)
    # TVL derived in USD
    total_value_locked_usd = fields.DecimalField(decimal_places=2, max_digits=32, default=0)
    # TVL derived in ETH
    total_value_locked_eth = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # TVL derived in USD untracked
    total_value_locked_usd_untracked = fields.DecimalField(decimal_places=2, max_digits=32, default=0)
    # TVL derived in ETH untracked
    total_value_locked_eth_untracked = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # current owner of the factory
    owner = fields.TextField(default=ADDRESS_ZERO)


class Token(CachedModel):
    id = fields.TextField(pk=True)
    # token symbol
    symbol = fields.TextField()
    # token name
    name = fields.TextField()
    # token decimals
    decimals = fields.BigIntField()
    # token total supply
    total_supply = fields.BigIntField()
    # volume in token units
    volume = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # volume in derived USD
    volume_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0, index=True)
    # volume in USD even on pools with less reliable USD values
    untracked_volume_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # fees in USD
    fees_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # transactions across all pools that include this token
    tx_count = fields.BigIntField(default=0)
    # number of pools containing this token
    pool_count = fields.BigIntField(default=0)
    # liquidity across all pools in token units
    total_value_locked = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # liquidity across all pools in derived USD
    total_value_locked_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # TVL derived in USD untracked
    total_value_locked_usd_untracked = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # derived price in ETH
    derived_eth = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # pools token is in that are whitelisted for USD pricing
    whitelist_pools = fields.ArrayField(default=[])


class Pool(CachedModel):
    id = fields.TextField(pk=True)
    # creation
    created_at_timestamp = fields.BigIntField()
    # block pool was created at
    created_at_block_number = fields.BigIntField()
    # token0
    token0: fields.ForeignKeyRelation[Token] = fields.ForeignKeyField('models.Token', related_name='pools_token0')
    # token1
    token1: fields.ForeignKeyRelation[Token] = fields.ForeignKeyField('models.Token', related_name='pools_token1')
    # fee amount
    fee_tier = fields.BigIntField(default=0)
    # in range liquidity
    liquidity = fields.DecimalField(decimal_places=0, max_digits=76, default=0)
    # current price tracker
    sqrt_price = fields.DecimalField(decimal_places=0, max_digits=76, default=0)
    # TODO: requires rpc calls
    # tracker for global fee growth
    # fee_growth_global_0x128 = fields.BigIntField(default=0)
    # tracker for global fee growth
    # fee_growth_global_1x128 = fields.BigIntField(default=0)
    # token0 per token1
    token0_price = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # token1 per token0
    token1_price = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # current tick
    tick = fields.BigIntField(null=True)
    # current observation index
    observation_index = fields.BigIntField(default=0)
    # all time token0 swapped
    volume_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time token1 swapped
    volume_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time USD swapped
    volume_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time USD swapped, unfiltered for unreliable USD pools
    untracked_volume_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # fees in USD
    fees_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time number of transactions
    tx_count = fields.BigIntField(default=0)
    # all time fees collected token0
    collected_fees_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time fees collected token1
    collected_fees_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time fees collected derived USD
    collected_fees_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # total token 0 across all ticks
    total_value_locked_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # total token 1 across all ticks
    total_value_locked_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # tvl derived ETH
    total_value_locked_eth = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # tvl USD
    total_value_locked_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # TVL derived in USD untracked
    total_value_locked_usd_untracked = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # Fields used to help derived relationship
    liquidity_provider_count = fields.BigIntField(default=0)  # used to detect new exchanges

    token0_id: str
    token1_id: str


class Tick(Model):
    id = fields.TextField(pk=True)
    # tick index
    tick_idx = fields.BigIntField()
    # pointer to pool
    pool: fields.ForeignKeyRelation[Pool] = fields.ForeignKeyField('models.Pool', related_name='ticks')
    # total liquidity pool has as tick lower or upper
    liquidity_gross = fields.DecimalField(decimal_places=0, max_digits=76, default=0)
    # how much liquidity changes when tick crossed
    liquidity_net = fields.DecimalField(decimal_places=0, max_digits=76, default=0)
    # calculated price of token0 of tick within this pool - constant
    price0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # calculated price of token1 of tick within this pool - constant
    price1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # lifetime volume of token0 with this tick in range
    volume_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # lifetime volume of token1 with this tick in range
    volume_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # lifetime volume in derived USD with this tick in range
    volume_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # lifetime volume in untracked USD with this tick in range
    untracked_volume_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # fees in USD
    fees_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time collected fees in token0
    collected_fees_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time collected fees in token1
    collected_fees_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time collected fees in USD
    collected_fees_usd = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # created time
    created_at_timestamp = fields.BigIntField()
    # created block
    created_at_block_number = fields.BigIntField()
    # Fields used to help derived relationship
    liquidity_provider_count = fields.BigIntField(default=0)  # used to detect new exchanges
    # vars needed for fee computation
    # TODO: require rpc calls
    # fee_growth_outside_0x128 = fields.BigIntField()
    # fee_growth_outside_1x128 = fields.BigIntField()


# NOTE: Cached, but with custom logic; see `demo_uniswap.utils.position`
class Position(Model):
    id = fields.BigIntField(pk=True)
    # owner of the NFT
    owner = fields.CharField(max_length=42, default=ADDRESS_ZERO)
    # pool position is within
    pool: fields.ForeignKeyRelation[Pool] = fields.ForeignKeyField('models.Pool', related_name='positions')
    # allow indexing by tokens
    token0: fields.ForeignKeyRelation[Token] = fields.ForeignKeyField(
        'models.Token', related_name='positions_token0', null=True
    )
    # allow indexing by tokens
    token1: fields.ForeignKeyRelation[Token] = fields.ForeignKeyField(
        'models.Token', related_name='positions_token1', null=True
    )
    # lower tick of the position
    tick_lower: fields.ForeignKeyRelation[Tick] = fields.ForeignKeyField(
        'models.Tick', related_name='positions_tick_lower', null=True
    )
    # upper tick of the position
    tick_upper: fields.ForeignKeyRelation[Tick] = fields.ForeignKeyField(
        'models.Tick', related_name='positions_tick_upper', null=True
    )
    # total position liquidity
    liquidity = fields.DecimalField(max_digits=76, decimal_places=0, default=0)
    # amount of token 0 ever deposited to position
    deposited_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount of token 1 ever deposited to position
    deposited_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount of token 0 ever withdrawn from position (without fees)
    withdrawn_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount of token 1 ever withdrawn from position (without fees)
    withdrawn_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time collected fees in token0
    collected_fees_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time collected fees in token1
    collected_fees_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # vars needed for fee computation
    # fee_growth_inside_0_last_x128 = fields.BigIntField(default=0)
    # fee_growth_inside_1_last_x128 = fields.BigIntField(default=0)
    blacklisted = fields.BooleanField(default=False)

    token0_id: str
    token1_id: str
    tick_lower_id: str
    tick_upper_id: str
    pool_id: int

    @classmethod
    async def reset(cls) -> None:
        await cls.filter().update(
            liquidity=0,
            deposited_token0=0,
            deposited_token1=0,
            withdrawn_token0=0,
            withdrawn_token1=0,
            collected_fees_token0=0,
            collected_fees_token1=0,
        )


class PositionSnapshot(Model):
    id = fields.TextField(pk=True)
    # owner of the NFT
    owner = fields.CharField(max_length=42)
    # pool the position is within
    pool: fields.ForeignKeyRelation[Pool] = fields.ForeignKeyField('models.Pool', related_name='position_snapshots')
    # position of which the snap was taken of
    position: fields.ForeignKeyRelation[Position] = fields.ForeignKeyField('models.Position', related_name='snapshots')
    # block in which the snap was created
    block_number = fields.BigIntField()
    # timestamp of block in which the snap was created
    timestamp = fields.BigIntField()
    # total position liquidity
    liquidity = fields.DecimalField(max_digits=76, decimal_places=0, default=0)
    # amount of token 0 ever deposited to position
    deposited_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount of token 1 ever deposited to position
    deposited_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount of token 0 ever withdrawn from position (without fees)
    withdrawn_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount of token 1 ever withdrawn from position (without fees)
    withdrawn_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time collected fees in token0
    collected_fees_token0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # all time collected fees in token1
    collected_fees_token1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # internal vars needed for fee computation
    # fee_growth_inside_0_last_x128 = fields.BigIntField()
    # fee_growth_inside_1_last_x128 = fields.BigIntField()


class Mint(Model):
    id = fields.TextField(pk=True)
    # which txn the mint was included in
    transaction_hash = fields.TextField()
    # time of txn
    timestamp = fields.BigIntField()
    # pool position is within
    pool: fields.ForeignKeyRelation[Pool] = fields.ForeignKeyField('models.Pool', related_name='mints')
    # allow indexing by tokens
    token0: fields.ForeignKeyRelation[Token] = fields.ForeignKeyField('models.Token', related_name='mints_token0')
    # allow indexing by tokens
    token1: fields.ForeignKeyRelation[Token] = fields.ForeignKeyField('models.Token', related_name='mints_token1')
    # owner of position where liquidity minted to
    owner = fields.CharField(max_length=42)
    # the address that minted the liquidity
    sender = fields.CharField(max_length=42, null=True)
    # TODO: txn origin
    # origin = fields.CharField(max_length=42)  # the EOA that initiated the txn
    # amount of liquidity minted
    amount = fields.DecimalField(decimal_places=0, max_digits=76, default=0)
    # amount of token 0 minted
    amount0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount of token 1 minted
    amount1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # derived amount based on available prices of tokens
    amount_usd = fields.DecimalField(decimal_places=18, max_digits=76, null=True)
    # lower tick of the position
    tick_lower = fields.BigIntField()
    # upper tick of the position
    tick_upper = fields.BigIntField()
    # order within the txn
    log_index = fields.BigIntField(null=True)


class Burn(Model):
    id = fields.TextField(pk=True)
    # txn burn was included in
    transaction_hash = fields.TextField()
    # pool position is within
    pool: fields.ForeignKeyRelation[Pool] = fields.ForeignKeyField('models.Pool', related_name='burns')
    # allow indexing by tokens
    token0: fields.ForeignKeyRelation[Token] = fields.ForeignKeyField('models.Token', related_name='burns_token0')
    # allow indexing by tokens
    token1: fields.ForeignKeyRelation[Token] = fields.ForeignKeyField('models.Token', related_name='burns_token1')
    # need this to pull recent txns for specific token or pool
    timestamp = fields.BigIntField()
    # owner of position where liquidity was burned
    owner = fields.CharField(max_length=42, null=True)
    # txn origin
    # origin = fields.CharField(max_length=42)  # the EOA that initiated the txn
    # amount of liquidity burned
    amount = fields.DecimalField(decimal_places=0, max_digits=76, default=0)
    # amount of token 0 burned
    amount0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount of token 1 burned
    amount1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # derived amount based on available prices of tokens
    amount_usd = fields.DecimalField(decimal_places=2, max_digits=32, default=0)
    # lower tick of position
    tick_lower = fields.BigIntField()
    # upper tick of position
    tick_upper = fields.BigIntField()
    # position within the transactions
    log_index = fields.BigIntField()


class Swap(Model):
    id = fields.TextField(pk=True)
    # pointer to transaction
    transaction_hash = fields.TextField()
    # timestamp of transaction
    timestamp = fields.DatetimeField(index=True)
    # pool swap occured within
    pool: fields.ForeignKeyRelation[Pool] = fields.ForeignKeyField('models.Pool', related_name='swaps')
    # allow indexing by tokens
    token0: fields.ForeignKeyRelation[Token] = fields.ForeignKeyField('models.Token', related_name='swaps_token0')
    # allow indexing by tokens
    token1: fields.ForeignKeyRelation[Token] = fields.ForeignKeyField('models.Token', related_name='swaps_token1')
    # sender of the swap
    sender = fields.CharField(max_length=42)
    # recipient of the swap
    recipient = fields.CharField(max_length=42)
    # txn origin
    origin = fields.CharField(max_length=42)  # the EOA that initiated the txn
    # delta of token0 swapped
    amount0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # delta of token1 swapped
    amount1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # derived info
    amount_usd = fields.DecimalField(decimal_places=2, max_digits=32, default=0)
    # The sqrt(price) of the pool after the swap, as a Q64.96
    sqrt_price_x96 = fields.DecimalField(decimal_places=0, max_digits=76, default=0)
    # the tick after the swap
    tick = fields.BigIntField()
    # index within the txn
    log_index = fields.BigIntField()


class Collect(Model):
    id = fields.TextField(pk=True)
    # pointer to txn
    transaction_hash = fields.TextField()
    # timestamp of event
    timestamp = fields.BigIntField()
    # pool collect occured within
    pool: fields.ForeignKeyRelation[Pool] = fields.ForeignKeyField('models.Pool', related_name='collects')
    # owner of position collect was performed on
    owner = fields.CharField(max_length=42, null=True)
    # amount of token0 collected
    amount0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount of token1 collected
    amount1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # derived amount based on available prices of tokens
    amount_usd = fields.DecimalField(decimal_places=18, max_digits=76, null=True)
    # lower tick of position
    tick_lower = fields.BigIntField()
    # upper tick of position
    tick_upper = fields.BigIntField()
    # index within the txn
    log_index = fields.BigIntField()


class Flash(Model):
    id = fields.TextField(pk=True)
    # pointer to txn
    transaction_hash = fields.TextField()
    # timestamp of event
    timestamp = fields.BigIntField()
    # pool collect occured within
    pool: fields.ForeignKeyRelation[Pool] = fields.ForeignKeyField('models.Pool', related_name='flashed')
    # sender of the flash
    sender = fields.CharField(max_length=42)
    # recipient of the flash
    recipient = fields.CharField(max_length=42)
    # amount of token0 flashed
    amount0 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount of token1 flashed
    amount1 = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # derived amount based on available prices of tokens
    amount_usd = fields.DecimalField(decimal_places=2, max_digits=32, default=0)
    # amount token0 paid for flash
    amount0_paid = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # amount token1 paid for flash
    amount1_paid = fields.DecimalField(decimal_places=18, max_digits=96, default=0)
    # index within the txn
    log_index = fields.BigIntField()