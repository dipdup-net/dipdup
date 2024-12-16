"""This module provides a set of classes extending Prometheus metrics with additional functionality

The goal is to make the use of Prometheus metrics easier in DipDup, directly integrating them with the
existing `_MetricManager` class in the `dipdup.performance` module

The first goal was to be able to transform `_MetricManager`'s attributes into Prometheus metrics with as little changes as possible,
that's why we make it possible to perform arithmetic operations between metrics and/or numeric values and retrieve their values
easily with the `value` property for reporting

Don't worry if you don't understand the code in this module, all you need to know is that you can transform an attributes in
`_MetricManager` into a Prometheus metric or add a new metric by using one of the classes in this module, you can then interact
with the metric as if it was a regular numeric value
"""

from abc import abstractmethod
from typing import Any
from typing import Union

from prometheus_client import Counter as PrometheusCounter
from prometheus_client import Gauge as PrometheusGauge
from prometheus_client import Histogram as PrometheusHistogram
from prometheus_client.metrics import MetricWrapperBase


class Metric(MetricWrapperBase):
    """Base class for custom Prometheus metrics, providing common functions
    for arithmetic operations and value retrieval.
    """

    def __add__(self, other: Union[int, float, 'Metric']) -> float:
        """Add another metric or a numeric value to this metric.

        Raises:
            TypeError: If one of the values is a parent metric.
        """
        if self._is_parent() or (isinstance(other, Metric) and other._is_parent()):
            raise TypeError('Cannot perform arithmetic operations between parent metrics')

        return float(self) + float(other)

    def __sub__(self, other: Union[int, float, 'Metric']) -> float:
        """Subtract another metric or a numeric value from this metric.

        Raises:
            TypeError: If one of the values is a parent metric.
        """
        if self._is_parent() or (isinstance(other, Metric) and other._is_parent()):
            raise TypeError('Cannot perform arithmetic operations between parent metrics')

        return float(self) - float(other)

    def _is_parent(self) -> bool:
        """Check if the metric is a parent metric."""
        return bool(self._labelnames) and not bool(self._labelvalues)

    @abstractmethod
    def _child_value(self) -> float:
        """Get the value of a child metric, used by the `value` property."""

    @property
    def value(self) -> float | dict[str, float]:
        """Get the value of the metric. If the metric is a parent, return a dictionary of values per label set.

        Returns:
            float | dict[str, float]: The value of the metric or a dictionary of labels-value pairs if it's a parent.
        """
        if self._is_parent():
            values: dict[str, float] = {}
            for label_values, metric in self._metrics.items():
                labels = ','.join(label_values)
                values[labels] = metric.value  # type: ignore[attr-defined]
            return values

        return self._child_value()

    def __float__(self) -> float:
        if isinstance(self.value, float):
            return self.value

        raise TypeError('Cannot convert a parent metric to a float')

    def __int__(self) -> int:
        if isinstance(self.value, float):
            return int(self.value)

        raise TypeError('Cannot convert a parent metric to an integer')

    def __str__(self) -> str:
        return str(self.value)


