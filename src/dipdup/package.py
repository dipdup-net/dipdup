import logging
from collections import deque
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Generator
from pathlib import Path
from typing import Any
from typing import cast

import appdirs  # type: ignore[import-untyped]
from pydantic import BaseModel

from dipdup import env
from dipdup.abi.cairo import CairoAbiManager
from dipdup.abi.evm import EvmAbiManager
from dipdup.exceptions import ProjectPackageError
from dipdup.project import Answers
from dipdup.project import answers_from_replay
from dipdup.project import get_default_answers
from dipdup.utils import import_from
from dipdup.utils import import_submodules
from dipdup.utils import pascal_to_snake
from dipdup.utils import touch

KEEP_MARKER = '.keep'
PACKAGE_MARKER = '__init__.py'
PEP_561_MARKER = 'py.typed'
DEFAULT_ENV = '.env.default'


EVM_ABI_JSON = 'abi.json'
CAIRO_ABI_JSON = 'cairo_abi.json'

_branch = '│   '
_tee = '├── '
_last = '└── '

_logger = logging.getLogger(__name__)


def _get_pointers(content_length: int) -> tuple[str, ...]:
    return (_tee,) * (content_length - 1) + (_last,)


def draw_package_tree(root: Path, project_tree: dict[str, tuple[Path, ...]]) -> tuple[str, ...]:
    lines: deque[str] = deque()
    pointers = _get_pointers(len(project_tree) - 1)
    for pointer, (section, paths) in zip(pointers, project_tree.items(), strict=False):
        lines.append(pointer + section)
        for inner_pointer, path in zip(_get_pointers(len(paths)), sorted(paths), strict=False):
            relative_path = path.relative_to(root / section)
            lines.append(_branch + inner_pointer + relative_path.as_posix())

    return tuple(lines)


class DipDupPackage:
    def __init__(self, root: Path, quiet: bool = False) -> None:
        _log = _logger.debug if quiet else _logger.info
        _log('Loading package `%s` from `%s`', root.name, root)

        self.root = root
        self.name = root.name

        # NOTE: Package sections with .keep markers
        self.abi = root / 'abi'
        self.configs = root / 'configs'
        self.deploy = root / 'deploy'
        self.graphql = root / 'graphql'
        self.handlers = root / 'handlers'
        self.hasura = root / 'hasura'
        self.hooks = root / 'hooks'
        self.models = root / 'models'
        self.sql = root / 'sql'
        self.types = root / 'types'
        # NOTE: Optional, created if aerich is installed
        self.migrations = root / 'migrations'

        # NOTE: Shared directories; not a part of package
        self._xdg_shared_dir = Path(appdirs.user_data_dir('dipdup'))
        self.schemas = self._xdg_shared_dir / 'schemas' / self.name
        # NOTE: ABIs required for codegen, but not in runtime
        self.abi_local = self._xdg_shared_dir / 'abi' / self.name

        # NOTE: Finally, internal in-memory stuff
        self._replay: Answers | None = None
        self._callbacks: dict[str, Callable[..., Awaitable[Any]]] = {}
        self._types: dict[str, type[BaseModel]] = {}
        self._evm_abis = EvmAbiManager(self)
        self._cairo_abis = CairoAbiManager(self)

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self.root})'

    @property
    def cairo_abi_paths(self) -> Generator[Any, None, None]:
        return self.abi.glob(f'**/{CAIRO_ABI_JSON}')

    @property
    def evm_abi_paths(self) -> Generator[Any, None, None]:
        return self.abi.glob(f'**/{EVM_ABI_JSON}')

    @property
    def replay_path(self) -> Path:
        return self.root / 'configs' / 'replay.yaml'

    @property
    def replay(self) -> Answers:
        if self.replay_path.exists():
            return answers_from_replay(self.replay_path)
        return get_default_answers()

    @property
    def skel(self) -> dict[Path, str | None]:
        return {
            # NOTE: Package sections
            self.abi: '**/*.json',
            self.configs: '**/*.y[a]ml',
            self.deploy: '**/*[Dockerfile|.env.default|yml|yaml]',
            self.graphql: '**/*.graphql',
            self.handlers: '**/*.py',
            self.hasura: '**/*.json',
            self.hooks: '**/*.py',
            self.models: '**/*.py',
            self.sql: '**/*.sql',
            self.types: '**/*.py',
            # NOTE: Python metadata
            Path(PEP_561_MARKER): None,
            Path(PACKAGE_MARKER): None,
        }

    def in_migration(self) -> bool:
        for path in self.root.iterdir():
            if path.name.endswith('.old'):
                return True
        return False

    def tree(self) -> dict[str, tuple[Path, ...]]:
        tree = {}
        for path, exp in self.skel.items():
            tree[path.name] = tuple(path.glob(exp)) if exp else ()
        return tree

    def initialize(self) -> None:
        """Create Python package skeleton if not exists"""
        self._pre_init()

        _logger.debug('Updating `%s` package structure', self.name)
        for path, glob in self.skel.items():
            if glob:
                touch(path / KEEP_MARKER)
            else:
                touch(self.root / path)

        self._post_init()

    def load_abis(self) -> None:
        self._evm_abis.load()
        self._cairo_abis.load()

    def _pre_init(self) -> None:
        if self.name != pascal_to_snake(self.name):
            raise ProjectPackageError(f'`{self.name}` is not a valid Python package name')
        if self.root.exists() and not self.root.is_dir():
            raise ProjectPackageError(f'`{self.root}` exists and not a directory')

    def _post_init(self) -> None:
        # NOTE: Allows plain package structure to be imported
        if self.root != Path.cwd() or env.NO_SYMLINK:
            return

        symlink_path = self.root.joinpath(self.name)
        if symlink_path.exists() and not symlink_path.is_symlink():
            raise ProjectPackageError(f'`{symlink_path}` exists and not a symlink')
        if not symlink_path.exists():
            symlink_path.symlink_to('.', True)

    def verify(self) -> None:
        _logger.debug('Verifying `%s` package', self.root)
        import_submodules(f'{self.name}.handlers')
        import_submodules(f'{self.name}.hooks')
        import_submodules(f'{self.name}.types')

    def get_type(self, typename: str, module: str, name: str) -> type[BaseModel]:
        key = f'{typename}{module}{name}'
        if (type_ := self._types.get(key)) is None:
            path = f'{self.name}.types.{typename}.{module}'
            type_ = import_from(path, name)
            if not isinstance(type_, type):
                raise ProjectPackageError(f'`{path}.{name}` is not a valid type')
            self._types[key] = type_
        return type_

    def get_callback(self, kind: str, module: str, name: str) -> Callable[..., Awaitable[None]]:
        key = f'{kind}{module}{name}'
        if (callback := self._callbacks.get(key)) is None:
            path = f'{self.name}.{kind}.{module}'
            callback = import_from(path, name)
            if not callable(callback):
                raise ProjectPackageError(f'`{path}.{name}` is not a valid callback')
            self._callbacks[key] = callback
        return cast(Callable[..., Awaitable[None]], callback)
