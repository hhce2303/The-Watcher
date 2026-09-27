//! watcher_h264_encoder — SPIKE (see docs/migration/SPIKE-editor-export-encoder.md).
//!
//! Feasibility prototype for a Rust-native replacement of ONLY the H.264
//! **encode** step inside `EditorExportPort`'s re-encode path
//! (`app/adapters/ffmpeg/editor_export_adapter.py::_reencode_trim`), following
//! the same PyO3 + maturin shape as `native/watcher_segments/` (ADR-0006).
//!
//! # Scope (deliberately narrow)
//!
//! This crate takes raw, already-decoded-and-scaled I420 (YUV420 planar)
//! frames and returns an H.264 Annex-B bitstream. It does **not** decode,
//! scale/pad/fps-normalize, encode audio, or mux MP4 — those stay on the
//! existing FFmpeg subprocess. See the SPIKE doc for the rationale (Codex's
//! cross-tension pass: a codec-conditional dual-decode-path for H.264 vs HEVC
//! sources would add real complexity for an unvalidated benefit).
//!
//! # Crate choice
//!
//! `openh264` (crates.io, v0.9.8, default `source` feature) — FFI to Cisco's
//! OpenH264 C library, BSD-2-Clause (wrapper and C core both). The `source`
//! feature statically compiles Cisco's C source at build time via the `cc`
//! crate, so there is no runtime DLL to bundle with PyInstaller (unlike
//! `ffmpeg-next`, which requires libav* DLLs at runtime — the TD-4 footgun in
//! docs/migration/tech-debt-and-best-practices.md).
//!
//! STATUS: SPIKE ONLY. Not wired into `editor_export_adapter.py`. No
//! `ENGINE_READY`-style flag exists yet — see the SPIKE doc for the effort
//! estimate to reach that point (parity oracle + flag + fallback wiring).
//! Also unresolved (flagged, not decided here): the source-build path's
//! MPEG-LA/Cisco patent pass-through nuance needs legal review.

use openh264::encoder::Encoder;
use openh264::formats::YUVBuffer;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// Bytes per I420 (YUV420 planar) frame of `width` x `height`: a full-resolution
/// Y plane plus two quarter-resolution (half width, half height) chroma planes.
/// `libx264`/openh264 both require even dimensions for 4:2:0 subsampling.
fn i420_frame_size(width: u32, height: u32) -> Result<usize, String> {
    if width == 0 || height == 0 {
        return Err(format!("width/height must be > 0 (got {width}x{height})"));
    }
    if !width.is_multiple_of(2) || !height.is_multiple_of(2) {
        return Err(format!(
            "width/height must be even for 4:2:0 (got {width}x{height})"
        ));
    }
    let luma = width as usize * height as usize;
    Ok(luma + luma / 2)
}

/// Pure-Rust implementation of the encode pipeline. Returns the concatenated
/// H.264 Annex-B bitstream (one NAL-unit stream covering every input frame in
/// order) or a human-readable error. Kept free of PyO3 types so it can be
/// exercised by `cargo test` without a Python runtime (mirrors
/// `watcher_segments::compile_clip_impl`).
fn encode_frames_impl(frames: Vec<Vec<u8>>, width: u32, height: u32) -> Result<Vec<u8>, String> {
    if frames.is_empty() {
        return Err("encode_frames: no frames given".to_string());
    }
    let expected = i420_frame_size(width, height)?;
    for (i, frame) in frames.iter().enumerate() {
        if frame.len() != expected {
            return Err(format!(
                "frame {i}: expected {expected} bytes (I420 {width}x{height}), got {} \
                 — caller must hand already-decoded/scaled planar YUV420P frames \
                 (e.g. ffmpeg -pix_fmt yuv420p raw output), one plane-concatenated buffer per frame",
                frame.len()
            ));
        }
    }

    // Default config: openh264 infers frame geometry from the first YUVSource
    // passed to `encode()`. A production adapter would tune bitrate/profile/
    // level via `EncoderConfig`; the spike keeps defaults since quality tuning
    // is out of scope for a feasibility check.
    let mut encoder = Encoder::new().map_err(|e| format!("Encoder::new: {e}"))?;

    let mut bitstream = Vec::new();
    for (i, frame) in frames.into_iter().enumerate() {
        let yuv = YUVBuffer::from_vec(frame, width as usize, height as usize);
        let encoded = encoder
            .encode(&yuv)
            .map_err(|e| format!("encode frame {i}: {e}"))?;
        encoded.write_vec(&mut bitstream);
    }

    if bitstream.is_empty() {
        return Err("encode_frames: encoder produced an empty bitstream".to_string());
    }

    Ok(bitstream)
}

