"""Phase 2: dispatch heuristic for the numeric fast path.

Arbitrary Python callables can't be safely translated to native code in
general, so instead of parsing function source/bytecode we *probe* the
callable: evaluate it at a couple of known points to guess an affine form
(``a * x + b``), then verify that guess against a sample of the series'
real values. Only if every sampled value matches do we trust the native
path — anything that doesn't fit (branches, non-numeric output, ``x**2``,
...) safely falls back to plain pandas.
"""

import numpy as np
import pandas as pd

from . import _turboply

MIN_ROWS = 50
SAMPLE_SIZE = 12
_TOL = 1e-9


def _is_real_number(value):
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)


def _sample_indices(n):
    step = max(1, n // SAMPLE_SIZE)
    return slice(None, None, step)


def _matches_on_sample(func, predict, sample):
    for x in sample:
        try:
            actual = func(x)
        except Exception:
            return False
        if not _is_real_number(actual):
            return False
        predicted = predict(x)
        tol = _TOL * max(1.0, abs(actual))
        if np.isnan(predicted) or np.isnan(actual):
            return False
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

    arr = series.to_numpy(dtype=float)
    sample = arr[_sample_indices(len(arr))]
    if len(sample) == 0 or np.any(np.isnan(sample)):
        return None

    if func is abs:
        return _restore_dtype(_turboply.abs_f64(arr), series)

    try:
        f0, f1 = func(0.0), func(1.0)
    except Exception:
        return None
    if not (_is_real_number(f0) and _is_real_number(f1)):
        return None

    a, b = f1 - f0, f0
    if _matches_on_sample(func, lambda x: a * x + b, sample):
        return _restore_dtype(_turboply.affine_f64(arr, a, b), series)

    return None
