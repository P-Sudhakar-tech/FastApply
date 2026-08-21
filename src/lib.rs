pub mod core;

use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use regex::Regex;

/// Elementwise `a * x + b` over a f64 array. Covers add/sub/mul/div-by-scalar
/// and any composition of them, since all of those reduce to a single affine
/// transform. GIL is released either way; only arrays past
/// [`core::PARALLEL_THRESHOLD`] pay for rayon's parallel dispatch.
#[pyfunction]
fn affine_f64<'py>(
    py: Python<'py>,
    arr: PyReadonlyArray1<'py, f64>,
    a: f64,
    b: f64,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let slice = arr.as_slice()?;
    let out = py.allow_threads(|| core::affine_f64(slice, a, b));
    Ok(out.into_pyarray_bound(py))
}

/// Integer counterpart of [`affine_f64`]. Used whenever both the Series and
/// the detected `a`/`b` coefficients are integral, so integer Series never
/// pay for a float64 round-trip (allocation, cast, and a rounding pass to
/// restore dtype afterwards) and stay exact past f64's 53-bit integer range.
#[pyfunction]
fn affine_i64<'py>(
    py: Python<'py>,
    arr: PyReadonlyArray1<'py, i64>,
    a: i64,
    b: i64,
) -> PyResult<Bound<'py, PyArray1<i64>>> {
    let slice = arr.as_slice()?;
    let out = py.allow_threads(|| core::affine_i64(slice, a, b));
    Ok(out.into_pyarray_bound(py))
}

/// Elementwise `abs(x)` over a f64 array. See [`affine_f64`] for the
/// sequential/parallel threshold rationale.
#[pyfunction]
fn abs_f64<'py>(py: Python<'py>, arr: PyReadonlyArray1<'py, f64>) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let slice = arr.as_slice()?;
    let out = py.allow_threads(|| core::abs_f64(slice));
    Ok(out.into_pyarray_bound(py))
}

/// Integer counterpart of [`abs_f64`]; see [`affine_i64`] for why it exists.
#[pyfunction]
fn abs_i64<'py>(py: Python<'py>, arr: PyReadonlyArray1<'py, i64>) -> PyResult<Bound<'py, PyArray1<i64>>> {
    let slice = arr.as_slice()?;
    let out = py.allow_threads(|| core::abs_i64(slice));
    Ok(out.into_pyarray_bound(py))
}

/// Elementwise `s.upper()` over a list of strings. See [`affine_f64`] for
/// the sequential/parallel threshold rationale.
#[pyfunction]
fn str_upper(py: Python<'_>, items: Vec<String>) -> Vec<String> {
    py.allow_threads(|| core::str_upper(&items))
}

/// Elementwise `s.lower()` over a list of strings.
#[pyfunction]
fn str_lower(py: Python<'_>, items: Vec<String>) -> Vec<String> {
    py.allow_threads(|| core::str_lower(&items))
}

/// Elementwise `s.strip()` over a list of strings — trims Unicode
/// whitespace from both ends, same as Rust's `str::trim()`.
#[pyfunction]
fn str_strip(py: Python<'_>, items: Vec<String>) -> Vec<String> {
    py.allow_threads(|| core::str_strip(&items))
}

/// Elementwise regex search over a list of strings: does `pattern` match
/// anywhere in each string? Backs `.turboply.str.contains(pattern)`.
#[pyfunction]
fn str_contains(py: Python<'_>, items: Vec<String>, pattern: String) -> PyResult<Vec<bool>> {
    let re = Regex::new(&pattern).map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok(py.allow_threads(|| core::str_contains(&items, &re)))
}

/// Elementwise regex replace-all over a list of strings. Backs
/// `.turboply.str.replace(pattern, repl)`. Rust's `regex` crate has no
/// backreference support (unlike Python's `re`), so patterns/replacements
/// relying on that won't compile or won't match Python's behavior here —
/// the caller (decide_str.py) verifies output against real Python `re`
/// output on a sample before trusting this on the full Series, so that
/// gap safely falls back rather than silently mismatching.
#[pyfunction]
fn str_replace(py: Python<'_>, items: Vec<String>, pattern: String, repl: String) -> PyResult<Vec<String>> {
    let re = Regex::new(&pattern).map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok(py.allow_threads(|| core::str_replace(&items, &re, &repl)))
}

/// Row-wise `sum(coeffs[i] * columns[i][row]) + intercept`, evaluated for
/// every row. Struct-of-arrays layout: `columns` is one 1-D array per
/// DataFrame column rather than an array-of-rows, so each column stays a
/// contiguous, zero-copy view into the original numpy backing array.
/// Backs the DataFrame row-wise fast path (decide_row.py): a row-wise
/// callable that turns out to be a linear combination of columns (e.g.
/// `row['a'] + row['b']`) is a straight generalization of the univariate
/// affine transform in [`affine_f64`] — same rationale for the
/// sequential/parallel split.
#[pyfunction]
fn row_affine_f64<'py>(
    py: Python<'py>,
    columns: Vec<PyReadonlyArray1<'py, f64>>,
    coeffs: Vec<f64>,
    intercept: f64,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    if columns.len() != coeffs.len() {
        return Err(PyValueError::new_err("columns and coeffs must be the same length"));
    }
    let slices: Vec<&[f64]> = columns
        .iter()
        .map(|c| c.as_slice().map_err(|e| PyValueError::new_err(e.to_string())))
        .collect::<PyResult<Vec<_>>>()?;
    let n = slices.first().map(|s| s.len()).unwrap_or(0);
    for s in &slices {
        if s.len() != n {
            return Err(PyValueError::new_err("all columns must be the same length"));
        }
    }

    let out = py.allow_threads(|| core::row_affine_f64(&slices, &coeffs, intercept));
    Ok(out.into_pyarray_bound(py))
}

#[pymodule]
fn _turboply(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(affine_f64, m)?)?;
    m.add_function(wrap_pyfunction!(affine_i64, m)?)?;
    m.add_function(wrap_pyfunction!(abs_f64, m)?)?;
    m.add_function(wrap_pyfunction!(abs_i64, m)?)?;
    m.add_function(wrap_pyfunction!(str_upper, m)?)?;
    m.add_function(wrap_pyfunction!(str_lower, m)?)?;
    m.add_function(wrap_pyfunction!(str_strip, m)?)?;
    m.add_function(wrap_pyfunction!(str_contains, m)?)?;
    m.add_function(wrap_pyfunction!(str_replace, m)?)?;
    m.add_function(wrap_pyfunction!(row_affine_f64, m)?)?;
    Ok(())
}
