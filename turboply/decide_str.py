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
    """Standalone sampler kept for callers that only need the sample
    (e.g. tests) — verified_native() below derives its sample from the
    same items list it already builds for the full run instead of calling
    this, to avoid converting the whole series twice."""
    n = len(series)
    step = max(1, n // SAMPLE_SIZE)
    return series.to_numpy()[::step][:SAMPLE_SIZE]


def verified_native(series, native_fn, python_equiv, label, min_rows=MIN_ROWS, dtype=None):
    """Run native_fn on the full series, but only after confirming its
    output matches python_equiv on a real sample. Returns a Decision.

    `dtype`, when known ahead of time (e.g. the source Series' own dtype
    for string results, "bool" for contains), is passed straight to the
    result pd.Series(...) constructor. Without it, pandas has to run its
    type-inference scan over the whole output list to guess a dtype —
    for string results specifically, that scan alone was measured costing
    more than the native computation itself, enough to make the "fast"
    path net slower than plain pandas at 1,000 rows.

    Builds `series.tolist()` exactly once and derives the verification
    sample from that same list (rather than a separate .to_numpy() pass
    just to grab a dozen values) for the same reason — avoiding a second
    full-series conversion that would otherwise double the biggest fixed
    cost in this whole path for no benefit."""
    if len(series) < min_rows:
        return Decision(None, "pandas", f"series has {len(series)} rows, needs >= {min_rows}")
    if not is_clean_string_series(series):
        return Decision(None, "pandas", "not a clean, non-null string Series")

    items = series.tolist()
    step = max(1, len(items) // SAMPLE_SIZE)
    values = items[::step][:SAMPLE_SIZE]
    if len(values) == 0 or not all(isinstance(x, str) for x in values):
        return Decision(None, "pandas", "sample contains non-string values")

    try:
        native_sample = list(native_fn(values))
        expected_sample = [python_equiv(x) for x in values]
    except Exception as exc:
        return Decision(None, "pandas", f"native/python call raised on sample: {exc!r}")

    if native_sample != expected_sample:
        return Decision(None, "pandas", "native result didn't match Python on a verification sample")

    try:
        out = native_fn(items)
    except Exception as exc:
        return Decision(None, "pandas", f"native call raised on full series: {exc!r}")

    result = pd.Series(out, index=series.index, name=series.name, dtype=dtype)
    return Decision(result, label, f"verified against a {len(values)}-value sample")


def decide(series, func):
    """Whitelist dispatch for .turboply(func) — only exact identity
    matches against known str methods (upper/lower/strip)."""
    whitelisted = _METHOD_WHITELIST.get(func)
    if whitelisted is None:
        return Decision(None, "pandas", "function isn't a whitelisted string method (upper/lower/strip)")
    label, native_fn = whitelisted
    # Match the source Series' own dtype rather than hardcoding "object":
    # pandas 3.x infers its dedicated StringDtype for string Series by
    # default, not the legacy object dtype, and a string->string
    # transform should preserve whichever one the input actually is.
    return verified_native(series, native_fn, func, label, dtype=series.dtype)
