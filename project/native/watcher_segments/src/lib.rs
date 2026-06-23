//! watcher_segments — native segment-compilation engine (R-6, ADR-0006).
//!
//! Compiled to a Python extension via PyO3/maturin and consumed by
//! `app/adapters/native/rust_segment_compiler.py`.
//!
//! STATUS: scaffold. `ENGINE_READY` is `false`, so the Python factory selects
//! the FFmpeg fallback and never calls `compile_clip` until the lossless
//! MPEG-TS → MP4 remux/concat/keyframe-trim implementation lands and is
//! validated (`cargo test` + the Python parity test).  Flip the flag to `true`
//! only once that is done.

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

/// Read by the Python selector. Keep `false` until the engine is implemented
/// AND validated — a half-finished native build must not be used silently.
const ENGINE_READY: bool = false;

/// Validate the optional trim window. Pure (no I/O) → unit-tested below.
fn check_window(in_point_s: Option<f64>, out_point_s: Option<f64>) -> Result<(), String> {
    if let (Some(i), Some(o)) = (in_point_s, out_point_s) {
        if o < i {
            return Err(format!("out_point ({o}) < in_point ({i})"));
        }
    }
    Ok(())
}

/// Compile/concatenate `sources` into `output`, losslessly, with an optional
/// `[in_point_s, out_point_s]` window. Mirrors `SegmentCompilerPort.compile`.
#[pyfunction]
#[pyo3(signature = (sources, output, in_point_s=None, out_point_s=None))]
fn compile_clip(
    sources: Vec<String>,
    output: String,
    in_point_s: Option<f64>,
    out_point_s: Option<f64>,
) -> PyResult<String> {
    if sources.is_empty() {
        return Err(PyRuntimeError::new_err("compile_clip: no sources"));
    }
    check_window(in_point_s, out_point_s).map_err(PyRuntimeError::new_err)?;

    // TODO(R-6): implement with mpeg2ts-reader (demux + keyframe detection) and
    // muxide (MP4 stream-copy mux). Concatenate `sources` in order on keyframe
    // boundaries, honour the window, write `output`, return it. Then set
    // ENGINE_READY = true.
    let _ = &output;
    Err(PyRuntimeError::new_err(
        "watcher_segments native engine not yet implemented (ENGINE_READY=false)",
    ))
}

#[pymodule]
fn watcher_segments(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("ENGINE_READY", ENGINE_READY)?;
    m.add_function(wrap_pyfunction!(compile_clip, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn engine_not_ready_by_default() {
        assert!(!ENGINE_READY, "scaffold must advertise not-ready");
    }

    #[test]
    fn window_valid() {
        assert!(check_window(Some(1.0), Some(2.0)).is_ok());
        assert!(check_window(None, None).is_ok());
        assert!(check_window(Some(1.0), None).is_ok());
    }

    #[test]
    fn window_inverted_is_error() {
        assert!(check_window(Some(2.0), Some(1.0)).is_err());
    }
}
