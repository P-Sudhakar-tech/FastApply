"""`.turboply.str` — mirrors pandas' own `.str` accessor, for the two
regex-backed ops that can't be safely auto-detected from an arbitrary
lambda passed to `.turboply(func)` the way `str.upper`/`.lower`/`.strip`
can (see decide_str.py's docstring for why). Called directly instead:
`s.turboply.str.contains(pattern)` / `s.turboply.str.replace(pattern, repl)`.

Same correctness guarantee as the rest of turboply: native output is
always verified against real Python `re` output on a sample before being
trusted on the full Series (decide_str.verified_native), so an
incompatibility between Rust's `regex` crate and Python's `re` (e.g. a
pattern using backreferences, which Rust's regex crate doesn't support)
falls back to plain pandas rather than silently mismatching.
"""

import re
import sys

from . import _turboply
from .decide_str import verified_native


def _log(verbose, op, engine, reason):
    if verbose:
        print(f"[turboply] str.{op}: engine={engine} - {reason}", file=sys.stderr)


class TurboplyStrAccessor:
    def __init__(self, series):
        self._series = series

    def contains(self, pattern, *, verbose=False):
        series = self._series
        decision = verified_native(
            series,
            lambda items: _turboply.str_contains(items, pattern),
            lambda s: bool(re.search(pattern, s)),
            "native-str-contains",
        )
        _log(verbose, "contains", decision.engine, decision.reason)
        if decision.result is not None:
            return decision.result
        return series.str.contains(pattern, regex=True)

    def replace(self, pattern, repl, *, verbose=False):
        series = self._series
        decision = verified_native(
            series,
            lambda items: _turboply.str_replace(items, pattern, repl),
            lambda s: re.sub(pattern, repl, s),
            "native-str-replace",
        )
        _log(verbose, "replace", decision.engine, decision.reason)
        if decision.result is not None:
            return decision.result
        return series.str.replace(pattern, repl, regex=True)
