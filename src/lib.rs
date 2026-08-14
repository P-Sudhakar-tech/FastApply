use pyo3::prelude::*;

/// Trivial native function used to verify the PyO3 build/import path end to end.
#[pyfunction]
fn dummy_add(a: i64, b: i64) -> i64 {
    a + b
}

#[pymodule]
fn _turboply(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(dummy_add, m)?)?;
    Ok(())
}
