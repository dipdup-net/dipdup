import asyncio
import importlib
import logging
import pkgutil
import re
import types
from collections import defaultdict
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from decimal import Decimal
from functools import reduce
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import TextIO
from typing import TypeVar

import orjson
from humps import main as humps
from pydantic import BaseModel
from pydantic import ValidationError

from dipdup.exceptions import FrameworkException
from dipdup.exceptions import InvalidDataError
from dipdup.exceptions import ProjectImportError

ObjectT = TypeVar('ObjectT', bound=BaseModel)

_logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from jinja2 import Template


def load_template(*path: str) -> 'Template':
    """Load template from path relative to dipdup package"""
    from jinja2 import Template

    full_path = Path(__file__).parent.joinpath(*path)
    return Template(full_path.read_text())


def touch(path: Path) -> None:
    """Create empty file, ignore if already exists"""
    if not path.parent.exists():
        _logger.info('Creating directory `%s`', path.parent)
        path.parent.mkdir(parents=True, exist_ok=True)

    if not path.is_file():
        _logger.info('Creating file `%s`', path)
        path.touch()


def write(path: Path, content: str | bytes, overwrite: bool = False, silent: bool = False) -> bool:
    """Write content to file, create directory tree if necessary"""
    _log = _logger.debug if silent else _logger.info
    if not path.parent.exists():
        _log('Creating directory `%s`', path.parent)
        path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not overwrite:
        return False

    _log('Writing into file `%s`', path)
    if isinstance(content, str):
        content = content.encode()
    path.write_bytes(content)
    return True


def import_submodules(package: str) -> dict[str, types.ModuleType]:
    """Recursively import all submodules of a package"""
    module = importlib.import_module(package)
    results = {}

    # NOTE: The first level; walk_packages falls into recursion with root symlink.
    if '.' not in package:
        raise FrameworkException("Don't use `import_submodules` for top-level package")

    for subpackage in pkgutil.walk_packages(module.__path__):
        name = subpackage.name
        is_pkg = subpackage.ispkg
        full_name = package + '.' + name
        results[full_name] = importlib.import_module(full_name)
        if is_pkg:
            results.update(import_submodules(full_name))
    return results


def snake_to_pascal(value: str) -> str:
    """humps wrapper for Python imports"""
    value = value.replace('.', '_')
    # NOTE: Special case, humps returns uppercase otherwise
    if value.isupper():
        value = value.lower()
    return humps.pascalize(value)


def pascal_to_snake(value: str, strip_dots: bool = True) -> str:
    """humps wrapper for Python imports"""
    if strip_dots:
        value = value.replace('.', '_')
    # NOTE: Special case, humps returns uppercase otherwise
    if value.isupper():
        value = value.lower()
    return humps.depascalize(value).replace('__', '_')


def split_by_chunks(input_: list[Any], size: int) -> Iterator[list[Any]]:
    i = 0
    while i < len(input_):
        yield input_[i : i + size]
        i += size


_T = TypeVar('_T')
_TT = TypeVar('_TT')


def groupby(seq: Sequence[_T], key: Callable[[Any], _TT]) -> defaultdict[_TT, list[_T]]:
    """Group by key into defaultdict"""
    return reduce(
        lambda grp, val: grp[key(val)].append(val) or grp,  # type: ignore[func-returns-value]
        seq,
        defaultdict(list),
    )


class FormattedLogger(Logger):
    """Logger wrapper with additional formatting"""

    def __init__(self, name: str, fmt: str | None = None) -> None:
        self.logger = logging.getLogger(name)
        self.fmt = fmt

    def __getattr__(self, name: str) -> Any:
        if name == '_log':
            return self._log
        return getattr(self.logger, name)

    def _log(
        self,
        level: int,
        msg: object,
        args: Any,
        exc_info: (
            None
            | bool
            | tuple[type[BaseException], BaseException, types.TracebackType | None]
            | tuple[None, None, None]
            | BaseException
            | None
        ) = None,
        extra: Mapping[str, Any] | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
    ) -> None:
        if self.fmt:
            msg = self.fmt.format(msg)
        self.logger._log(level, msg, args, exc_info, extra, stack_info, stacklevel)


def iter_files(path: Path, ext: str | None = None) -> Iterator[TextIO]:
    """Iterate over files in a directory. Or a single file. Sort alphabetically, filter by extension, skip empty files."""
    if not path.exists() and ext:
        path = Path(f'{path}{ext}')
    if not path.exists():
        return
    elif path.is_file():
        paths = [path]
    elif path.is_dir():
        paths = sorted(path.glob('**/*'))
    else:
        raise FrameworkException(f'Path `{path}` exists but is neither a file nor a directory')

    for path in paths:
        if ext and path.suffix != ext:
            continue
        if not path.exists():
            continue
        if not path.stat().st_size:
            continue
        with path.open() as file:
            yield file


def import_from(module: str, obj: str) -> Any:
    """Import object from module, raise ProjectImportError on failure"""
    try:
        return getattr(importlib.import_module(module), obj)
    except (ImportError, AttributeError) as e:
        raise ProjectImportError(module, obj) from e


def parse_object(
    type_: type[ObjectT],
    data: Mapping[str, Any] | Sequence[Any] | None,
    plain: bool = False,
    nested: bool = False,
) -> ObjectT:
    try:
        if plain is False or data is None:
            return type_.model_validate(data)

        model_keys = tuple(field.alias or key for key, field in type_.model_fields.items())
        model_dict = dict(zip(model_keys, data, strict=True))

        if nested:
            for k, v in model_dict.items():
                if not isinstance(v, list | tuple):
                    continue

                # NOTE: Might be `from_` or other reserved keyword
                field_k = '{k}_ ' if k not in type_.model_fields else k
                nested_type = type_.model_fields[field_k].annotation
                model_dict[k] = parse_object(nested_type, v, plain=True)  # type: ignore[arg-type]

        return type_(**model_dict)
    except ValidationError as e:
        raise InvalidDataError(f'Failed to parse: {e.errors()}', type_, data) from e
    except ValueError as e:
        raise InvalidDataError(f'Failed to parse: {e}', type_, data) from e


def _default_for_decimals(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError


def json_dumps(obj: Any | str, option: int | None = orjson.OPT_INDENT_2) -> bytes:
    """Smarter json.dumps"""
    return orjson.dumps(
        obj,
        default=_default_for_decimals,
        option=option,
    )


def json_dumps_plain(obj: Any | str) -> str:
    return json_dumps(obj, None).decode()


class Watchdog:
    def __init__(self, timeout: int) -> None:
        self._watchdog = asyncio.Event()
        self._timeout = timeout

    def reset(self) -> None:
        self._watchdog.set()
        self._watchdog.clear()

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._timeout)
            try:
                await asyncio.wait_for(
                    self._watchdog.wait(),
                    timeout=self._timeout,
                )
            except TimeoutError as e:
                msg = f'Watchdog timeout; no messages received in {self._timeout} seconds'
                raise FrameworkException(msg) from e


def sorted_glob(path: Path, pattern: str) -> list[Path]:
    def natural_sort_key(item: Path) -> Any:
        def split_parts(text: str) -> list[int | str]:
            parts = re.split(r'(\d+)', text)
            return [int(part) if part.isdigit() else part.lower() for part in parts]

        # Sort by parent directories first, then by filename
        return [split_parts(part) for part in item.parent.parts], split_parts(item.name)

    return sorted(path.glob(pattern), key=natural_sort_key)
