from dipdup import fields
from dipdup.models import Model


class Deposit(Model):
    id = fields.IntField(primary_key=True)
    level = fields.IntField()
    token = fields.CharField(max_length=36)
    amount = fields.IntField()
