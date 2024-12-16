"""This module contains code to manage queues, caches and tune metrics.

There are three module-level singletons, one for each type of resource:

- `_QueueManager` for simple deque queues
- `_CacheManager` for LRU caches
- `_MetricManager` for performance/prometheus metrics and pprofile integration

These three need to be importable from anywhere, so no internal imports in this module.
"""

import gc
import logging
from collections import deque
from collections.abc import Callable
from collections.abc import Coroutine
from functools import _CacheInfo
from functools import lru_cache
from itertools import chain
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dipdup.exceptions import FrameworkException
from dipdup.prometheus import Counter
from dipdup.prometheus import Gauge
from dipdup.prometheus import Histogram
from dipdup.prometheus import Metric

if TYPE_CHECKING:

    from dipdup.models import CachedModel

_logger = logging.getLogger(__name__)


class _CacheManager:
    def __init__(self) -> None:
        self._plain: dict[str, dict[Any, Any]] = {}
        self._lru: dict[str, Callable[..., Any]] = {}
        self._alru: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}
        self._models: set[type[CachedModel]] = set()

    def add_plain(
        self,
        obj: dict[Any, Any],
        name: str,
    ) -> None:
        self._plain[name] = obj

    def add_lru(
        self,
        fn: Callable[..., Any],
        maxsize: int | None,
        name: str | None = None,
    ) -> Callable[..., Any]:
        if name is None:
            name = f'{fn.__module__}.{fn.__name__}:{id(fn)}'
        if name in self._lru or name in self._alru:
            raise FrameworkException(f'LRU cache `{name}` already exists')

        self._lru[name] = lru_cache(maxsize)(fn)
        return self._lru[name]

    def add_alru(
        self,
        fn: Callable[..., Coroutine[Any, Any, None]],
        maxsize: int,
        name: str | None = None,
    ) -> Callable[..., Coroutine[Any, Any, None]]:
        from async_lru import alru_cache

        if name is None:
            name = f'{fn.__module__}.{fn.__name__}:{id(fn)}'
        if name in self._lru or name in self._alru:
            raise FrameworkException(f'LRU cache `{name}` already exists')

        self._alru[name] = alru_cache(maxsize)(fn)
        return self._alru[name]

    def add_model(
        self,
        cls: 'type[CachedModel]',
    ) -> None:
        if cls in self._models:
            raise FrameworkException(f'Model cache for `{cls}` already exists')
        self._models.add(cls)

    def stats(self) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        for name, plain_cache in self._plain.items():
            name = f'plain:{name}'
            stats[name] = {'size': len(plain_cache)}
        for name, fn_cache in chain(self._lru.items(), self._alru.items()):
            name = f'lru:{name}'
            c = cast(_CacheInfo, fn_cache.cache_info())  # type: ignore[attr-defined]
            if not c.hits and not c.misses:
                continue
            stats[name] = {
                'hits': c.hits,
                'misses': c.misses,
                'size': c.currsize,
                'limit': c.maxsize,
                'full': (c.currsize / c.maxsize) if c.maxsize else 0,
                'hit_rate': c.hits / (c.hits + c.misses),
            }
        for model_cls in self._models:
            name = f'model:{model_cls.__name__}'
            stats[name] = model_cls.stats()

        return stats

    def clear(self) -> None:
        items = 0

        for plain_cache in self._plain.values():
            items += len(plain_cache)
            plain_cache.clear()
        for fn_cache in chain(self._lru.values(), self._alru.values()):
            stats = cast(_CacheInfo, fn_cache.cache_info())  # type: ignore[attr-defined]
            items += stats.currsize
            fn_cache.cache_clear()  # type: ignore[attr-defined]
        for model_cls in self._models:
            items += model_cls.stats()['size']
            model_cls.clear()

        _logger.debug('Cleared %d cached items', items)

        collected = gc.collect()
        _logger.debug('Garbage collected %d items', collected)


