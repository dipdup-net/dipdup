from __future__ import annotations

from contextlib import suppress
from copy import copy
from decimal import Decimal
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeVar

import orjson
from tortoise.contrib.postgres.fields import ArrayField as ArrayField
from tortoise.exceptions import ConfigurationError as TortoiseConfigurationError
from tortoise.fields import relational as relational
from tortoise.fields.base import CASCADE as CASCADE
from tortoise.fields.base import NO_ACTION as NO_ACTION
from tortoise.fields.base import RESTRICT as RESTRICT
from tortoise.fields.base import SET_DEFAULT as SET_DEFAULT
from tortoise.fields.base import SET_NULL as SET_NULL
from tortoise.fields.base import Field as Field
from tortoise.fields.data import BigIntField as BigIntField
from tortoise.fields.data import BinaryField as BinaryField
from tortoise.fields.data import BooleanField as BooleanField
from tortoise.fields.data import CharField as CharField
from tortoise.fields.data import DateField as DateField
from tortoise.fields.data import DatetimeField as DatetimeField
from tortoise.fields.data import FloatField as FloatField
from tortoise.fields.data import IntEnumFieldInstance as IntEnumFieldInstance
from tortoise.fields.data import IntField as IntField
from tortoise.fields.data import JSONField as _JSONField
from tortoise.fields.data import SmallIntField as SmallIntField
from tortoise.fields.data import TimeDeltaField as TimeDeltaField
from tortoise.fields.data import TimeField as TimeField
from tortoise.fields.data import UUIDField as UUIDField
from tortoise.fields.relational import BackwardFKRelation as BackwardFKRelation
from tortoise.fields.relational import BackwardOneToOneRelation as BackwardOneToOneRelation
from tortoise.fields.relational import ForeignKeyFieldInstance as ForeignKeyFieldInstance
from tortoise.fields.relational import ForeignKeyNullableRelation as ForeignKeyNullableRelation
from tortoise.fields.relational import ForeignKeyRelation as ForeignKeyRelation
from tortoise.fields.relational import ManyToManyFieldInstance as ManyToManyFieldInstance
from tortoise.fields.relational import ManyToManyRelation as ManyToManyRelation
from tortoise.fields.relational import OneToOneField as OneToOneField
from tortoise.fields.relational import OneToOneFieldInstance as OneToOneFieldInstance
from tortoise.fields.relational import OneToOneNullableRelation as OneToOneNullableRelation
from tortoise.fields.relational import OneToOneRelation as OneToOneRelation
from tortoise.fields.relational import ReverseRelation as ReverseRelation

from dipdup.exceptions import FrameworkException
from dipdup.utils import json_dumps_plain

if TYPE_CHECKING:
    from tortoise.models import Model as _TortoiseModel

IntEnumField = IntEnumFieldInstance
ForeignKeyField = ForeignKeyFieldInstance
ManyToManyField = ManyToManyFieldInstance

_EnumFieldT = TypeVar('_EnumFieldT', bound=Enum)


JSONField = partial(
    _JSONField[Any],
    encoder=json_dumps_plain,
    decoder=orjson.loads,
)


class EnumField(Field[_EnumFieldT]):
    """Like CharEnumField but without max_size and additional validation"""

    indexable = True
    SQL_TYPE = 'TEXT'

    def __init__(
        self,
        enum_type: type[_EnumFieldT],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.enum_type = enum_type

    def to_db_value(
        self,
        value: Enum | str | None,
        instance: type[_TortoiseModel] | _TortoiseModel,
    ) -> str | None:
        if isinstance(value, self.enum_type):
            return value.value  # type: ignore[no-any-return]
        if isinstance(value, str):
            return value
        if value is None:
            return None
        raise FrameworkException(f'Invalid enum value: {value}')

    def to_python_value(
        self,
        value: Enum | str | None,
    ) -> Enum | None:
        if isinstance(value, str):
            return self.enum_type(value)
        if isinstance(value, self.enum_type):
            return value
        if value is None:
            return None
        raise FrameworkException(f'Invalid enum value: {value}')


class DecimalField(Field[Decimal], Decimal):
    """
    Accurate decimal field.

    You must provide the following:

    ``max_digits`` (int):
        Max digits of significance of the decimal field.
    ``decimal_places`` (int):
        How many of those significant digits is after the decimal point.
    """

    skip_to_python_if_native = True

    def __init__(self, max_digits: int, decimal_places: int, **kwargs: Any) -> None:
        if int(max_digits) < 1:
            raise TortoiseConfigurationError("'max_digits' must be >= 1")
        if int(decimal_places) < 0:
            raise TortoiseConfigurationError("'decimal_places' must be >= 0")
        super().__init__(**kwargs)
        self.max_digits = max_digits
        self.decimal_places = decimal_places
        self.quant = Decimal('1' if decimal_places == 0 else f'1.{("0" * decimal_places)}')

    def to_python_value(self, value: Any) -> Decimal | None:
        if value is not None:
            value = Decimal(value).quantize(self.quant).normalize()
        self.validate(value)
        return value  # type: ignore[no-any-return]

    @property
    def SQL_TYPE(self) -> str:  # type: ignore[override]
        return f'DECIMAL({self.max_digits},{self.decimal_places})'

    # class _db_sqlite:
    #     SQL_TYPE = 'VARCHAR(40)'

    #     def function_cast(self, term: Term) -> Term:
    #         return functions.Cast(term, SqlTypes.NUMERIC)


# NOTE: Tortoise forbids db_index=True on TextField, and shows warning when it's pk=True. We only support SQLite and
# PostgreSQL and have no plans for others. For SQLite, there's only TEXT type. For PosrgreSQL, there's no difference
# between TEXT and VARCHAR except for length constraint. So we can safely use TEXT for both to avoid schema changes.
class TextField(Field[str], str):  # type: ignore[misc]
    """
    Large Text field.
    """

    indexable = True
    SQL_TYPE = 'TEXT'


# NOTE: Finally, attach processed fields back to `tortoise.fields` to verify them later
# in `validate_models`. Also it magically fixes incorrect imports if any.
import tortoise.fields

for name, item in copy(locals()).items():
    setattr(tortoise.fields, name, item)
    with suppress(Exception):
        item.__module__ = __name__

# NOTE: Don't try any of the above at home, kids. See you in the next episode!
