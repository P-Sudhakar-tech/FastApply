"""`.turbofastapply.str` — mirrors pandas' own `.str` accessor, for the two
regex-backed ops that can't be safely auto-detected from an arbitrary
lambda passed to `.turbofastapply(func)` the way `str.upper`/`.lower`/`.strip`
can (see decide_str.py's docstring for why). Called directly instead:
`s.turbofastapply.str.contains(pattern)` / `s.turbofastapply.str.replace(pattern, repl)`.

Same correctness guarantee as the rest of turbofastapply: native output is
always verified against real Python `re` output on a sample before being
trusted on the full Series (decide_str.verified_native), so an
incompatibility between Rust's `regex` crate and Python's `re` (e.g. a
pattern using backreferences, which Rust's regex crate doesn't support)
falls back to plain pandas rather than silently mismatching.

Performance caveat, measured rather than assumed: unlike the numeric
fast path (a genuine zero-copy numpy view), string data has to be
copied into owned Rust Strings on the way in and new Python str objects
on the way out. Benchmarked across pattern complexity and row counts up
to 1,000,000, that round-trip consistently costs more than it saves —
these methods are correct and will fall back automatically if native
output doesn't match Python's, but calling them isn't a performance
recommendation the way `.turbofastapply(func)`'s numeric/row-wise fast paths
are. See accessor.py's module docstring and claude.md for the numbers.
"""

import re
import sys

from . import _turbofastapply
from .decide_str import verified_native


def _log(verbose, op, engine, reason):
    if verbose:
        print(f"[turbofastapply] str.{op}: engine={engine} - {reason}", file=sys.stderr)


class TurboFastApplyStrAccessor:
    def __init__(self, series):
        self._series = series

    def contains(self, pattern, *, verbose=False):
        series = self._series
        decision = verified_native(
            series,
            lambda items: _turbofastapply.str_contains(items, pattern),
            lambda s: bool(re.search(pattern, s)),
            "native-str-contains",
            dtype=bool,
        )
        _log(verbose, "contains", decision.engine, decision.reason)
        if decision.result is not None:
            return decision.result
        return series.str.contains(pattern, regex=True)

    def replace(self, pattern, repl, *, verbose=False):
        series = self._series
        decision = verified_native(
            series,
            lambda items: _turbofastapply.str_replace(items, pattern, repl),
            lambda s: re.sub(pattern, repl, s),
            "native-str-replace",
            dtype=series.dtype,
        )
        _log(verbose, "replace", decision.engine, decision.reason)
        if decision.result is not None:
            return decision.result
        return series.str.replace(pattern, repl, regex=True)
