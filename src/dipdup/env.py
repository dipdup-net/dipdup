import importlib
import importlib.util
import platform
import sys
import tomllib
from contextlib import suppress
from functools import cache
from os import getenv
from pathlib import Path

from dipdup.exceptions import FrameworkException


def dump() -> dict[str, str]:
    result: dict[str, str] = {}
    for key in globals().keys():
        if key.isupper():
            result[key] = getenv(f'DIPDUP_{key}') or ''
    return result


def get_pyproject_name() -> str | None:
    pyproject_path = Path('pyproject.toml')
    if not pyproject_path.exists():
        return None

    content = tomllib.loads(pyproject_path.read_text())
    if 'project' in content:
        return str(content['project']['name'])
    if 'tool' in content and 'poetry' in content['tool']:
        return str(content['tool']['poetry']['name'])
    raise FrameworkException('`pyproject.toml` found, but has neither `project` nor `tool.poetry` section')


@cache
def get_package_path(package: str) -> Path:
    """Absolute path to the indexer package, existing or default"""

    if PACKAGE_PATH:
        spec = importlib.util.spec_from_file_location(package, PACKAGE_PATH / '__init__.py')
        if spec is None:
            raise ImportError(f'Failed to import `{package}` package from `{PACKAGE_PATH}`')
        module = importlib.util.module_from_spec(spec)
        sys.modules[package] = module
        if spec.loader is None:
            raise ImportError(f'Failed to import `{package}` package from `{PACKAGE_PATH}`')
        spec.loader.exec_module(module)
        return PACKAGE_PATH

    # NOTE: Integration tests run in isolated environment
    if TEST:
        return Path.cwd() / package

    # NOTE: If cwd is a package, use it
    if package in {get_pyproject_name(), Path.cwd().name}:
        return Path.cwd()

    # NOTE: Detect existing package in current environment
    with suppress(ImportError):
        module = importlib.import_module(package)
        if module.__file__ is None:
            raise ImportError(f'`{module.__name__}` package has no `__file__` attribute')
        return Path(module.__file__).parent

    # NOTE: Create a new package
    return Path.cwd() / package


def get_bool(key: str) -> bool:
    return (getenv(key) or '').lower() in ('1', 'y', 'yes', 't', 'true', 'on')


def get_int(key: str, default: int) -> int:
    return int(getenv(key) or default)


def get_path(key: str) -> Path | None:
    value = getenv(key)
    if value is None:
        return None
    return Path(value)


def reload_env() -> None:
    global CI, DEBUG, DOCKER, JSON_LOG, LOW_MEMORY, MIGRATIONS, NEXT, NO_SYMLINK, NO_VERSION_CHECK, PACKAGE_PATH, REPLAY_PATH, TEST

    CI = get_bool('DIPDUP_CI')
    DEBUG = get_bool('DIPDUP_DEBUG')
    DOCKER = get_bool('DIPDUP_DOCKER')
    JSON_LOG = get_bool('DIPDUP_JSON_LOG')
    LOW_MEMORY = get_bool('DIPDUP_LOW_MEMORY')
    MIGRATIONS = get_bool('DIPDUP_MIGRATIONS')
    NEXT = get_bool('DIPDUP_NEXT')
    NO_SYMLINK = get_bool('DIPDUP_NO_SYMLINK')
    NO_VERSION_CHECK = get_bool('DIPDUP_NO_VERSION_CHECK')
    PACKAGE_PATH = get_path('DIPDUP_PACKAGE_PATH')
    REPLAY_PATH = get_path('DIPDUP_REPLAY_PATH')
    TEST = get_bool('DIPDUP_TEST')


def set_test() -> None:
    global TEST, REPLAY_PATH
    TEST = True
    REPLAY_PATH = Path(__file__).parent.parent.parent / 'tests' / 'replays'


CI: bool = get_bool('DIPDUP_CI')
DEBUG: bool = get_bool('DIPDUP_DEBUG')
DOCKER: bool = get_bool('DIPDUP_DOCKER')
JSON_LOG: bool = get_bool('DIPDUP_JSON_LOG')
LOW_MEMORY: bool = get_bool('DIPDUP_LOW_MEMORY')
MIGRATIONS: bool = get_bool('DIPDUP_MIGRATIONS')
NEXT: bool = get_bool('DIPDUP_NEXT')
NO_SYMLINK: bool = get_bool('DIPDUP_NO_SYMLINK')
NO_VERSION_CHECK: bool = get_bool('DIPDUP_NO_VERSION_CHECK')
PACKAGE_PATH: Path | None = get_path('DIPDUP_PACKAGE_PATH')
REPLAY_PATH: Path | None = get_path('DIPDUP_REPLAY_PATH')
TEST: bool = get_bool('DIPDUP_TEST')

if getenv('CI') == 'true':
    CI = True
if platform.system() == 'Linux' and Path('/.dockerenv').exists():
    DOCKER = True
