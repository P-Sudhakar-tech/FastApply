import numpy as np
import pandas as pd
import pytest

import turboply  # noqa: F401  (registers the .turboply accessor)
from turboply import decide


LARGE_N = 1000


@pytest.mark.parametrize(
    "func",
    [
        lambda x: x * 2,
        lambda x: x * 2 + 1,
        lambda x: x + 5,
        lambda x: x - 3,
        lambda x: x / 4,
        lambda x: -x,
        lambda x: x,
        abs,
    ],
)
def test_fast_path_matches_pandas_on_large_int_series(func):
    s = pd.Series(np.arange(-LARGE_N // 2, LARGE_N // 2), dtype="int64")
    expected = s.apply(func)
    result = s.turboply.apply(func)
    pd.testing.assert_series_equal(result, expected)


@pytest.mark.parametrize(
    "func",
    [
        lambda x: x * 1.5 + 0.25,
        lambda x: x / 3,
        abs,
    ],
)
def test_fast_path_matches_pandas_on_large_float_series(func):
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(size=LARGE_N))
    expected = s.apply(func)
    result = s.turboply.apply(func)
    pd.testing.assert_series_equal(result, expected)


def test_fast_path_actually_engaged_for_affine_func():
    s = pd.Series(np.arange(LARGE_N, dtype="int64"))
    fast = decide.try_numeric_fast_path(s, lambda x: x * 2 + 1)
    assert fast is not None


@pytest.mark.parametrize(
    "func",
    [
        lambda x: x**2,
        lambda x: x if x % 2 == 0 else -x,
        str,
    ],
)
def test_non_affine_func_falls_back_correctly_on_large_series(func):
    s = pd.Series(np.arange(-LARGE_N // 2, LARGE_N // 2), dtype="int64")
    assert decide.try_numeric_fast_path(s, func) is None
    expected = s.apply(func)
    result = s.turboply.apply(func)
    pd.testing.assert_series_equal(result, expected)


def test_small_series_never_engages_fast_path():
    s = pd.Series(range(10))
    assert decide.try_numeric_fast_path(s, lambda x: x * 2) is None


def test_string_series_never_engages_fast_path():
    s = pd.Series([f"item_{i}" for i in range(LARGE_N)])
    assert decide.try_numeric_fast_path(s, str.upper) is None
    pd.testing.assert_series_equal(s.turboply.apply(str.upper), s.apply(str.upper))