class _QueueManager:
    def __init__(self) -> None:
        self._queues: dict[str, deque[Any]] = {}
        self._limits: dict[str, int] = {}

    def add_queue(
        self,
        queue: deque[Any],
        name: str,
        limit: int = 0,
    ) -> None:
        if name in self._queues:
            raise FrameworkException(f'Queue `{name}` already exists')
        self._queues[name] = queue
        self._limits[name] = limit

    def remove_queue(self, name: str) -> None:
        if name not in self._queues:
            raise FrameworkException(f'Queue `{name}` does not exist')
        del self._queues[name]
        del self._limits[name]

    def stats(self) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        for name, queue in self._queues.items():
            size = len(queue)
            soft_limit = self._limits[name]
            if soft_limit:
                stats[name] = {
                    'size': size,
                    'limit': soft_limit,
                    'full': size / soft_limit,
                }
            elif queue.maxlen:
                stats[name] = {
                    'size': size,
                    'limit': queue.maxlen,
                    'full': size / queue.maxlen,
                }
            else:
                stats[name] = {
                    'size': size,
                    'limit': None,
                    'full': None,
                }
        return stats


class _MetricManager:
    # NOTE: Some metrics types are unions with int and float to make mypy happy
    # NOTE: If you want your metric to be part of the stats, it should not be private (start with _)
    # and should have explicit type annotation

    # NOTE: General metrics
    levels_indexed: Gauge | int = Gauge('dipdup_levels_indexed_total', 'Total number of levels indexed')
    levels_nonempty: Counter = Counter('dipdup_levels_nonempty_total', 'Total number of nonempty levels indexed')
    levels_total: Gauge | int = Gauge('dipdup_levels_total', 'Total number of levels')
    objects_indexed: Counter = Counter('dipdup_objects_indexed_total', 'Total number of objects indexed')

    # NOTE: Index metrics
    handlers_matched: Counter = Counter('dipdup_index_handlers_matched_total', 'Index total hits', ['handler'])
    time_in_matcher: Histogram = Histogram('dipdup_index_time_in_matcher_seconds', 'Time spent in matcher', ['index'])
    time_in_callbacks: Histogram = Histogram(
        'dipdup_index_time_in_callbacks_seconds', 'Time spent in callbacks', ['index']
    )

    # NOTE: Datasource metrics
    time_in_requests: Histogram = Histogram(
        'dipdup_datasource_time_in_requests_seconds', 'Time spent in datasource requests', ['datasource']
    )
    requests_total: Counter = Counter(
        'dipdup_datasource_requests_total', 'Total number of datasource requests', ['datasource']
    )

    # NOTE: Various timestamps
    started_at: Gauge | float = Gauge('dipdup_started_at_timestamp', 'Timestamp of the DipDup start')
    synchronized_at: Gauge | float = Gauge('dipdup_synchronized_at_timestamp', 'Timestamp of the last synchronization')
    realtime_at: Gauge | float = Gauge('dipdup_realtime_at_timestamp', 'Timestamp of the last realtime update')
    metrics_updated_at: Gauge | float = Gauge(
        'dipdup_metrics_updated_at_timestamp', 'Timestamp of the last metrics update'
    )

    # NOTE: Speed estimates
    levels_speed: Gauge | float = Gauge('dipdup_levels_speed', 'Levels per second')
    levels_speed_average: Gauge | float = Gauge('dipdup_levels_speed_average', 'Average levels per second')
    levels_nonempty_speed: Gauge | float = Gauge('dipdup_levels_nonempty_speed', 'Nonempty levels per second')
    objects_speed: Gauge | float = Gauge('dipdup_objects_speed', 'Objects per second')

    # NOTE: Time estimates
    time_passed: Gauge | float = Gauge('dipdup_time_passed_seconds', 'Time passed since the start')
    time_left: Gauge | float = Gauge('dipdup_time_left_seconds', 'Time left estimated until the end')
    progress: Gauge | float = Gauge('dipdup_progress', 'Progress in percents')

    # NOTE: Orignally in prometheus.py
    _indexes_total = Gauge(
        'dipdup_indexes_total',
        'Number of indexes in operation by status',
        ('status',),
    )
    _levels_to_sync: Histogram = Histogram(
        'dipdup_index_levels_to_sync_total',
        'Number of levels to reach synced state',
        ['index'],
    )
    _levels_to_realtime: Histogram = Histogram(
        'dipdup_index_levels_to_realtime_total',
        'Number of levels to reach realtime state',
        ['index'],
    )

    _index_total_sync_duration: Histogram = Histogram(
        'dipdup_index_total_sync_duration_seconds',
        'Duration of the last index syncronization',
    )
    _index_total_realtime_duration: Histogram = Histogram(
        'dipdup_index_total_realtime_duration_seconds',
        'Duration of the last index realtime syncronization',
    )

    _datasource_head_updated = Gauge(
        'dipdup_datasource_head_updated_timestamp',
        'Timestamp of the last head update',
        ['datasource'],
    )
    _datasource_rollbacks = Counter(
        'dipdup_datasource_rollbacks_total',
        'Number of rollbacks',
        ['datasource'],
    )

    _http_errors = Counter(
        'dipdup_http_errors_total',
        'Number of http errors',
        ['url', 'status'],
    )
    _http_errors_in_row = Gauge(
        'dipdup_http_errors_in_row',
        'Number of consecutive failed requests',
    )

    _sqd_processor_last_block: Gauge | int = Gauge(
        'sqd_processor_last_block',
        'Level of the last processed block from Subsquid Network',
    )
    _sqd_processor_chain_height = Gauge(
        'sqd_processor_chain_height',
        'Current chain height as reported by Subsquid Network',
    )
    _sqd_processor_archive_http_errors_in_row = Gauge(
        'sqd_processor_archive_http_errors_in_row',
        'Number of consecutive failed requests to Subsquid Network',
    )

    def __setattr__(self, name: str, value: int | float | Counter | Gauge | Histogram) -> None:
        """Custom attribute setter for the class, it only affects Counter, Gauge and Histogram attributes,
        falling back to the default behavior for the rest.

        This method makes it possible to assign int and float values to Gauge and Histogram attributes,
        calling `set` and `observe` methods respectively and raises an error when trying to assign:
            - any value to a Counter attribute
            - any value to a parent Gauge or Histogram attribute
            - other than int or float or Gauge to a Gauge attribute, same for Histogram
        """
        attr = getattr(self, name)

        # If both are Counters, it's probably coming from a += operation, se we accept it
        if isinstance(attr, Counter) and not isinstance(value, Counter):
            raise TypeError('Counters can only be incremented, use the += operator or the `inc` method instead')

        if isinstance(attr, Gauge):
            if attr._is_parent():
                raise TypeError('Cannot assign to parent Gauge, use metric["label"] = value instead')

            if isinstance(value, int | float):
                attr.set(value)
                return

            if not isinstance(value, Gauge):
                raise TypeError(f'Cannot assign {type(value)} to Gauge, only int and float are allowed')

        if isinstance(attr, Histogram):
            if attr._is_parent():
                raise TypeError('Cannot assign to parent Histogram, use metric["label"] = value instead')

            if isinstance(value, int | float):
                attr.observe(value)
                return

            if not isinstance(value, Histogram):
                raise TypeError(f'Cannot assign {type(value)} to Histogram, only int and float are allowed')

        super().__setattr__(name, value)

    def set_http_error(self, url: str, status: int) -> None:
        self._http_errors.labels(url=url, status=status).inc()

    def set_http_errors_in_row(self, url: str, errors_count: int) -> None:
        self._http_errors_in_row.inc(errors_count)
        if 'subsquid' in url:
            self._sqd_processor_archive_http_errors_in_row.inc(errors_count)

    def stats(self) -> dict[str, Any]:
        def _round(value: Any) -> Any:
            if isinstance(value, Metric):
                return _round(value.value)
            if isinstance(value, dict):
                return {k: _round(v) for k, v in value.items()}
            if isinstance(value, float):
                return round(value, 2)
            return value

        return {
            k: _round(getattr(self, k))
            for k in dir(self)
            if not k.startswith('_') and isinstance(getattr(self, k), Metric)
        }


caches = _CacheManager()
queues = _QueueManager()
metrics = _MetricManager()


def get_stats() -> dict[str, Any]:
    return {
        'caches': caches.stats(),
        'queues': queues.stats(),
        'metrics': metrics.stats(),
    }
