from contextlib import suppress
from functools import lru_cache
from itertools import groupby
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Type
from typing import Union

from pydantic.error_wrappers import ValidationError
from typing_extensions import get_args
from typing_extensions import get_origin

from dipdup.exceptions import ConfigurationError
from dipdup.exceptions import InvalidDataError
from dipdup.models import OperationData
from dipdup.models import StorageType

IntrospectionError = (KeyError, IndexError, AttributeError)


@lru_cache(None)
def _is_bigmap_list(storage_type: Type[Any]) -> bool:
    # NOTE: is List[Union[int, Dict]
    try:
        root_type = storage_type.__annotations__['__root__']
        return get_origin(get_args(get_args(root_type)[0])[1]) == dict
    except IntrospectionError:
        return False


@lru_cache(None)
def _is_array(storage_type: Type) -> bool:
    """TzKT can return bigmaps as objects or as arrays of key-value objects. Guess it from storage type."""
    try:
        fields = storage_type.__fields__
    # NOTE: Not a dataclass
    except AttributeError:
        return False

    # NOTE: TzKT array (dict actually)
    if 'key' in fields and 'value' in fields:
        return True

    # NOTE: Pydantic array
    try:
        return get_origin(get_args(getattr(fields.get('__root__'), 'type_', None))[1]) == list
    except IntrospectionError:
        return False


@lru_cache(None)
def _extract_field_type(field: Type) -> Type:
    """Get type of nested field keeping in mind Pydantic special cases"""
    if field.type_ == field.outer_type_:
        return field.type_

    # NOTE: `BaseModel.type_` returns incorrect value when annotation is Dict[str, bool], Dict[str, BaseModel], and possibly in some other cases.
    if field.type_ == bool:
        return field.outer_type_
    with suppress(*IntrospectionError):
        get_args(field.outer_type_)[1].__fields__
        return field.outer_type_

    return field.type_


@lru_cache(None)
def _extract_root_type(storage_type: Type[StorageType]) -> Type[StorageType]:
    return get_args(storage_type.__annotations__['__root__'])[0]


def _preprocess_bigmap_diffs(diffs: Iterable[Dict[str, Any]]) -> Dict[int, Iterable[Dict[str, Any]]]:
    """Filter out bigmap diffs and group them by bigmap id"""
    return {
        k: tuple(v)
        for k, v in groupby(
            filter(lambda d: d['action'] in ('add_key', 'update_key'), diffs),
            lambda d: d['bigmap'],
        )
    }


def _apply_bigmap_diffs(
    bigmap_id: int,
    bigmap_diffs: Dict[int, Iterable[Dict[str, Any]]],
    is_array: bool,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    storage: Union[List[Dict[str, Any]], Dict[str, Any]] = [] if is_array else {}
    for diff in bigmap_diffs.get(bigmap_id, ()):
        bigmap_key, bigmap_value = diff['content']['key'], diff['content']['value']
        if is_array:
            storage.append(  # type: ignore
                {
                    'key': bigmap_key,
                    'value': bigmap_value,
                }
            )
        else:
            storage[bigmap_key] = bigmap_value  # type: ignore

    return storage


def _process_storage(
    storage: Any,
    storage_type: Type[StorageType],
    bigmap_diffs: Dict[int, Iterable[Dict[str, Any]]],
) -> Any:
    # NOTE: Bigmap pointer, apply diffs
    if isinstance(storage, int):
        is_array = _is_array(storage_type)  # type: ignore
        storage = _apply_bigmap_diffs(storage, bigmap_diffs, is_array)

    # NOTE: List of something, apply diffs recursively if needed
    elif isinstance(storage, list):
        if _is_bigmap_list(storage_type):  # type: ignore
            for i, _ in enumerate(storage):
                storage[i] = _process_storage(storage[i], storage_type, bigmap_diffs)

    # NOTE: Regular dict, possibly nested: fire up introspection magic
    elif isinstance(storage, dict):

        for key, field in storage_type.__fields__.items():
            # NOTE: Plain Pydantic model, ignore
            if key == '__root__':
                continue

            # NOTE: Use field alias when present
            if field.alias:
                key = field.alias

            # NOTE: Ignore missing optional fields, raise on required
            value = storage.get(key)
            if value is None:
                if not field.required:
                    continue
                raise ConfigurationError(f'Type `{storage_type.__name__}` is invalid: `{key}` field does not exists')

            field_type = _extract_field_type(field)
            is_array = _is_array(field_type)  # type: ignore

            # NOTE: Bigmap, apply diffs
            # NOTE: bool is a possible Pydantic bug, see note in _extract_field_type
            if field_type not in (int, bool) and isinstance(value, int):
                storage[key] = _apply_bigmap_diffs(value, bigmap_diffs, is_array)

            # NOTE: Regular dict, process root type recursively
            elif hasattr(field_type, '__fields__') and isinstance(storage[key], dict):
                storage[key] = _process_storage(storage[key], field_type, bigmap_diffs)

            # NOTE: List of bigmaps, apply diffs recursively
            elif _is_bigmap_list(field_type):  # type: ignore
                storage_type = _extract_root_type(field_type)  # type: ignore
                for i, _ in enumerate(storage[key]):
                    storage[key][i] = _process_storage(storage[key][i], storage_type, bigmap_diffs)

            else:
                pass

    else:
        raise NotImplementedError

    return storage


def deserialize_storage(operation_data: OperationData, storage_type: Type[StorageType]) -> StorageType:
    """Merge big map diffs and deserialize raw storage into typeclass"""
    bigmap_diffs = _preprocess_bigmap_diffs(operation_data.diffs)

    operation_data.storage = _process_storage(
        storage=operation_data.storage,
        storage_type=storage_type,
        bigmap_diffs=bigmap_diffs,
    )

    try:
        return storage_type.parse_obj(operation_data.storage)
    except ValidationError as e:
        raise InvalidDataError(
            type_cls=storage_type,
            data=operation_data.storage,
            parsed_object=operation_data,
        ) from e
