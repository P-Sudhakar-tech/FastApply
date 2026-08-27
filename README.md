# Turboply

A drop-in, accelerated replacement for `pandas.apply()`.

Status: **feature-complete** (all 8 roadmap phases) — numeric transforms
detected as linear/abs (`x * 2 + 1`) and row-wise DataFrame functions
that are linear combinations of columns (`row['a'] + row['b']`) run
through genuine native fast paths, ~1.9–2x and ~4–4.5x faster than plain
`pandas.apply()` on 1,000 rows respectively (`examples/benchmark.py`).
Arbitrary callables that don't qualify get a sampling-based threaded
fallback that only engages when actually measured faster (helps I/O-bound
work, correctly declines pure-CPU-bound Python). Everything else falls
back to native `pandas.apply()`, so `.turboply` is always
correctness-equivalent to it. See `claude.md` for the full roadmap,
including three real correctness bugs found and fixed during hardening.

String ops (`str.upper`/`.lower`/`.strip`, `.turboply.str.contains()`/
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
`import turboply` works from anywhere without setting `PYTHONPATH`):

```powershell
./build.ps1
.venv/Scripts/python.exe -m pytest -v
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs on Ubuntu with a
properly provisioned toolchain, so `maturin develop` works there regardless.

## Usage

The accessor is directly callable — `s.turboply(func)` is the primary API,
not `s.turboply.apply(func)` (kept only as an alias):

```python
import pandas as pd
import turboply  # registers the .turboply accessor

s = pd.Series([1, 2, 3])
s.turboply(lambda x: x * 2)   # identical result to s.apply(lambda x: x * 2)

df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
df.turboply(lambda row: row["a"] + row["b"], axis=1)

# Whitelisted string methods and regex ops (.turboply.str mirrors
# pandas' own .str accessor) are implemented and correct, but not
# faster than plain pandas in practice — see the Status note above.
# They use plain pandas by default; engine="native" forces the compiled
# path if you want it anyway:
names = pd.Series(["  Ada  ", "GRACE", "margaret"] * 50)
names.turboply(str.upper, engine="native")
names.turboply.str.contains(r"^GRACE$")

# .groupby(...).turboply(func) also works — correctness-only for now (no
# native GroupBy fast path yet), so it's a drop-in for
# .groupby(...).apply(func) with the same engine/verbose/progress_bar
# options as everything else. engine="native" raises rather than
# pretending to accelerate something it can't yet.
df.groupby("a").turboply(lambda g: g["b"].sum())
```

### Options

```python
s.turboply(func, engine="auto")     # default: try the native fast path, fall back silently
s.turboply(func, engine="pandas")   # always plain pandas .apply(), skips the eligibility check
s.turboply(func, engine="native")   # require the fast path; raises ValueError with the
                                     # specific reason if func isn't eligible, instead of
                                     # silently falling back

s.turboply(func, verbose=True)      # prints which engine was used and why, to stderr

s.turboply(func, progress_bar=True) # progress bar for the pandas-fallback path only —
                                     # the native path is one vectorized call, nothing to
                                     # report progress on there
```

## Benchmarks

`examples/benchmark.py` compares plain `pandas.apply()` against `.turboply()`
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
`turboply` dependency), since that library pulls in dask, tqdm, etc. As of
this writing its 1.4.0 release doesn't run cleanly against recent
pandas/Python — see that script's error message for the specific
compatibility gap if you hit it.