/// Encode `frames` (each a raw I420/YUV420P buffer of `width` x `height`, e.g.
/// FFmpeg's `-pix_fmt yuv420p` raw output) into one concatenated H.264 Annex-B
/// bitstream.
///
/// SPIKE scope: this is the entire surface area evaluated in this pass — no
/// decode, no scale/fps-normalize, no audio, no mux. See module docs and
/// docs/migration/SPIKE-editor-export-encoder.md.
///
/// Returns a Python `bytes` object. NOTE (found only by actually running the
/// Python round-trip, not obvious from the Rust API alone): PyO3's default
/// `Vec<u8>` -> Python conversion produces a `list[int]`, not `bytes` — each
/// byte gets boxed as a separate Python `int` object, which is both the wrong
/// type for a caller expecting a bitstream and needlessly expensive for
/// multi-megabyte output. We convert explicitly via `PyBytes::new` instead.
// clippy::useless_conversion is a known false positive against the code
// `#[pyfunction]` generates for a `Bound<'py, T>` return type (the lint
// attributes itself to the signature, not any line we wrote); `cargo clippy
// --fix` confirms there is nothing to actually change.
#[allow(clippy::useless_conversion)]
#[pyfunction]
fn encode_frames<'py>(
    py: Python<'py>,
    frames: Vec<Vec<u8>>,
    width: u32,
    height: u32,
) -> PyResult<Bound<'py, PyBytes>> {
    let bitstream = py
        .allow_threads(|| encode_frames_impl(frames, width, height))
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new_bound(py, &bitstream))
}

#[pymodule]
fn watcher_h264_encoder(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(encode_frames, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn synthetic_i420_frame(width: u32, height: u32, luma_value: u8) -> Vec<u8> {
        // A flat gray-ish frame: constant luma, neutral (128) chroma. Content
        // doesn't matter for a feasibility round-trip check — only that the
        // encoder accepts the buffer and emits a non-empty bitstream.
        let size = i420_frame_size(width, height).unwrap();
        let luma_len = (width as usize) * (height as usize);
        let mut buf = vec![128u8; size];
        buf[..luma_len].fill(luma_value);
        buf
    }

    #[test]
    fn frame_size_rejects_odd_dimensions() {
        assert!(i420_frame_size(65, 64).is_err());
        assert!(i420_frame_size(64, 65).is_err());
    }

    #[test]
    fn frame_size_rejects_zero_dimensions() {
        assert!(i420_frame_size(0, 64).is_err());
        assert!(i420_frame_size(64, 0).is_err());
    }

    #[test]
    fn frame_size_matches_i420_layout() {
        // 4x4 luma (16) + 2x2 U (4) + 2x2 V (4) = 24.
        assert_eq!(i420_frame_size(4, 4).unwrap(), 24);
    }

    #[test]
    fn encode_frames_rejects_empty_input() {
        let err = encode_frames_impl(Vec::new(), 64, 64).unwrap_err();
        assert!(err.contains("no frames"));
    }

    #[test]
    fn encode_frames_rejects_wrong_buffer_size() {
        let bad_frame = vec![0u8; 10]; // not a valid 64x64 I420 buffer
        let err = encode_frames_impl(vec![bad_frame], 64, 64).unwrap_err();
        assert!(err.contains("expected"), "error was: {err}");
    }

    /// The actual feasibility check: hand a handful of synthetic raw YUV420P
    /// frames to the real openh264 encoder and confirm we get back a non-empty
    /// H.264 bitstream starting with an Annex-B start code. This is NOT a
    /// parity/quality check (no oracle comparison — see the SPIKE doc for what
    /// a future parity oracle would need), only "does the round trip work at
    /// all" on this machine's build of the `source`-compiled OpenH264.
    #[test]
    fn encode_frames_round_trips_synthetic_frames() {
        let width = 64;
        let height = 64;
        let frames = vec![
            synthetic_i420_frame(width, height, 16),
            synthetic_i420_frame(width, height, 128),
            synthetic_i420_frame(width, height, 240),
        ];
        let bitstream = encode_frames_impl(frames, width, height)
            .expect("openh264 encode should succeed for a valid synthetic I420 buffer");

        assert!(!bitstream.is_empty(), "encoder produced no bytes");
        // Annex-B streams start with a 3- or 4-byte start code (00 00 01 / 00 00 00 01).
        let has_start_code =
            bitstream.starts_with(&[0, 0, 0, 1]) || bitstream.starts_with(&[0, 0, 1]);
        assert!(
            has_start_code,
            "bitstream does not start with an Annex-B start code: {:02x?}",
            &bitstream[..bitstream.len().min(8)]
        );
    }
}
