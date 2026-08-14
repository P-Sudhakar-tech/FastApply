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
    let out = py.allow_threads(|| {
        if slice.len() >= PARALLEL_THRESHOLD {
            slice.par_iter().map(|&x| a * x + b).collect::<Vec<f64>>()
        } else {
            slice.iter().map(|&x| a * x + b).collect::<Vec<f64>>()
        }
    });
    Ok(out.into_pyarray_bound(py))
}

/// Elementwise `abs(x)` over a f64 array. See [`affine_f64`] for the
/// sequential/parallel threshold rationale.
#[pyfunction]
fn abs_f64<'py>(py: Python<'py>, arr: PyReadonlyArray1<'py, f64>) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let slice = arr.as_slice()?;
    let out = py.allow_threads(|| {
        if slice.len() >= PARALLEL_THRESHOLD {
            slice.par_iter().map(|&x| x.abs()).collect::<Vec<f64>>()
        } else {
            slice.iter().map(|&x| x.abs()).collect::<Vec<f64>>()
        }
    });
    Ok(out.into_pyarray_bound(py))
}

#[pymodule]
fn _turboply(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(dummy_add, m)?)?;
    m.add_function(wrap_pyfunction!(affine_f64, m)?)?;
    m.add_function(wrap_pyfunction!(abs_f64, m)?)?;
    Ok(())
}
