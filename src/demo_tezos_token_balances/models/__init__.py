from dipdup import fields
from dipdup.models import Model


class Holder(Model):
    address = fields.TextField(primary_key=True)
    balance = fields.DecimalField(decimal_places=8, max_digits=20, default=0)
