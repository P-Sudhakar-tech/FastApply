"""Dispatch heuristic for the numeric fast path.

Arbitrary Python callables can't be safely translated to native code in
general, so instead of parsing function source/bytecode we *probe* the
callable: evaluate it at a couple of known points to guess an affine form
(``a * x + b``), then verify that guess against a sample of the series'
real values. Only if every sampled value matches do we trust the native
path — anything that doesn't fit (branches, non-numeric output, ``x**2``,
...) safely falls back to plain pandas.

Integer Series get a dedicated int64 path (`affine_i64` / `abs_i64`)
whenever the detected coefficients are themselves whole numbers, so the
common case (`x * 2 + 1` on an int column) never pays for a float64
round-trip: no cast of the full array to float, and no rounding pass
afterwards to restore the dtype.
"""

import numpy as np
import pandas as pd

from . import _turboply

MIN_ROWS = 50
SAMPLE_SIZE = 12
_TOL = 1e-9


def _is_real_number(value):
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)


def _is_whole(x):
    return bool(np.isclose(x, np.round(x)))


def _sample(series):
    n = len(series)
    step = max(1, n // SAMPLE_SIZE)
    return series.to_numpy()[::step][:SAMPLE_SIZE].astype(float)


def _matches_on_sample(func, predict, sample):
    for x in sample:
        try:
            actual = func(x)
        except Exception:
            return False
        if not _is_real_number(actual):
            return False
        predicted = predict(x)
        if np.isnan(predicted) or np.isnan(actual):
            return False
        tol = _TOL * max(1.0, abs(actual))
        if abs(predicted - actual) > tol:
            return False
    return True


def _restore_dtype(out, series):
    result = pd.Series(out, index=series.index, name=series.name)
    if pd.api.types.is_integer_dtype(series.dtype) and np.all(np.isclose(out, np.round(out))):
        result = result.round().astype(series.dtype)
    return result


def try_numeric_fast_path(series, func):
    """Return an accelerated result equivalent to series.apply(func), or
    None if func can't be verified as a supported whitelisted pattern."""
    if len(series) < MIN_ROWS or not pd.api.types.is_numeric_dtype(series.dtype):
        return None

    is_int_series = pd.api.types.is_integer_dtype(series.dtype)
    sample = _sample(series)
    if len(sample) == 0 or np.any(np.isnan(sample)):
        return None

    if func is abs:
        if is_int_series:
            arr = series.to_numpy().astype(np.int64, copy=False)
            out = _turboply.abs_i64(arr)
        else:
            out = _turboply.abs_f64(series.to_numpy(dtype=float))
        return pd.Series(out, index=series.index, name=series.name)

    try:
        f0, f1 = func(0.0), func(1.0)
    except Exception:
        return None
    if not (_is_real_number(f0) and _is_real_number(f1)):
        return None

    a, b = f1 - f0, f0
    if not _matches_on_sample(func, lambda x: a * x + b, sample):
        return None

    if is_int_series and _is_whole(a) and _is_whole(b):
        arr = series.to_numpy().astype(np.int64, copy=False)
        out = _turboply.affine_i64(arr, int(round(a)), int(round(b)))
        return pd.Series(out, index=series.index, name=series.name)

    out = _turboply.affine_f64(series.to_numpy(dtype=float), a, b)
    return _restore_dtype(out, series)