class Counter(Metric, PrometheusCounter):
    """Custom Counter metric, extending Prometheus' Counter.

    Calling += operator on a Counter will increment the metric using `inc`.

    If it's a parent metric, you can use the dict syntax (`metric["label"]`) to get and increment the value of a specific label set.

    The `value` property returns the value of the Counter, as a float or a dictionary of label-value pairs if it's a parent metric
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def _child_value(self) -> float:
        """Get the value of the Counter."""
        return float(self._value.get())

    def __iadd__(self, other: int | float) -> 'Counter':  # type: ignore[override, misc]
        """Increment the Counter using `inc`."""
        self.inc(other)
        return self

    def __getitem__(self, label_values: str | tuple[str, ...]) -> 'Counter':
        """Get a specific label set of the Counter."""
        if not self._is_parent():
            raise TypeError('This Counter is not a parent')
        if isinstance(label_values, str):
            label_values = (label_values,)
        elif not isinstance(label_values, tuple):
            raise TypeError('Label values must be a string or tuple of strings')

        return self.labels(*label_values)

    def __setitem__(self, label_values: str | tuple[str, ...], value: Union[float, 'Counter']) -> None:
        # The += (__idadd__) operator calls __setitem__ with the new metric as the value
        # We already handle the increment operation in __iadd__, so we can safely ignore this call
        # Same goes for the -= (__isub__) operator
        if isinstance(value, Counter):
            if value in self._metrics.values():
                return

        raise TypeError('Counters can only be incremented, use the += operator or the `inc` method instead')


class Gauge(Metric, PrometheusGauge):
    """Custom Gauge metric, extending Prometheus' Gauge.

    Calling += and -= operators on a Gauge will increment and decrement the metric using `inc` and `dec`, respectively.

    If it's a parent metric, you can use the dict syntax (`metric["label"]`) to get and set the value of a specific label set.

    The `value` property returns the value of the Gauge, as a float or a dictionary of label-value pairs if it's a parent metric
    """

    # Append the docstring from prometheus_client.Gauge
    __doc__ = f'{__doc__}\n{PrometheusGauge.__doc__}'

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def _child_value(self) -> float:
        """Get the value of the Gauge."""
        return float(self._value.get())

    def __bool__(self) -> bool:
        return bool(self.value)

    def __iadd__(self, other: int | float) -> 'Gauge':  # type: ignore[override, misc]
        """Increment the Gauge using `inc`."""
        self.inc(other)
        return self

    def __isub__(self, other: int | float) -> 'Gauge':  # type: ignore[override, misc]
        """Decrement the Gauge using `dec`."""
        self.dec(other)
        return self

    def __getitem__(self, label_values: str | tuple[str, ...]) -> 'Gauge':
        """Get a specific label set of the Gauge."""
        if not self._is_parent():
            raise TypeError('This Gauge is not a parent')
        if isinstance(label_values, str):
            label_values = (label_values,)
        elif not isinstance(label_values, tuple):
            raise TypeError('Label values must be a string or tuple of strings')
        return self.labels(*label_values)

    def __setitem__(self, label_values: str | tuple[str, ...], value: Union[float, 'Gauge']) -> None:
        """Set the value of a gauge metric using `set`."""
        # The += (__iadd__) operator calls __setitem__ with the metric as the value
        # We already handle the increment operation in __iadd__, so we can safely ignore this call
        # Same goes for the -= (__isub__) operator
        if isinstance(value, Gauge):
            if value in self._metrics.values():
                return

            raise TypeError('Cannot reassign a Gauge with another Gauge')

        if not self._is_parent():
            raise TypeError('This Gauge is not a parent')

        self[label_values].set(value)


class Histogram(Metric, PrometheusHistogram):
    """Custom Histogram metric, extending Prometheus' Histogram.

    Calling += and -= operators on a Histogram will increment and decrement the metric using `observe`, respectively.

    If it's a parent metric, you can use the dict syntax (`metric["label"]`) to get and set the value of a specific label set.

    The `value` property returns the sum of all observations in the Histogram, as a float or a dictionary of label-value pairs
    if it's a parent metric
    """

    # Append the docstring from prometheus_client.Gauge
    __doc__ = f'{__doc__}\n{PrometheusGauge.__doc__}'

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def _child_value(self) -> float:
        """Return the sum of all observations in the Histogram."""
        return float(self._sum.get())

    def __iadd__(self, other: int | float) -> 'Histogram':  # type: ignore[override, misc]
        """Increment the Histogram using `observe`."""
        self.observe(other)
        return self

    def __isub__(self, other: int | float) -> 'Histogram':  # type: ignore[override, misc]
        """Decrement the Histogram using `observe`."""
        self.observe(-other)
        return self

    def __getitem__(self, label_values: str | tuple[str, ...]) -> 'Histogram':
        """Get a specific label set of the Histogram."""
        if not self._is_parent():
            raise TypeError('This Histogram is not a parent')
        if isinstance(label_values, str):
            label_values = (label_values,)
        elif not isinstance(label_values, tuple):
            raise TypeError('Label values must be a string or tuple of strings')
        return self.labels(*label_values)

    def __setitem__(self, label_values: str | tuple[str, ...], value: Union[float, 'Histogram']) -> None:
        """Set the value of a specific label set of the Histogram using `observe`."""
        # The += (__idadd__) operator calls __setitem__ with the metric as the value
        # We already handle the increment operation in __iadd__, so we can safely ignore this call
        # Same goes for the -= (__isub__) operator
        if isinstance(value, Histogram):
            if value in self._metrics.values():
                return

            raise TypeError('Cannot reassign a Histogram with another Histogram')

        if not self._is_parent():
            raise TypeError('This Histogram is not a parent')

        self[label_values].observe(value)
