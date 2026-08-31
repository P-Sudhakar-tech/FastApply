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

`decide()` is the single entry point — it runs the probe-and-verify logic
exactly once and returns a `Decision` carrying the result (or None),
which engine was used, and a human-readable reason. `verbose=True` and
`engine="native"` on the accessor both read off that one `Decision`
rather than re-running the (cheap, but not free) probing a second time.
"""

from collections import namedtuple

import numpy as np
import pandas as pd

from . import _turbofastapply

MIN_ROWS = 50
SAMPLE_SIZE = 12
_TOL = 1e-9

Decision = namedtuple("Decision", ["result", "engine", "reason"])


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


def decide(series, func, *, enforce_min_rows=True):
    """Run the fast-path eligibility check once and return a Decision.

    `enforce_min_rows=False` (used by the accessor only when the caller
    explicitly requested `engine="native"`) skips the MIN_ROWS decline.
    MIN_ROWS exists purely as an `engine="auto"` profitability heuristic —
    below it, the native call's fixed overhead costs more than plain
    pandas on that little data — not a correctness requirement: the
    sample-verification and native computation below are both exact
    regardless of row count (verified down to a single row and to zero
    rows, where the empty-sample check further down declines cleanly on
    its own). An explicit engine="native" request means the caller wants
    the fast path regardless of whether it's worth it, same as
    engine="native" already overrides decide_str's separate engine="auto"
    exclusion elsewhere in this accessor."""
    if enforce_min_rows and len(series) < MIN_ROWS:
        return Decision(None, "pandas", f"series has {len(series)} rows, needs >= {MIN_ROWS}")
    if not pd.api.types.is_numeric_dtype(series.dtype):
        return Decision(None, "pandas", f"dtype {series.dtype} is not numeric")
    if pd.api.types.is_bool_dtype(series.dtype):
        # bool is numeric-ish but not integer-dtype in pandas, and its
        # apply() dtype inference is genuinely ambiguous for our purposes:
        # pandas keeps bool dtype only when func is *literally* Python's
        # identity (returns the same object unchanged), but promotes to
        # int64 for anything arithmetically equivalent (even `x*1+0`) —
        # a distinction our affine probing can't observe, since both
        # produce identical coefficients (a=1, b=0). Declining outright
        # avoids guessing wrong on a genuine ambiguity rather than
        # picking a dtype that's sometimes right by chance.
        return Decision(None, "pandas", "bool dtype not supported (see decide.py for why)")

    is_int_series = pd.api.types.is_integer_dtype(series.dtype)
    # NaN can only occur in float (never plain int64) Series, but must be
    # checked across the WHOLE series, not just the verification sample:
    # a guessed affine function is only verified against sampled
    # positions, so a NaN elsewhere would silently get the naive a*x+b
    # treatment even if the real function has explicit NaN-handling
    # logic (branches) that differs — confirmed as a real bug, not a
    # theoretical one, by a case where func returned 0.0 for NaN input
    # but the native path returned NaN instead, because the sample
    # (by chance, given its stride) never landed on the NaN row.
    if not is_int_series and series.isna().any():
        return Decision(None, "pandas", "series contains NaN — can't safely trust a sample-only affine guess")

    sample = _sample(series)
    if len(sample) == 0:
        return Decision(None, "pandas", "empty sample")

    if func is abs:
        if is_int_series:
            arr = series.to_numpy().astype(np.int64, copy=False)
            out = _turbofastapply.abs_i64(arr)
            engine = "native-int64"
        else:
            out = _turbofastapply.abs_f64(series.to_numpy(dtype=float))
            engine = "native-float64"
        result = pd.Series(out, index=series.index, name=series.name)
        return Decision(result, engine, "abs() built-in, always exact")

    try:
        f0, f1 = func(0.0), func(1.0)
    except Exception as exc:
        return Decision(None, "pandas", f"function raised on probe inputs (0.0, 1.0): {exc!r}")
    if not (_is_real_number(f0) and _is_real_number(f1)):
        return Decision(None, "pandas", "function output at probe points isn't a real number")

    a, b = f1 - f0, f0
    if not _matches_on_sample(func, lambda x: a * x + b, sample):
        return Decision(
            None, "pandas", "function isn't affine on a sample of the real data (branches, x**2, ...)"
        )

    if is_int_series and _is_whole(a) and _is_whole(b):
        arr = series.to_numpy().astype(np.int64, copy=False)
        out = _turbofastapply.affine_i64(arr, int(round(a)), int(round(b)))
        result = pd.Series(out, index=series.index, name=series.name)
        return Decision(result, "native-int64", f"affine transform a*x+b, a={a:g}, b={b:g}")

    out = _turbofastapply.affine_f64(series.to_numpy(dtype=float), a, b)
    result = _restore_dtype(out, series)
    return Decision(result, "native-float64", f"affine transform a*x+b, a={a:g}, b={b:g}")


def try_numeric_fast_path(series, func):
    """Return an accelerated result equivalent to series.apply(func), or
    None if func can't be verified as a supported whitelisted pattern."""
    return decide(series, func).result
