use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1};
use pyo3::prelude::*;
use rayon::prelude::*;

/// Below this length, rayon's work-splitting/join overhead costs more than
/// a plain sequential loop saves — so we only parallelize past it.
const PARALLEL_THRESHOLD: usize = 50_000;

/// Trivial native function used to verify the PyO3 build/import path end to end.
#[pyfunction]
fn dummy_add(a: i64, b: i64) -> i64 {
    a + b
}

macro_rules! elementwise {
    ($slice:expr, $threshold:expr, $f:expr) => {
        if $slice.len() >= $threshold {
            $slice.par_iter().map($f).collect()
        } else {
            $slice.iter().map($f).collect()
        }
    };
}

/// Elementwise `a * x + b` over a f64 array. Covers add/sub/mul/div-by-scalar
/// and any composition of them, since all of those reduce to a single affine
/// transform. GIL is released either way; only arrays past
/// [`PARALLEL_THRESHOLD`] pay for rayon's parallel dispatch.
#[pyfunction]
fn affine_f64<'py>(
    py: Python<'py>,
    arr: PyReadonlyArray1<'py, f64>,
    a: f64,
    b: f64,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let slice = arr.as_slice()?;
    let out: Vec<f64> =
        py.allow_threads(|| elementwise!(slice, PARALLEL_THRESHOLD, |&x| a * x + b));
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
    let out: Vec<i64> = py.allow_threads(|| {
        elementwise!(slice, PARALLEL_THRESHOLD, |&x| a
            .wrapping_mul(x)
            .wrapping_add(b))
    });
    Ok(out.into_pyarray_bound(py))
}

/// Elementwise `abs(x)` over a f64 array. See [`affine_f64`] for the
/// sequential/parallel threshold rationale.
#[pyfunction]
fn abs_f64<'py>(py: Python<'py>, arr: PyReadonlyArray1<'py, f64>) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let slice = arr.as_slice()?;
    let out: Vec<f64> = py.allow_threads(|| elementwise!(slice, PARALLEL_THRESHOLD, |&x: &f64| x.abs()));
    Ok(out.into_pyarray_bound(py))
}

/// Integer counterpart of [`abs_f64`]; see [`affine_i64`] for why it exists.
#[pyfunction]
fn abs_i64<'py>(py: Python<'py>, arr: PyReadonlyArray1<'py, i64>) -> PyResult<Bound<'py, PyArray1<i64>>> {
    let slice = arr.as_slice()?;
    let out: Vec<i64> =
        py.allow_threads(|| elementwise!(slice, PARALLEL_THRESHOLD, |&x: &i64| x.wrapping_abs()));
    Ok(out.into_pyarray_bound(py))
}

#[pymodule]
fn _turboply(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(dummy_add, m)?)?;
    m.add_function(wrap_pyfunction!(affine_f64, m)?)?;
    m.add_function(wrap_pyfunction!(affine_i64, m)?)?;
    m.add_function(wrap_pyfunction!(abs_f64, m)?)?;
    m.add_function(wrap_pyfunction!(abs_i64, m)?)?;
    Ok(())
}
