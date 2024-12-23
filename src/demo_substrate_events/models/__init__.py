from dipdup import fields
from dipdup.models import CachedModel


class Holder(CachedModel):
    address = fields.TextField(primary_key=True)
    balance = fields.DecimalField(decimal_places=6, max_digits=40, default=0)
    turnover = fields.DecimalField(decimal_places=6, max_digits=40, default=0)
    tx_count = fields.BigIntField(default=0)
    last_seen = fields.BigIntField(null=True)

    class Meta:
        maxsize = 2**12
