"""Minimal, dependency-free progress reporting for the pandas-fallback
path. Only meaningful when pandas itself is doing the row-by-row Python
loop (the native fast path is a single vectorized call, so there's
nothing to report progress on)."""

import sys

_BAR_WIDTH = 30


def with_progress(func, total, label="turbofastapply"):
    if total <= 0:
        return func

    state = {"count": 0}
    report_every = max(1, total // 100)

    def wrapped(x, *args, **kwargs):
        state["count"] += 1
        n = state["count"]
        if n == total or n % report_every == 0:
            frac = n / total
            filled = int(_BAR_WIDTH * frac)
            bar = "#" * filled + "-" * (_BAR_WIDTH - filled)
            end = "\n" if n == total else ""
            print(f"\r{label} [{bar}] {n}/{total} ({frac:.0%})", end=end, file=sys.stderr, flush=True)
        return func(x, *args, **kwargs)

    return wrapped
