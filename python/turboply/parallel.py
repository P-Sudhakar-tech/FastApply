"""Sampling-based parallel fallback for arbitrary (non-whitelisted) callables.

For callables that don't qualify for the native numeric fast path
(decide.py), pandas.apply() falls back to a single-threaded Python loop.
Whether a thread pool can beat that depends entirely on whether `func`
releases the GIL while it runs — calls that hit I/O, sleep, hashlib,
compression, or certain numpy/pandas C internals do; plain CPU-bound
Python bytecode does not, and threading it just adds overhead for no
benefit (CPython's GIL means only one thread runs Python bytecode at a
time regardless of thread count).

Rather than assume either way, this measures it: time a small sample
serially and threaded-chunked, and only use the threaded version on the
full data if it was actually faster on the sample. That's the
"sampling-based" half of Phase 3 — no static assumption about which
callables parallelize, and a function that doesn't benefit costs a
bounded, small measurement overhead rather than a silent regression.

Only safe to chunk by contiguous row ranges, so this applies to
Series.apply and DataFrame.apply(axis=1) — never DataFrame.apply(axis=0),
where func operates on whole columns rather than independent rows.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

MIN_ROWS = 2000
SAMPLE_ROWS = 100
MIN_SPEEDUP = 1.5
_MIN_MEASURABLE_TIME = 0.001
_MAX_WORKERS = min(32, os.cpu_count() or 4)


def _chunks(obj, n):
    size = len(obj)
    if size == 0:
        return []
    step = max(1, -(-size // n))  # ceil division
    return [obj.iloc[i : i + step] for i in range(0, size, step)]


def _apply_threaded(obj, func, axis):
    parts = _chunks(obj, _MAX_WORKERS)
    if not parts:
        return obj.apply(func) if axis is None else obj.apply(func, axis=axis)
    with ThreadPoolExecutor(max_workers=len(parts)) as pool:
        if axis is None:
            futures = [pool.submit(part.apply, func) for part in parts]
        else:
            futures = [pool.submit(part.apply, func, axis=axis) for part in parts]
        results = [f.result() for f in futures]
    return pd.concat(results)


def _time_once(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def try_parallel_fallback(obj, func, axis=None):
    """Return an accelerated result equivalent to obj.apply(func) (or
    obj.apply(func, axis=axis)), or None if a sample measurement didn't
    show threading actually helps — caller should fall back to plain
    serial pandas .apply() in that case."""
    n = len(obj)
    if n < MIN_ROWS:
        return None

    sample = obj.iloc[:SAMPLE_ROWS]

    def serial_call():
        return sample.apply(func) if axis is None else sample.apply(func, axis=axis)

    try:
        t_serial = _time_once(serial_call)
        if t_serial < _MIN_MEASURABLE_TIME:
            return None
        t_parallel = _time_once(lambda: _apply_threaded(sample, func, axis))
    except Exception:
        return None

    if t_parallel <= 0 or t_serial / t_parallel < MIN_SPEEDUP:
        return None

    try:
        return _apply_threaded(obj, func, axis)
    except Exception:
        return None
