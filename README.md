# Turboply

A drop-in, accelerated replacement for `pandas.apply()`, in the spirit of
[swifter](https://github.com/jmcarpenter2/swifter).

Status: **Phase 2** — numeric transforms detected as linear/abs (e.g.
`x * 2 + 1`) on a numeric Series of 50+ rows run through a native fast
path, ~1.9–2x faster than plain `pandas.apply()` on 1,000 rows
(`examples/benchmark.py`). Everything else falls back to native
`pandas.apply()`, so `.turboply` is always correctness-equivalent to it.
See `claude.md` for the full roadmap.

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
```
