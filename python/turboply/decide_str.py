"""Dispatch heuristic for the string fast path (Phase 4).

Unlike the numeric affine transform (decide.py), a lambda like
`lambda s: s.replace("a", "b")` can't be reverse-engineered from a couple
of probe points — the captured `old`/`new` strings aren't recoverable by
black-box probing the way an affine transform's two coefficients are
(that trick relies on affine functions being fully determined by exactly
two points; string operations have no such closed form). So this module
covers two different mechanisms:

  - `decide()` — a strict identity whitelist for the handful of no-argument
    str methods reachable through plain `.turboply(func)`: `str.upper`,
    `str.lower`, `str.strip`. `func is str.upper` is completely safe to
    match this way (zero risk of misdetection, unlike sample-based
    guessing), since it's the exact operation, not an inference.

  - `verified_native()` — shared by `decide()` and by the `.turboply.str`
    sub-accessor (str_accessor.py) for the parametrized `contains`/
    `replace` ops, which are called directly instead of inferred from a
    lambda for the reason above. Even for an exact identity match, this
    never trusts the native path blindly: Rust's Unicode case-folding /
    whitespace-trimming, or its `regex` crate's dialect, could in
    principle differ from Python's in some edge case, so native output is
    always checked against real Python output on a sample of the actual
    data before being trusted on the full Series.
"""

import pandas as pd

from . import _turboply
from .decide import SAMPLE_SIZE, Decision

MIN_ROWS = 50

_METHOD_WHITELIST = {
    str.upper: ("native-str-upper", lambda items: _turboply.str_upper(items)),
    str.lower: ("native-str-lower", lambda items: _turboply.str_lower(items)),
    str.strip: ("native-str-strip", lambda items: _turboply.str_strip(items)),
}


def is_clean_string_series(series):
    is_stringy = series.dtype == object or pd.api.types.is_string_dtype(series.dtype)
    return is_stringy and not series.isna().any()


def sample(series):
    n = len(series)
    step = max(1, n // SAMPLE_SIZE)
    return series.to_numpy()[::step][:SAMPLE_SIZE]


def verified_native(series, native_fn, python_equiv, label, min_rows=MIN_ROWS):
    """Run native_fn on the full series, but only after confirming its
    output matches python_equiv on a real sample. Returns a Decision."""
    if len(series) < min_rows:
        return Decision(None, "pandas", f"series has {len(series)} rows, needs >= {min_rows}")
    if not is_clean_string_series(series):
        return Decision(None, "pandas", "not a clean, non-null string Series")

    values = sample(series)
    if len(values) == 0 or not all(isinstance(x, str) for x in values):
        return Decision(None, "pandas", "sample contains non-string values")

    try:
        native_sample = list(native_fn(list(values)))
        expected_sample = [python_equiv(x) for x in values]
    except Exception as exc:
        return Decision(None, "pandas", f"native/python call raised on sample: {exc!r}")

    if native_sample != expected_sample:
        return Decision(None, "pandas", "native result didn't match Python on a verification sample")

    try:
        out = native_fn(series.tolist())
    except Exception as exc:
        return Decision(None, "pandas", f"native call raised on full series: {exc!r}")

    result = pd.Series(out, index=series.index, name=series.name)
    return Decision(result, label, f"verified against a {len(values)}-value sample")


def decide(series, func):
    """Whitelist dispatch for .turboply(func) — only exact identity
    matches against known str methods (upper/lower/strip)."""
    whitelisted = _METHOD_WHITELIST.get(func)
    if whitelisted is None:
        return Decision(None, "pandas", "function isn't a whitelisted string method (upper/lower/strip)")
    label, native_fn = whitelisted
    return verified_native(series, native_fn, func, label)
