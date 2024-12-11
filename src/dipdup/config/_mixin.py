from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from collections import Counter
from pydoc import locate
from typing import TYPE_CHECKING
from typing import Any
from typing import Generic
from typing import TypeVar
from typing import cast

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from dipdup.exceptions import ConfigInitializationException
from dipdup.exceptions import ConfigurationError
from dipdup.utils import pascal_to_snake

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class NameMixin:
    def __post_init__(self) -> None:
        self._name: str | None = None

    @property
    def name(self) -> str:
        if self._name is None:
            raise ConfigInitializationException(f'{self.__class__.__name__} name is not set')
        return self._name


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class CodegenMixin(ABC):
    """Base for pattern config classes containing methods required for codegen"""

    @abstractmethod
    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]: ...

    @abstractmethod
    def iter_arguments(self) -> Iterator[tuple[str, str]]: ...

    def format_imports(self, package: str) -> Iterator[str]:
        for package_name, cls in self.iter_imports(package):
            yield f'from {package_name} import {cls}'

    def format_arguments(self) -> Iterator[str]:
        arguments = list(self.iter_arguments())
        i, counter = 0, Counter(name for name, _ in arguments)

        for name, cls in arguments:
            if counter[name] > 1:
                yield f'{name}_{i}: {cls}'
                i += 1
            else:
                yield f'{name}: {cls}'

    def locate_arguments(self) -> dict[str, type | None]:
        """Try to resolve scope annotations for arguments"""
        kwargs: dict[str, type[Any] | None] = {}
        for name, cls in self.iter_arguments():
            cls = cls.split(' as ')[0]
            kwargs[name] = cast(type | None, locate(cls))
        return kwargs


ParentT = TypeVar('ParentT')


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class ParentMixin(Generic[ParentT]):
    """`parent` field for index and template configs"""

    def __post_init__(self: ParentMixin[ParentT]) -> None:
        self._parent: ParentT | None = None

    @property
    def parent(self) -> ParentT:
        if not self._parent:
            raise ConfigInitializationException(f'{self.__class__.__name__} parent is not set')
        return self._parent

    @parent.setter
    def parent(self, value: ParentT) -> None:
        self._parent = value


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class CallbackMixin(CodegenMixin):
    """Mixin for callback configs

    :param callback: Callback name
    """

    callback: str

    def __post_init__(self) -> None:
        if self.callback and self.callback != pascal_to_snake(self.callback, strip_dots=False):
            raise ConfigurationError('`callback` field must be a valid Python module name')


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SubgroupIndexMixin:
    """`subgroup_index` field to track index of operation in group

    :param subgroup_index:
    """

    def __post_init__(self) -> None:
        self._subgroup_index: int | None = None

    @property
    def subgroup_index(self) -> int:
        if self._subgroup_index is None:
            raise ConfigInitializationException
        return self._subgroup_index

    @subgroup_index.setter
    def subgroup_index(self, value: int) -> None:
        self._subgroup_index = value
