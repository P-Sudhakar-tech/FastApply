from unittest import mock

import numpy as np
import pandas as pd
import pytest

import turboply  # noqa: F401  (registers the .turboply accessor)
from turboply import _turboply, decide


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


def test_int_series_with_whole_coefficients_uses_int64_path_not_float():
    """x * 2 + 1 on an int64 Series should skip the float64 round-trip
    entirely and call the dedicated int64 native fn."""
    s = pd.Series(np.arange(LARGE_N, dtype="int64"))
    with mock.patch.object(_turboply, "affine_i64", wraps=_turboply.affine_i64) as spy_i64, \
         mock.patch.object(_turboply, "affine_f64", wraps=_turboply.affine_f64) as spy_f64:
        result = decide.try_numeric_fast_path(s, lambda x: x * 2 + 1)
    assert result is not None
    assert result.dtype == np.int64
    spy_i64.assert_called_once()
    spy_f64.assert_not_called()


def test_int_series_with_fractional_coefficients_uses_float_path():
    """x / 3 on an int64 Series can't stay integral, so it must use the
    float64 path (and pandas would return float64 too)."""
    s = pd.Series(np.arange(LARGE_N, dtype="int64"))
    with mock.patch.object(_turboply, "affine_i64", wraps=_turboply.affine_i64) as spy_i64, \
         mock.patch.object(_turboply, "affine_f64", wraps=_turboply.affine_f64) as spy_f64:
        result = decide.try_numeric_fast_path(s, lambda x: x / 3)
    assert result is not None
    assert result.dtype == np.float64
    spy_f64.assert_called_once()
    spy_i64.assert_not_called()


def test_small_series_never_engages_fast_path():
    s = pd.Series(range(10))
    assert decide.try_numeric_fast_path(s, lambda x: x * 2) is None


def test_string_series_never_engages_numeric_fast_path():
    """decide.py (numeric) should decline a string Series outright — the
    string whitelist lives in decide_str.py (Phase 4) and is exercised
    separately in tests/test_decide_str.py; this only checks the numeric
    module's own boundary."""
    s = pd.Series([f"item_{i}" for i in range(LARGE_N)])
    assert decide.try_numeric_fast_path(s, str.upper) is None
    pd.testing.assert_series_equal(s.turboply.apply(str.upper), s.apply(str.upper))


def test_nan_outside_sample_does_not_silently_corrupt_result():
    """Regression test for a real bug (found via P7 hardening, not code
    review): the verification sample only covers ~12 stride-spaced
    positions, so a NaN elsewhere in the Series would previously pass
    verification undetected, and the native path would then apply the
    naive a*x+b formula to that NaN — silently wrong whenever the real
    function has explicit NaN-handling logic the sample never exercised.
    """
    vals = [1.0] * LARGE_N
    vals[40] = float("nan")  # off the sampling stride for a 1000-row Series
    s = pd.Series(vals)

    def func(x):
        return 0.0 if np.isnan(x) else x * 2 + 1

    assert decide.try_numeric_fast_path(s, func) is None
    pd.testing.assert_series_equal(s.turboply(func), s.apply(func))


def test_inf_handled_correctly_via_fallback_or_native():
    s = pd.Series([1.0, float("inf"), float("-inf")] + list(range(LARGE_N)))
    func = lambda x: x * 2 + 1  # noqa: E731
    expected = s.apply(func)
    result = s.turboply(func)
    pd.testing.assert_series_equal(result, expected)
