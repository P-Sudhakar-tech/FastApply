# TurboFastApply

A drop-in, accelerated replacement for `pandas.apply()`.

Status: **feature-complete** (all 8 roadmap phases) — numeric transforms
detected as linear/abs (`x * 2 + 1`) and row-wise DataFrame functions
that are linear combinations of columns (`row['a'] + row['b']`) run
through genuine native fast paths, ~1.9–2x and ~4–4.5x faster than plain
`pandas.apply()` on 1,000 rows respectively (`examples/benchmark.py`).
Arbitrary callables that don't qualify get a sampling-based threaded
fallback that only engages when actually measured faster (helps I/O-bound
work, correctly declines pure-CPU-bound Python). Everything else falls
back to native `pandas.apply()`, so `.turbofastapply` is always
correctness-equivalent to it. See `claude.md` for the full roadmap,
including three real correctness bugs found and fixed during hardening.

String ops (`str.upper`/`.lower`/`.strip`, `.turbofastapply.str.contains()`/
`.replace()`) are implemented and correct but **not** faster in practice
— benchmarked from 500 to 1,000,000 rows, consistently ~0.6–0.8x plain
pandas — so they're excluded from the default `engine="auto"` and only
reachable via explicit `engine="native"`. See "Options" below.

## Development

The native extension is built with [PyO3](https://pyo3.rs) +
[maturin](https://www.maturin.rs).

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install maturin pytest pandas numpy
maturin develop                # builds the extension and installs it in the venv
pytest -v
```

If `maturin develop` fails to launch on your machine (e.g. `maturin.exe`
can't load `api-ms-win-crt-*.dll` because only the GNU Rust toolchain is
installed and the MSVC Visual C++ Redistributable is missing), use the
fallback build script instead. It calls `cargo build` directly, drops the
resulting DLL into the package as a `.pyd`, and links `python/` into the
venv via a `.pth` file (same end result as `maturin develop`, so
`import turbofastapply` works from anywhere without setting `PYTHONPATH`):

```powershell
./build.ps1
.venv/Scripts/python.exe -m pytest -v
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs on Ubuntu with a
properly provisioned toolchain, so `maturin develop` works there regardless.

## Usage

The accessor is directly callable — `s.turbofastapply(func)` is the primary API,
not `s.turbofastapply.apply(func)` (kept only as an alias):

```python
import pandas as pd
import turbofastapply  # registers the .turbofastapply accessor

s = pd.Series([1, 2, 3])
s.turbofastapply(lambda x: x * 2)   # identical result to s.apply(lambda x: x * 2)

df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
df.turbofastapply(lambda row: row["a"] + row["b"], axis=1)

# Whitelisted string methods and regex ops (.turbofastapply.str mirrors
# pandas' own .str accessor) are implemented and correct, but not
# faster than plain pandas in practice — see the Status note above.
# They use plain pandas by default; engine="native" forces the compiled
# path if you want it anyway:
names = pd.Series(["  Ada  ", "GRACE", "margaret"] * 50)
names.turbofastapply(str.upper, engine="native")
names.turbofastapply.str.contains(r"^GRACE$")

# .groupby(...).turbofastapply(func) also works — a drop-in for
# .groupby(...).apply(func) with the same engine/verbose/progress_bar
# options as everything else. engine="auto" tries a threaded parallel
# fallback first (measured, not assumed — same approach as the
# GIL-releasing-callable case above, just chunked by group), for
# GroupBy objects with at least 800 groups — a real, ~2x+ speedup for
# GIL-releasing callables, verified never to regress a CPU-bound one
# even at that scale (see claude.md's P9 section for why the threshold
# is that high). Below that it falls back to plain pandas immediately,
# no measurement overhead paid. There's no *native* (Rust) GroupBy path
# though, so engine="native" raises rather than pretending to
# accelerate something that doesn't exist yet.
df.groupby("a").turbofastapply(lambda g: g["b"].sum())
```

### Options

```python
s.turbofastapply(func, engine="auto")     # default: try the native fast path, fall back silently
s.turbofastapply(func, engine="pandas")   # always plain pandas .apply(), skips the eligibility check
s.turbofastapply(func, engine="native")   # require the fast path; raises ValueError with the
                                     # specific reason if func isn't eligible, instead of
                                     # silently falling back

s.turbofastapply(func, verbose=True)      # prints which engine was used and why, to stderr

s.turbofastapply(func, progress_bar=True) # progress bar for the pandas-fallback path only —
                                     # the native path is one vectorized call, nothing to
                                     # report progress on there
```

## Benchmarks

`examples/benchmark.py` compares plain `pandas.apply()` against `.turbofastapply()`
on 1,000 rows (median of 50 runs, 5 warmup): the numeric-transform case
(`x * 2 + 1`) lands at **~1.9–2x** and the row-wise case
(`row['a'] + row['b']`, notoriously slow in vanilla pandas since it
constructs a Series per row) at **~4–4.5x**. It also runs the string case
both ways — default `engine="auto"` (matches plain pandas exactly, no
native path picked) and forced `engine="native"` — to show directly why
`"auto"` never picks it.

`cargo bench` (`benches/native_benches.rs`) benchmarks the pure Rust
compute cores directly (1,000 / 50,000 / 200,000 elements), independent
of Python/PyO3 marshaling overhead — useful for catching a regression in
the Rust layer itself.

`examples/benchmark_vs_competitor.py` adds a comparison against another
accelerated-`.apply()` library. It's a separate opt-in script (not a
`turbofastapply` dependency), since that library pulls in dask, tqdm, etc. As of
this writing its 1.4.0 release doesn't run cleanly against recent
pandas/Python — see that script's error message for the specific
compatibility gap if you hit it.
