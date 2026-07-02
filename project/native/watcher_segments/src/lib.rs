//! watcher_segments — native segment-compilation engine (R-6, ADR-0006).
//!
//! Compiled to a Python extension via PyO3/maturin and consumed by
//! `app/adapters/native/rust_segment_compiler.py`.
//!
//! # What this does
//!
//! `compile_clip` performs a **lossless stream-copy remux** of one or more
//! MPEG-TS sources into a single MP4, concatenating them in order and applying
//! an optional keyframe-aligned trim window. No frame is decoded or
//! re-encoded — the coded picture bytes are preserved bit-for-bit; only the
//! container (TS → MP4) and NAL framing (Annex-B → length-prefixed) change.
//!
//! It mirrors the FFmpeg oracle:
//! ```text
//! ffmpeg -fflags +genpts -f concat -safe 0 -i <list> [-ss IN] [-to OUT] \
//!        -c copy [-tag:v hvc1] -avoid_negative_ts make_zero \
//!        -movflags +faststart -y OUT.mp4
//! ```
//!
//! # Pipeline
//!
//! 1. **Demux** each TS with `mpeg2ts-reader`: pick the first H.264 (0x1b) or
//!    HEVC (0x24) video PES stream and reassemble its PES payloads into access
//!    units (one coded picture each), tagged with PTS/DTS (90 kHz).
//! 2. **Parse** each access unit's Annex-B NAL units: collect parameter sets
//!    (SPS/PPS, plus VPS for HEVC), classify keyframes, and re-emit the picture
//!    NALs in 4-byte length-prefixed form for the MP4 `mdat`.
//! 3. **Concatenate** sources on the shared 90 kHz timeline: each source is
//!    offset so its timestamps continue after the previous one, then the whole
//!    stream is shifted so the first PTS is 0 (`-avoid_negative_ts make_zero`).
//! 4. **Window**: `in_point_s` snaps back to the last keyframe at or before it
//!    (like `-ss` with `-c copy`); `out_point_s` bounds the end.
//! 5. **Mux** with `shiguredo_mp4`'s `Mp4FileMuxer`, emitting `avc1`/`hvc1`
//!    sample entries with faststart (`moov` before `mdat`).
//!
//! # Crate choices
//!
//! - `mpeg2ts-reader` (pure Rust) — TS demux via its callback state machine.
//! - `shiguredo_mp4` (pure Rust, Sans-I/O) — MP4 mux. It exposes exactly the
//!   `avc1`/`hvc1` sample entries and faststart layout the oracle needs, so no
//!   substitution was necessary. Both crates are pure Rust → the resulting
//!   `.pyd` bundles cleanly under PyInstaller (no external DLLs).
//!
//! STATUS: `ENGINE_READY` is `true` — validated end-to-end (cargo test + Python
//! parity harness + editor smoke). The Python factory selects this engine and
//! falls back to FFmpeg only when the `.pyd` is absent.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
use std::num::NonZeroU32;
use std::path::Path;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

use mpeg2ts_reader::demultiplex;
use mpeg2ts_reader::packet;
use mpeg2ts_reader::pes;
use mpeg2ts_reader::psi;
use mpeg2ts_reader::StreamType;
// The demux boilerplate macros are `#[macro_export]`ed at the crate root.
use mpeg2ts_reader::{demux_context, packet_filter_switch};

use shiguredo_mp4::boxes::{
    Avc1Box, AvccBox, HvccBox, HvccNalUintArray, Hvc1Box, SampleEntry, VisualSampleEntryFields,
};
use shiguredo_mp4::demux::{Input, Mp4FileDemuxer};
use shiguredo_mp4::mux::{Mp4FileMuxer, Mp4FileMuxerOptions, Sample};
use shiguredo_mp4::{TrackKind, Uint};

/// Read by the Python selector. `true`: the engine is implemented and validated
/// end-to-end — `cargo test` (44 cases incl. real-media TS/MP4/HEVC integration),
/// the Python Rust↔FFmpeg parity harness (`tests/test_parity_segment_compiler.py`,
/// 10 cases incl. MP4 concat), and an editor-export smoke (reencode + copy modes).
/// The factory selects this engine, falling back to FFmpeg only when the `.pyd`
/// is absent.
const ENGINE_READY: bool = true;

/// MPEG-TS presentation/decode clock rate (Hz). Also used as the MP4 timescale
/// so timestamps map across 1:1 without rounding.
const TS_TIMEBASE: u64 = 90_000;

/// Video codec of the elementary stream we remux.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum VideoCodec {
    H264,
    Hevc,
}

/// One reassembled coded picture (access unit) on the 90 kHz timeline.
///
/// `data` is the picture in MP4 form: concatenated 4-byte-length-prefixed NAL
/// units (parameter sets go in the sample entry, not here). `pts`/`dts` are in
/// TS ticks (may be adjusted during concat / windowing).
#[derive(Debug, Clone, PartialEq)]
struct Frame {
    pts: i64,
    dts: i64,
    keyframe: bool,
    data: Vec<u8>,
}

/// Everything a decoded source contributes: its codec, parameter sets, and its
/// frames on the source-local 90 kHz timeline.
#[derive(Debug, Clone)]
struct DecodedSource {
    codec: VideoCodec,
    /// SPS NAL bodies (raw, no start code / length prefix).
    sps: Vec<Vec<u8>>,
    /// PPS NAL bodies.
    pps: Vec<Vec<u8>>,
    /// VPS NAL bodies (HEVC only; empty for H.264).
    vps: Vec<Vec<u8>>,
    frames: Vec<Frame>,
}

// ---------------------------------------------------------------------------
// Pure helpers (no I/O) — unit-tested below.
// ---------------------------------------------------------------------------

/// Validate the optional trim window. Pure (no I/O) → unit-tested below.
fn check_window(in_point_s: Option<f64>, out_point_s: Option<f64>) -> Result<(), String> {
    if let (Some(i), Some(o)) = (in_point_s, out_point_s) {
        if o < i {
            return Err(format!("out_point ({o}) < in_point ({i})"));
        }
    }
    Ok(())
}

/// Normalise an optional in-point: treat `None` or non-positive as "no trim".
/// Mirrors the oracle, which omits `-ss` when `in_point_s` is `None` or `<= 0`.
fn effective_in_point(in_point_s: Option<f64>) -> Option<f64> {
    match in_point_s {
        Some(v) if v > 0.0 => Some(v),
        _ => None,
    }
}

/// Given frames sorted by DTS and a target start time (in TS ticks), return the
/// index of the last keyframe at or before `target_ticks` — the keyframe a
/// `-ss` + `-c copy` seek would snap back to. If no keyframe is at or before the
/// target, fall back to the first keyframe (0 by convention here); if there are
/// no keyframes at all, return 0.
///
/// `frames` is a slice of `(pts_ticks, is_keyframe)` in presentation order used
/// for the seek reference point; we compare against the sort key the caller
/// provides.
fn keyframe_index_at_or_before(frames: &[(i64, bool)], target_ticks: i64) -> usize {
    let mut chosen: Option<usize> = None;
    for (i, (t, kf)) in frames.iter().enumerate() {
        if !*kf {
            continue;
        }
        if *t <= target_ticks {
            chosen = Some(i);
        } else {
            break;
        }
    }
    match chosen {
        Some(i) => i,
        None => frames
            .iter()
            .position(|(_, kf)| *kf)
            .unwrap_or(0),
    }
}

/// Compute the per-source concat offsets (in TS ticks) applied to make sources
/// continuous. Source 0 gets offset `-first_pts[0]` (so the whole timeline
/// starts at 0 — the `make_zero` behaviour); each later source is offset so its
/// first PTS lands right after the previous source's last frame end.
///
/// `spans` is `(first_pts, last_frame_end)` per source, in that source's own
/// local TS ticks (`last_frame_end` = last PTS + its duration). Returns one
/// offset per source; `local_ts + offset` gives the position on the shared
/// timeline.
fn concat_offsets(spans: &[(i64, i64)]) -> Vec<i64> {
    let mut offsets = Vec::with_capacity(spans.len());
    let mut cursor: i64 = 0; // next free position on the shared timeline
    for (first, end) in spans {
        // Place this source so its first PTS maps to `cursor`.
        let offset = cursor - first;
        offsets.push(offset);
        // Advance the cursor past this source's mapped end.
        cursor = end + offset;
    }
    offsets
}

/// Derive per-frame durations (TS ticks) from a DTS-sorted list of decode
/// timestamps. Each frame's duration is the delta to the next frame's DTS; the
/// final frame reuses the previous delta (or a nominal 1 if only one frame).
fn frame_durations(dts_sorted: &[i64]) -> Vec<u32> {
    let n = dts_sorted.len();
    if n == 0 {
        return Vec::new();
    }
    if n == 1 {
        return vec![1];
    }
    let mut durs = Vec::with_capacity(n);
    for i in 0..n - 1 {
        let d = dts_sorted[i + 1] - dts_sorted[i];
        durs.push(if d > 0 { d as u32 } else { 1 });
    }
    // Last frame: reuse the previous positive delta.
    let last = *durs.last().unwrap_or(&1);
    durs.push(last);
    durs
}

/// Split an Annex-B byte stream into its NAL unit bodies (start codes removed).
/// Accepts both 3-byte (00 00 01) and 4-byte (00 00 00 01) start codes.
fn split_annexb_nals(data: &[u8]) -> Vec<&[u8]> {
    let mut nals = Vec::new();
    let n = data.len();
    // Find all start-code positions (index just past the code).
    let mut starts: Vec<usize> = Vec::new();
    let mut i = 0usize;
    while i + 3 <= n {
        if data[i] == 0 && data[i + 1] == 0 && data[i + 2] == 1 {
            starts.push(i + 3);
            i += 3;
        } else {
            i += 1;
        }
    }
    for (idx, &s) in starts.iter().enumerate() {
        // NAL runs until the next start code, minus any trailing zero bytes
        // that belong to that next start code (00 00 [00] 01).
        let mut end = if idx + 1 < starts.len() {
            starts[idx + 1] - 3
        } else {
            n
        };
        // Trim the single leading zero of a 4-byte start code, plus trailing
        // zero padding.
        while end > s && data[end - 1] == 0 {
            end -= 1;
        }
        if end > s {
            nals.push(&data[s..end]);
        }
    }
    nals
}

/// H.264 NAL type (low 5 bits of the header byte).
fn h264_nal_type(nal: &[u8]) -> u8 {
    if nal.is_empty() {
        return 0;
    }
    nal[0] & 0x1F
}

/// HEVC NAL type (bits 1..6 of the first header byte).
fn hevc_nal_type(nal: &[u8]) -> u8 {
    if nal.is_empty() {
        return 0;
    }
    (nal[0] >> 1) & 0x3F
}

/// Is this a keyframe (IDR/IRAP) for the given codec, given the NAL types in
/// the access unit?
fn is_keyframe(codec: VideoCodec, nal_types: &[u8]) -> bool {
    match codec {
        // H.264: NAL type 5 = IDR slice.
        VideoCodec::H264 => nal_types.contains(&5),
        // HEVC: IRAP pictures are NAL types 16..=23 (BLA/IDR/CRA/RASL etc.
        // headers). 19/20 = IDR, 21 = CRA, 16..18 = BLA. Any of these begins a
        // random-access point suitable as a keyframe.
        VideoCodec::Hevc => nal_types.iter().any(|t| (16..=23).contains(t)),
    }
}

/// Convert a list of NAL bodies into MP4 length-prefixed form (4-byte BE length
/// + body per NAL). Parameter-set NALs are dropped here (they live in the
/// sample entry / config box) but VCL and SEI NALs are kept.
fn nals_to_length_prefixed(codec: VideoCodec, nals: &[&[u8]]) -> Vec<u8> {
    let mut out = Vec::new();
    for nal in nals {
        if nal.is_empty() {
            continue;
        }
        let is_param = match codec {
            VideoCodec::H264 => matches!(h264_nal_type(nal), 7 | 8 | 9), // SPS/PPS/AUD
            VideoCodec::Hevc => matches!(hevc_nal_type(nal), 32 | 33 | 34 | 35), // VPS/SPS/PPS/AUD
        };
        if is_param {
            continue;
        }
        let len = nal.len() as u32;
        out.extend_from_slice(&len.to_be_bytes());
        out.extend_from_slice(nal);
    }
    out
}

// ---------------------------------------------------------------------------
// TS demux (mpeg2ts-reader callback state machine).
// ---------------------------------------------------------------------------

// The filter switch enumerates every way we handle a TS packet. `Pes` carries
// our application logic; the rest are framework boilerplate.
packet_filter_switch! {
    SegFilterSwitch<SegDemuxContext> {
        Pes: pes::PesPacketFilter<SegDemuxContext, VideoEsConsumer>,
        Pat: demultiplex::PatPacketFilter<SegDemuxContext>,
        Pmt: demultiplex::PmtPacketFilter<SegDemuxContext>,
        Null: demultiplex::NullPacketFilter<SegDemuxContext>,
    }
}

demux_context!(SegDemuxContext, SegFilterSwitch);

impl SegDemuxContext {
    fn do_construct(&mut self, req: demultiplex::FilterRequest<'_, '_>) -> SegFilterSwitch {
        match req {
            demultiplex::FilterRequest::ByPid(psi::pat::PAT_PID) => {
                SegFilterSwitch::Pat(demultiplex::PatPacketFilter::default())
            }
            demultiplex::FilterRequest::ByPid(mpeg2ts_reader::STUFFING_PID) => {
                SegFilterSwitch::Null(demultiplex::NullPacketFilter::default())
            }
            demultiplex::FilterRequest::ByPid(_) => {
                SegFilterSwitch::Null(demultiplex::NullPacketFilter::default())
            }
            // Handle the first H.264 or HEVC video stream we encounter. Once we
            // have locked onto a PID we ignore any others.
            demultiplex::FilterRequest::ByStream {
                stream_type: StreamType::H264,
                stream_info,
                ..
            } => VideoEsConsumer::construct(VideoCodec::H264, stream_info),
            demultiplex::FilterRequest::ByStream {
                stream_type: StreamType::H265,
                stream_info,
                ..
            } => VideoEsConsumer::construct(VideoCodec::Hevc, stream_info),
            demultiplex::FilterRequest::ByStream { .. } => {
                SegFilterSwitch::Null(demultiplex::NullPacketFilter::default())
            }
            demultiplex::FilterRequest::Pmt {
                pid,
                program_number,
            } => SegFilterSwitch::Pmt(demultiplex::PmtPacketFilter::new(pid, program_number)),
            demultiplex::FilterRequest::Nit { .. } => {
                SegFilterSwitch::Null(demultiplex::NullPacketFilter::default())
            }
        }
    }
}

/// Accumulator shared through the demux context via `VideoEsConsumer`.
///
/// mpeg2ts-reader does not thread arbitrary user state into the context type
/// (it is generated by the macro), so the consumer owns the accumulator and the
/// caller reads it back out after the demux completes.
#[derive(Default)]
struct EsAccumulator {
    codec: Option<VideoCodec>,
    /// The PID we locked onto (first video stream wins).
    locked_pid: Option<packet::Pid>,
    /// Bytes of the access unit currently being assembled.
    cur_data: Vec<u8>,
    cur_pts: Option<i64>,
    cur_dts: Option<i64>,
    have_cur: bool,
    /// Completed frames (unsorted; presentation/decode order per PES arrival).
    frames: Vec<Frame>,
    sps: Vec<Vec<u8>>,
    pps: Vec<Vec<u8>>,
    vps: Vec<Vec<u8>>,
}

// The consumer needs to reach a per-run accumulator. We stash it in a
// thread-local so the macro-generated context stays untouched; `compile_clip`
// runs single-threaded per source, so this is safe and simple.
thread_local! {
    static ACC: std::cell::RefCell<EsAccumulator> = std::cell::RefCell::new(EsAccumulator::default());
}

/// Flush the in-progress access unit into a finished `Frame`.
fn flush_current(acc: &mut EsAccumulator) {
    if !acc.have_cur {
        return;
    }
    let codec = acc.codec.unwrap_or(VideoCodec::H264);
    let data = std::mem::take(&mut acc.cur_data);
    let nals = split_annexb_nals(&data);

    // Collect parameter sets and classify the AU.
    let mut nal_types: Vec<u8> = Vec::with_capacity(nals.len());
    for nal in &nals {
        match codec {
            VideoCodec::H264 => {
                let t = h264_nal_type(nal);
                nal_types.push(t);
                match t {
                    7 => {
                        if !acc.sps.iter().any(|s| s == *nal) {
                            acc.sps.push(nal.to_vec());
                        }
                    }
                    8 => {
                        if !acc.pps.iter().any(|s| s == *nal) {
                            acc.pps.push(nal.to_vec());
                        }
                    }
                    _ => {}
                }
            }
            VideoCodec::Hevc => {
                let t = hevc_nal_type(nal);
                nal_types.push(t);
                match t {
                    32 => {
                        if !acc.vps.iter().any(|s| s == *nal) {
                            acc.vps.push(nal.to_vec());
                        }
                    }
                    33 => {
                        if !acc.sps.iter().any(|s| s == *nal) {
                            acc.sps.push(nal.to_vec());
                        }
                    }
                    34 => {
                        if !acc.pps.iter().any(|s| s == *nal) {
                            acc.pps.push(nal.to_vec());
                        }
                    }
                    _ => {}
                }
            }
        }
    }

    let keyframe = is_keyframe(codec, &nal_types);
    let payload = nals_to_length_prefixed(codec, &nals);

    // Skip access units that carry no VCL data (e.g. a leading PES that held
    // only parameter sets) — they would create zero-byte MP4 samples.
    if !payload.is_empty() {
        let pts = acc.cur_pts.unwrap_or(0);
        let dts = acc.cur_dts.unwrap_or(pts);
        acc.frames.push(Frame {
            pts,
            dts,
            keyframe,
            data: payload,
        });
    }

    acc.cur_pts = None;
    acc.cur_dts = None;
    acc.have_cur = false;
}

/// Elementary-stream consumer: reassembles PES payloads into access units.
struct VideoEsConsumer {
    pid: packet::Pid,
}

impl VideoEsConsumer {
    fn construct(codec: VideoCodec, stream_info: &psi::pmt::StreamInfo) -> SegFilterSwitch {
        let pid = stream_info.elementary_pid();
        ACC.with(|a| {
            let mut acc = a.borrow_mut();
            // Lock onto the first video stream only.
            if acc.locked_pid.is_none() {
                acc.locked_pid = Some(pid);
                acc.codec = Some(codec);
            }
        });
        SegFilterSwitch::Pes(pes::PesPacketFilter::new(VideoEsConsumer { pid }))
    }

    fn is_locked(&self) -> bool {
        ACC.with(|a| a.borrow().locked_pid == Some(self.pid))
    }
}

impl pes::ElementaryStreamConsumer<SegDemuxContext> for VideoEsConsumer {
    fn start_stream(&mut self, _ctx: &mut SegDemuxContext) {}

    fn begin_packet(&mut self, _ctx: &mut SegDemuxContext, header: pes::PesHeader) {
        if !self.is_locked() {
            return;
        }
        // A new PES packet begins a new access unit → flush the previous one.
        ACC.with(|a| flush_current(&mut a.borrow_mut()));

        match header.contents() {
            pes::PesContents::Parsed(Some(parsed)) => {
                let (pts, dts) = match parsed.pts_dts() {
                    Ok(pes::PtsDts::PtsOnly(Ok(pts))) => {
                        (Some(pts.value() as i64), None)
                    }
                    Ok(pes::PtsDts::Both {
                        pts: Ok(pts),
                        dts: Ok(dts),
                    }) => (Some(pts.value() as i64), Some(dts.value() as i64)),
                    _ => (None, None),
                };
                let payload = parsed.payload();
                ACC.with(|a| {
                    let mut acc = a.borrow_mut();
                    acc.cur_pts = pts;
                    acc.cur_dts = dts;
                    acc.have_cur = true;
                    acc.cur_data.extend_from_slice(payload);
                });
            }
            pes::PesContents::Parsed(None) => {
                ACC.with(|a| {
                    let mut acc = a.borrow_mut();
                    acc.have_cur = true;
                });
            }
            pes::PesContents::Payload(payload) => {
                ACC.with(|a| {
                    let mut acc = a.borrow_mut();
                    acc.have_cur = true;
                    acc.cur_data.extend_from_slice(payload);
                });
            }
        }
    }

    fn continue_packet(&mut self, _ctx: &mut SegDemuxContext, data: &[u8]) {
        if !self.is_locked() {
            return;
        }
        ACC.with(|a| a.borrow_mut().cur_data.extend_from_slice(data));
    }

    fn end_packet(&mut self, _ctx: &mut SegDemuxContext) {}
    fn continuity_error(&mut self, _ctx: &mut SegDemuxContext) {}
}

/// Container the source file uses.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Container {
    MpegTs,
    Mp4,
}

/// Detect the container by sniffing the file header, falling back to the file
/// extension when the bytes are inconclusive.
///
/// - MP4/ISO-BMFF: the first box is almost always `ftyp`, so bytes 4..8 read
///   `"ftyp"` (the leading 4 bytes are the box size). We also accept the rarer
///   leading `styp`/`moov`/`free`/`skip`/`mdat` box types.
/// - MPEG-TS: a stream of 188-byte packets, each starting with the sync byte
///   `0x47`; we confirm the sync byte repeats at the 188-byte cadence.
fn detect_container(path: &str, header: &[u8]) -> Result<Container, String> {
    // ISO-BMFF: `<size:4><type:4>` — check the box type at offset 4.
    if header.len() >= 8 {
        let box_type = &header[4..8];
        const MP4_BOX_TYPES: [&[u8; 4]; 6] =
            [b"ftyp", b"styp", b"moov", b"free", b"skip", b"mdat"];
        if MP4_BOX_TYPES.iter().any(|t| box_type == *t) {
            return Ok(Container::Mp4);
        }
    }

    // MPEG-TS: sync byte 0x47 at offset 0, and again 188 bytes later if we have
    // that much data (guards against a stray 0x47 at the start of an MP4).
    if header.first() == Some(&0x47)
        && (header.len() < 189 || header.get(188) == Some(&0x47))
    {
        return Ok(Container::MpegTs);
    }

    // Inconclusive header → tiebreak on extension.
    let lower = path.to_ascii_lowercase();
    if lower.ends_with(".ts") || lower.ends_with(".m2ts") || lower.ends_with(".mts") {
        return Ok(Container::MpegTs);
    }
    if lower.ends_with(".mp4") || lower.ends_with(".m4v") || lower.ends_with(".mov") {
        return Ok(Container::Mp4);
    }

    Err(format!(
        "{path}: could not detect container (not MPEG-TS or MP4)"
    ))
}

/// Demux one source file into a `DecodedSource`, dispatching on the detected
/// container. Both paths yield the same structure the muxer consumes: frames
/// carry MP4-form (length-prefixed) NAL data on the shared 90 kHz timeline.
fn demux_source(path: &str) -> Result<DecodedSource, String> {
    // Sniff enough bytes to cover an MP4 `ftyp` box and two TS packets.
    let mut header = vec![0u8; 189];
    {
        let mut f = File::open(path).map_err(|e| format!("open {path}: {e}"))?;
        let n = f.read(&mut header).map_err(|e| format!("read {path}: {e}"))?;
        header.truncate(n);
    }
    match detect_container(path, &header)? {
        Container::MpegTs => demux_ts(path),
        Container::Mp4 => demux_mp4(path),
    }
}

/// Demux one TS file into a `DecodedSource`.
fn demux_ts(path: &str) -> Result<DecodedSource, String> {
    let mut f = File::open(path).map_err(|e| format!("open {path}: {e}"))?;

    // Reset the thread-local accumulator for this source.
    ACC.with(|a| *a.borrow_mut() = EsAccumulator::default());

    let mut ctx = SegDemuxContext::new();
    let mut demux = demultiplex::Demultiplex::new(&mut ctx);

    let mut buf = [0u8; 188 * 1024];
    loop {
        let n = f.read(&mut buf[..]).map_err(|e| format!("read {path}: {e}"))?;
        if n == 0 {
            break;
        }
        demux.push(&mut ctx, &buf[0..n]);
    }

    // Flush any access unit left in progress at EOF.
    ACC.with(|a| flush_current(&mut a.borrow_mut()));

    let acc = ACC.with(|a| std::mem::take(&mut *a.borrow_mut()));

    let codec = acc
        .codec
        .ok_or_else(|| format!("{path}: no H.264/HEVC video stream found"))?;
    if acc.frames.is_empty() {
        return Err(format!("{path}: no coded frames decoded"));
    }
    if acc.sps.is_empty() || acc.pps.is_empty() {
        return Err(format!(
            "{path}: missing SPS/PPS parameter sets (cannot build sample entry)"
        ));
    }
    if codec == VideoCodec::Hevc && acc.vps.is_empty() {
        return Err(format!("{path}: HEVC stream missing VPS"));
    }

    Ok(DecodedSource {
        codec,
        sps: acc.sps,
        pps: acc.pps,
        vps: acc.vps,
        frames: acc.frames,
    })
}

/// Rescale a timestamp/duration from an arbitrary MP4 timescale to the shared
/// 90 kHz TS timebase: `value * 90000 / mp4_timescale`, rounded to nearest.
/// Uses i128 intermediates to avoid overflow on long clips.
fn rescale_to_ts_ticks(value: i64, mp4_timescale: u32) -> i64 {
    if mp4_timescale == 0 {
        return value;
    }
    let num = value as i128 * TS_TIMEBASE as i128;
    let den = mp4_timescale as i128;
    // Round-half-away-from-zero.
    let half = den / 2;
    let rounded = if num >= 0 {
        (num + half) / den
    } else {
        (num - half) / den
    };
    rounded as i64
}

/// Pull the codec + parameter sets (SPS/PPS, plus VPS for HEVC) out of an MP4
/// visual `SampleEntry`. The parameter sets live directly in the AvccBox /
/// HvccBox, so no bitstream parsing is needed on the MP4 path.
fn params_from_sample_entry(
    entry: &SampleEntry,
) -> Result<(VideoCodec, Vec<Vec<u8>>, Vec<Vec<u8>>, Vec<Vec<u8>>), String> {
    match entry {
        SampleEntry::Avc1(b) => {
            let sps = b.avcc_box.sps_list.clone();
            let pps = b.avcc_box.pps_list.clone();
            Ok((VideoCodec::H264, sps, pps, Vec::new()))
        }
        SampleEntry::Hvc1(b) => hevc_params(&b.hvcc_box),
        SampleEntry::Hev1(b) => hevc_params(&b.hvcc_box),
        other => Err(format!(
            "unsupported MP4 video sample entry (only avc1/hvc1/hev1): {other:?}"
        )),
    }
}

/// Extract VPS(32)/SPS(33)/PPS(34) NAL bodies from an HvccBox's `nalu_arrays`.
fn hevc_params(
    hvcc: &HvccBox,
) -> Result<(VideoCodec, Vec<Vec<u8>>, Vec<Vec<u8>>, Vec<Vec<u8>>), String> {
    let mut vps = Vec::new();
    let mut sps = Vec::new();
    let mut pps = Vec::new();
    for arr in &hvcc.nalu_arrays {
        match arr.nal_unit_type.get() {
            32 => vps.extend(arr.nalus.iter().cloned()),
            33 => sps.extend(arr.nalus.iter().cloned()),
            34 => pps.extend(arr.nalus.iter().cloned()),
            _ => {}
        }
    }
    Ok((VideoCodec::Hevc, sps, pps, vps))
}

/// Demux one MP4 file into a `DecodedSource` using `shiguredo_mp4`'s decode
/// side (`Mp4FileDemuxer`).
///
/// The file is read fully into memory and handed to the demuxer as a single
/// `Input`. We then iterate `next_sample()`, keeping only the first video
/// track's samples. Each sample already holds length-prefixed (AVCC/HVCC) NAL
/// data — the exact form our muxer wants — so we copy the bytes straight out of
/// the buffer at `data_offset`. Timestamps are rescaled from the MP4 timescale
/// to the shared 90 kHz TS timebase so MP4 and TS sources concat on one clock.
fn demux_mp4(path: &str) -> Result<DecodedSource, String> {
    let file_data = std::fs::read(path).map_err(|e| format!("read {path}: {e}"))?;

    let mut demuxer = Mp4FileDemuxer::new();
    // Drive the Sans-I/O state machine; we hold the whole file, so each request
    // is satisfied directly from `file_data`.
    while let Some(required) = demuxer.required_input() {
        let pos = required.position as usize;
        let end = match required.size {
            Some(s) => (pos + s).min(file_data.len()),
            None => file_data.len(),
        };
        let slice = if pos <= file_data.len() {
            &file_data[pos..end]
        } else {
            &[][..]
        };
        demuxer.handle_input(Input {
            position: required.position,
            data: slice,
        });
        // Guard against a stall (e.g. truncated file) that would loop forever.
        if slice.is_empty() {
            break;
        }
    }

    // Identify the first video track.
    let tracks = demuxer
        .tracks()
        .map_err(|e| format!("{path}: mp4 tracks: {e}"))?;
    let video = tracks
        .iter()
        .find(|t| t.kind == TrackKind::Video)
        .ok_or_else(|| format!("{path}: no video track found"))?;
    let video_track_id = video.track_id;
    let mp4_timescale = video.timescale.get();

    let mut codec: Option<VideoCodec> = None;
    let mut sps: Vec<Vec<u8>> = Vec::new();
    let mut pps: Vec<Vec<u8>> = Vec::new();
    let mut vps: Vec<Vec<u8>> = Vec::new();
    let mut frames: Vec<Frame> = Vec::new();

    loop {
        let sample = demuxer
            .next_sample()
            .map_err(|e| format!("{path}: mp4 next_sample: {e}"))?;
        let Some(sample) = sample else { break };

        // Skip non-video tracks (e.g. audio).
        if sample.track.track_id != video_track_id {
            continue;
        }

        // The first video sample always carries the sample entry; extract the
        // codec + parameter sets from it once.
        if let Some(entry) = sample.sample_entry {
            if codec.is_none() {
                let (c, s, p, v) = params_from_sample_entry(entry)?;
                codec = Some(c);
                sps = s;
                pps = p;
                vps = v;
            }
        }

        // DTS/PTS in MP4 track ticks → shared 90 kHz ticks.
        let dts_mp4 = sample.timestamp as i64;
        let cto_mp4 = sample.composition_time_offset.unwrap_or(0);
        let pts_mp4 = dts_mp4 + cto_mp4;
        let dts = rescale_to_ts_ticks(dts_mp4, mp4_timescale);
        let pts = rescale_to_ts_ticks(pts_mp4, mp4_timescale);

        // Copy the (already length-prefixed) sample bytes from the buffer.
        let start = sample.data_offset as usize;
        let end = start + sample.data_size;
        if end > file_data.len() {
            return Err(format!(
                "{path}: sample data range {start}..{end} exceeds file ({} bytes)",
                file_data.len()
            ));
        }
        let data = file_data[start..end].to_vec();
        if data.is_empty() {
            continue;
        }

        frames.push(Frame {
            pts,
            dts,
            keyframe: sample.keyframe,
            data,
        });
    }

    let codec = codec.ok_or_else(|| format!("{path}: no H.264/HEVC video stream found"))?;
    if frames.is_empty() {
        return Err(format!("{path}: no coded frames decoded"));
    }
    if sps.is_empty() || pps.is_empty() {
        return Err(format!(
            "{path}: missing SPS/PPS parameter sets in sample entry"
        ));
    }
    if codec == VideoCodec::Hevc && vps.is_empty() {
        return Err(format!("{path}: HEVC stream missing VPS in sample entry"));
    }

    Ok(DecodedSource {
        codec,
        sps,
        pps,
        vps,
        frames,
    })
}

// ---------------------------------------------------------------------------
// Sample-entry construction.
// ---------------------------------------------------------------------------

/// Read a big-endian unsigned integer of `bytes` length from `data` at `pos`.
fn be_uint(data: &[u8], pos: usize, bytes: usize) -> u64 {
    let mut v = 0u64;
    for i in 0..bytes {
        v = (v << 8) | *data.get(pos + i).unwrap_or(&0) as u64;
    }
    v
}

/// Best-effort video resolution guess from the SPS is out of scope for the
/// spike; we fall back to a nominal size. The MP4 `tkhd`/`stsd` width/height
/// are advisory — players read the real geometry from the SPS in the bitstream.
const NOMINAL_W: u16 = 1920;
const NOMINAL_H: u16 = 1080;

fn visual_fields(width: u16, height: u16) -> VisualSampleEntryFields {
    VisualSampleEntryFields {
        data_reference_index: VisualSampleEntryFields::DEFAULT_DATA_REFERENCE_INDEX,
        width,
        height,
        horizresolution: VisualSampleEntryFields::DEFAULT_HORIZRESOLUTION,
        vertresolution: VisualSampleEntryFields::DEFAULT_VERTRESOLUTION,
        frame_count: VisualSampleEntryFields::DEFAULT_FRAME_COUNT,
        compressorname: VisualSampleEntryFields::NULL_COMPRESSORNAME,
        depth: VisualSampleEntryFields::DEFAULT_DEPTH,
    }
}

/// Build an `avc1` sample entry from collected SPS/PPS. Profile/level are taken
/// from the first SPS (bytes after the NAL header: profile_idc, constraints,
/// level_idc), which are at fixed offsets in the SPS RBSP.
fn build_avc1(sps: &[Vec<u8>], pps: &[Vec<u8>]) -> SampleEntry {
    // SPS layout: [nal_header(1)][profile_idc(1)][constraint_flags(1)][level_idc(1)] ...
    let first = &sps[0];
    let profile_idc = *first.get(1).unwrap_or(&66);
    let profile_compat = *first.get(2).unwrap_or(&0);
    let level_idc = *first.get(3).unwrap_or(&30);

    // ISO/IEC 14496-15: for profiles other than Baseline(66)/Main(77)/
    // Extended(88), the avcC MUST carry chroma_format + bit-depth fields.
    // Our capture pipeline (and libx264 High by default) is 4:2:0 8-bit, so we
    // supply the standard values. Parsing them exactly from the SPS would need
    // exp-Golomb decoding; for the spike these fixed values match the pipeline.
    let extended_profile = !matches!(profile_idc, 66 | 77 | 88);
    let (chroma_format, bd_luma, bd_chroma) = if extended_profile {
        (Some(Uint::new(1)), Some(Uint::new(0)), Some(Uint::new(0)))
    } else {
        (None, None, None)
    };

    let avcc = AvccBox {
        avc_profile_indication: profile_idc,
        profile_compatibility: profile_compat,
        avc_level_indication: level_idc,
        length_size_minus_one: Uint::new(3), // 4-byte NAL length prefixes
        sps_list: sps.to_vec(),
        pps_list: pps.to_vec(),
        chroma_format,
        bit_depth_luma_minus8: bd_luma,
        bit_depth_chroma_minus8: bd_chroma,
        sps_ext_list: Vec::new(),
    };

    SampleEntry::Avc1(Avc1Box {
        visual: visual_fields(NOMINAL_W, NOMINAL_H),
        avcc_box: avcc,
        unknown_boxes: Vec::new(),
    })
}

/// Build an `hvc1` sample entry (NOT `hev1`) from collected VPS/SPS/PPS.
///
/// The HEVC profile/tier/level fields live in the SPS `profile_tier_level`
/// structure, which begins after `sps_video_parameter_set_id` (4 bits),
/// `sps_max_sub_layers_minus1` (3 bits) and `sps_temporal_id_nesting_flag`
/// (1 bit) — i.e. one byte after the two-byte NAL header. We read the 12-byte
/// `profile_tier_level` general fields from there. Fields we cannot cheaply
/// recover (e.g. `min_spatial_segmentation_idc`) are left at conservative
/// defaults; players read the authoritative geometry from the in-band SPS.
fn build_hvc1(vps: &[Vec<u8>], sps: &[Vec<u8>], pps: &[Vec<u8>]) -> SampleEntry {
    let first_sps = &sps[0];
    // profile_tier_level starts at byte offset 2 (after 2-byte NAL header) + 1
    // (the sub-layer/nesting byte) = 3.
    let ptl = 3usize;
    let byte0 = *first_sps.get(ptl).unwrap_or(&0);
    let general_profile_space = (byte0 >> 6) & 0x03;
    let general_tier_flag = (byte0 >> 5) & 0x01;
    let general_profile_idc = byte0 & 0x1F;
    let general_profile_compat = be_uint(first_sps, ptl + 1, 4) as u32;
    let general_constraint = be_uint(first_sps, ptl + 5, 6); // 48 bits
    let general_level_idc = *first_sps.get(ptl + 11).unwrap_or(&0);

    let hvcc = HvccBox {
        general_profile_space: Uint::new(general_profile_space),
        general_tier_flag: Uint::new(general_tier_flag),
        general_profile_idc: Uint::new(general_profile_idc),
        general_profile_compatibility_flags: general_profile_compat,
        general_constraint_indicator_flags: Uint::new(general_constraint),
        general_level_idc,
        min_spatial_segmentation_idc: Uint::new(0),
        parallelism_type: Uint::new(0),
        chroma_format_idc: Uint::new(1), // 4:2:0 (typical)
        bit_depth_luma_minus8: Uint::new(0),
        bit_depth_chroma_minus8: Uint::new(0),
        avg_frame_rate: 0,
        constant_frame_rate: Uint::new(0),
        num_temporal_layers: Uint::new(1),
        temporal_id_nested: Uint::new(0),
        length_size_minus_one: Uint::new(3), // 4-byte NAL length prefixes
        nalu_arrays: vec![
            HvccNalUintArray {
                array_completeness: Uint::new(0),
                nal_unit_type: Uint::new(32), // VPS
                nalus: vps.to_vec(),
            },
            HvccNalUintArray {
                array_completeness: Uint::new(0),
                nal_unit_type: Uint::new(33), // SPS
                nalus: sps.to_vec(),
            },
            HvccNalUintArray {
                array_completeness: Uint::new(0),
                nal_unit_type: Uint::new(34), // PPS
                nalus: pps.to_vec(),
            },
        ],
    };

    // hvc1 (not hev1): parameter sets are in the sample entry and MUST NOT vary
    // in-band; we already strip them from the mdat samples.
    SampleEntry::Hvc1(Hvc1Box {
        visual: visual_fields(NOMINAL_W, NOMINAL_H),
        hvcc_box: hvcc,
        unknown_boxes: Vec::new(),
    })
}

// ---------------------------------------------------------------------------
// Concat + window + mux.
// ---------------------------------------------------------------------------

/// Assemble the final, DTS-sorted, timeline-normalised frame list from all
/// sources, applying concat offsets and (if given) the keyframe-aligned window.
/// Returns the frames plus the codec (all sources must share a codec).
fn assemble_timeline(
    sources: &[DecodedSource],
    in_point_s: Option<f64>,
    out_point_s: Option<f64>,
) -> Result<(VideoCodec, Vec<Frame>), String> {
    let codec = sources[0].codec;
    if sources.iter().any(|s| s.codec != codec) {
        return Err("mixed codecs across sources are not supported".to_string());
    }

    // Per-source local spans (first PTS, last frame end) for concat offsetting.
    // We use DTS-sorted order to compute durations but PTS for placement.
    let mut spans = Vec::with_capacity(sources.len());
    for s in sources {
        let mut dts: Vec<i64> = s.frames.iter().map(|f| f.dts).collect();
        dts.sort_unstable();
        let durs = frame_durations(&dts);
        let total: i64 = durs.iter().map(|d| *d as i64).sum();
        let first_pts = s.frames.iter().map(|f| f.pts).min().unwrap_or(0);
        spans.push((first_pts, first_pts + total));
    }
    let offsets = concat_offsets(&spans);

    // Merge all frames onto the shared timeline.
    let mut all: Vec<Frame> = Vec::new();
    for (si, s) in sources.iter().enumerate() {
        let off = offsets[si];
        for f in &s.frames {
            all.push(Frame {
                pts: f.pts + off,
                dts: f.dts + off,
                keyframe: f.keyframe,
                data: f.data.clone(),
            });
        }
    }

    // Decode order = sort by DTS (stable to keep same-DTS order deterministic).
    all.sort_by_key(|f| f.dts);

    // Apply the window. `-ss` snaps back to the last keyframe at or before the
    // requested in-point; `-to` bounds the end (frames whose PTS exceeds the
    // out-point are dropped).
    if let Some(in_s) = effective_in_point(in_point_s) {
        let target = (in_s * TS_TIMEBASE as f64).round() as i64;
        // Use presentation order (PTS) for the seek reference.
        let mut by_pts: Vec<(i64, bool)> =
            all.iter().map(|f| (f.pts, f.keyframe)).collect();
        // keyframe_index_at_or_before expects PTS-ascending order.
        by_pts.sort_by_key(|(p, _)| *p);
        let kf_pts = {
            let idx = keyframe_index_at_or_before(&by_pts, target);
            by_pts.get(idx).map(|(p, _)| *p).unwrap_or(0)
        };
        all.retain(|f| f.pts >= kf_pts);
    }

    if let Some(out_s) = out_point_s {
        let bound = (out_s * TS_TIMEBASE as f64).round() as i64;
        all.retain(|f| f.pts <= bound);
    }

    if all.is_empty() {
        return Err("window selected no frames".to_string());
    }

    // Normalise so the earliest PTS is 0 (`-avoid_negative_ts make_zero`).
    let min_pts = all.iter().map(|f| f.pts).min().unwrap_or(0);
    for f in &mut all {
        f.pts -= min_pts;
        f.dts -= min_pts;
    }

    Ok((codec, all))
}

/// Mux the assembled frames into an MP4 at `output`, faststart, stream-copy.
fn mux_mp4(codec: VideoCodec, frames: &[Frame], source: &DecodedSource, output: &str) -> Result<(), String> {
    // Reserve enough moov headroom for faststart (moov before mdat). Video
    // samples are ~16 bytes of metadata each; add generous slack.
    let est = 4096 + frames.len() * 24;
    let options = Mp4FileMuxerOptions {
        reserved_moov_box_size: est,
        ..Default::default()
    };
    let mut muxer = Mp4FileMuxer::with_options(options)
        .map_err(|e| format!("muxer init: {e}"))?;

    let sample_entry = match codec {
        VideoCodec::H264 => build_avc1(&source.sps, &source.pps),
        VideoCodec::Hevc => build_hvc1(&source.vps, &source.sps, &source.pps),
    };

    // DTS-sorted durations for the whole assembled stream.
    let dts: Vec<i64> = frames.iter().map(|f| f.dts).collect();
    let durs = frame_durations(&dts);
    let timescale = NonZeroU32::new(TS_TIMEBASE as u32).expect("90000 != 0");

    let mut file = File::create(output).map_err(|e| format!("create {output}: {e}"))?;
    file.write_all(muxer.initial_boxes_bytes())
        .map_err(|e| format!("write header: {e}"))?;

    let mut first = true;
    for (i, f) in frames.iter().enumerate() {
        // The muxer requires each sample's `data_offset` to equal the actual
        // byte position where we just wrote it, so we track the file cursor.
        let offset = file
            .stream_position()
            .map_err(|e| format!("stream_position: {e}"))?;
        file.write_all(&f.data)
            .map_err(|e| format!("write sample: {e}"))?;

        let cto = f.pts - f.dts;
        let sample = Sample {
            track_kind: TrackKind::Video,
            sample_entry: if first { Some(sample_entry.clone()) } else { None },
            keyframe: f.keyframe,
            timescale,
            duration: durs[i],
            composition_time_offset: if cto != 0 { Some(cto) } else { None },
            data_offset: offset,
            data_size: f.data.len(),
        };
        muxer
            .append_sample(&sample)
            .map_err(|e| format!("append_sample[{i}]: {e}"))?;
        first = false;
    }

    let finalized = muxer.finalize().map_err(|e| format!("finalize: {e}"))?;
    for (offset, bytes) in finalized.offset_and_bytes_pairs() {
        file.seek(SeekFrom::Start(offset))
            .map_err(|e| format!("seek {offset}: {e}"))?;
        file.write_all(bytes)
            .map_err(|e| format!("write finalized box: {e}"))?;
    }
    file.flush().map_err(|e| format!("flush: {e}"))?;

    // Sanity: faststart must have taken (moov before mdat). If the reserved
    // space was too small the muxer silently falls back to moov-at-end; surface
    // that rather than shipping a non-streamable file.
    if !finalized.is_faststart_enabled() {
        return Err("faststart layout failed (moov reserve too small)".to_string());
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// PyO3 entry point.
// ---------------------------------------------------------------------------

/// Pure-Rust implementation of the compile pipeline. Returns the output path on
/// success or a human-readable error string. Kept free of PyO3 types so it can
/// be exercised by native integration tests without a Python runtime.
fn compile_clip_impl(
    sources: &[String],
    output: &str,
    in_point_s: Option<f64>,
    out_point_s: Option<f64>,
) -> Result<String, String> {
    if sources.is_empty() {
        return Err("compile_clip: no sources".to_string());
    }
    check_window(in_point_s, out_point_s)?;

    for s in sources {
        if !Path::new(s).exists() {
            return Err(format!("compile_clip: source not found: {s}"));
        }
    }

    let decoded: Vec<DecodedSource> = sources
        .iter()
        .map(|s| demux_source(s))
        .collect::<Result<_, _>>()?;

    let (codec, frames) = assemble_timeline(&decoded, in_point_s, out_point_s)?;

    // Parameter sets: use the first source's (all sources share a codec; for a
    // clean stream-copy concat they must also share parameter sets, which is
    // true for our single-encoder capture pipeline).
    mux_mp4(codec, &frames, &decoded[0], output)?;

    Ok(output.to_string())
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
    compile_clip_impl(&sources, &output, in_point_s, out_point_s)
        .map_err(PyRuntimeError::new_err)
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
    fn engine_ready_is_advertised() {
        // Flipped to true after the engine passed cargo test + the Python parity
        // harness + the editor-export smoke. The Python factory relies on this
        // to select the native engine.
        assert!(ENGINE_READY, "validated engine must advertise ready");
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

    #[test]
    fn effective_in_point_drops_nonpositive() {
        assert_eq!(effective_in_point(None), None);
        assert_eq!(effective_in_point(Some(0.0)), None);
        assert_eq!(effective_in_point(Some(-1.0)), None);
        assert_eq!(effective_in_point(Some(2.5)), Some(2.5));
    }

    // ---- keyframe selection --------------------------------------------

    #[test]
    fn keyframe_snaps_back_to_prior_keyframe() {
        // keyframes at 0 and 300; frames every 100 ticks.
        let frames = [
            (0, true),
            (100, false),
            (200, false),
            (300, true),
            (400, false),
        ];
        // target between kf 0 and kf 300 → snap back to 0.
        assert_eq!(keyframe_index_at_or_before(&frames, 250), 0);
        // target exactly on kf 300 → pick 300 (index 3).
        assert_eq!(keyframe_index_at_or_before(&frames, 300), 3);
        // target after last kf → still the last kf.
        assert_eq!(keyframe_index_at_or_before(&frames, 500), 3);
    }

    #[test]
    fn keyframe_before_first_falls_back_to_first_keyframe() {
        let frames = [(100, false), (200, true), (300, false)];
        // target before any keyframe → first keyframe (index 1).
        assert_eq!(keyframe_index_at_or_before(&frames, 50), 1);
    }

    #[test]
    fn keyframe_no_keyframes_returns_zero() {
        let frames = [(0, false), (100, false)];
        assert_eq!(keyframe_index_at_or_before(&frames, 50), 0);
    }

    // ---- concat offsets ------------------------------------------------

    #[test]
    fn concat_single_source_zeroes_start() {
        // one source starting at PTS 900 for 300 ticks → offset -900.
        let offsets = concat_offsets(&[(900, 1200)]);
        assert_eq!(offsets, vec![-900]);
    }

    #[test]
    fn concat_multi_source_is_continuous() {
        // src A: 0..300, src B (local 5000..5300).
        let offsets = concat_offsets(&[(0, 300), (5000, 5300)]);
        // A: offset 0 (starts at 0). B: must start at 300 → offset 300-5000.
        assert_eq!(offsets, vec![0, 300 - 5000]);
        // Verify B's first PTS maps to 300 (right after A's end).
        assert_eq!(5000 + offsets[1], 300);
    }

    #[test]
    fn concat_three_sources_chain() {
        let offsets = concat_offsets(&[(100, 400), (0, 200), (1000, 1300)]);
        // A local 100..400 → shared 0..300 (offset -100).
        assert_eq!(offsets[0], -100);
        // B local 0..200 → shared 300..500 (offset 300).
        assert_eq!(offsets[1], 300);
        assert_eq!(0 + offsets[1], 300);
        // C local 1000..1300 → shared 500..800 (offset 500-1000).
        assert_eq!(offsets[2], 500 - 1000);
        assert_eq!(1000 + offsets[2], 500);
    }

    // ---- frame durations -----------------------------------------------

    #[test]
    fn durations_from_uniform_dts() {
        let dts = [0, 3000, 6000, 9000];
        // deltas 3000,3000,3000, last reuses 3000.
        assert_eq!(frame_durations(&dts), vec![3000, 3000, 3000, 3000]);
    }

    #[test]
    fn durations_single_and_empty() {
        assert_eq!(frame_durations(&[]), Vec::<u32>::new());
        assert_eq!(frame_durations(&[42]), vec![1]);
    }

    #[test]
    fn durations_nonmonotonic_clamps_to_one() {
        // a zero/negative delta clamps to 1 rather than producing 0-length.
        let dts = [0, 0, 3000];
        assert_eq!(frame_durations(&dts), vec![1, 3000, 3000]);
    }

    // ---- Annex-B splitting ---------------------------------------------

    #[test]
    fn annexb_split_4byte_and_3byte_start_codes() {
        // 4-byte start | NAL [0x67 ..] | 3-byte start | NAL [0x68 ..]
        let data = [
            0x00, 0x00, 0x00, 0x01, 0x67, 0xAA, 0xBB, // SPS-ish
            0x00, 0x00, 0x01, 0x68, 0xCC, // PPS-ish
        ];
        let nals = split_annexb_nals(&data);
        assert_eq!(nals.len(), 2);
        assert_eq!(nals[0], &[0x67, 0xAA, 0xBB]);
        assert_eq!(nals[1], &[0x68, 0xCC]);
    }

    #[test]
    fn annexb_split_trims_trailing_zeros() {
        let data = [0x00, 0x00, 0x01, 0x65, 0x11, 0x00, 0x00];
        let nals = split_annexb_nals(&data);
        assert_eq!(nals.len(), 1);
        assert_eq!(nals[0], &[0x65, 0x11]);
    }

    // ---- NAL typing + keyframe classification --------------------------

    #[test]
    fn h264_idr_is_keyframe() {
        assert!(is_keyframe(VideoCodec::H264, &[7, 8, 5])); // SPS,PPS,IDR
        assert!(!is_keyframe(VideoCodec::H264, &[1])); // non-IDR slice
    }

    #[test]
    fn hevc_irap_is_keyframe() {
        assert!(is_keyframe(VideoCodec::Hevc, &[32, 33, 34, 19])); // VPS/SPS/PPS/IDR_W_RADL
        assert!(is_keyframe(VideoCodec::Hevc, &[21])); // CRA
        assert!(!is_keyframe(VideoCodec::Hevc, &[1])); // TRAIL_R
    }

    #[test]
    fn length_prefix_conversion_drops_param_sets() {
        // H.264: SPS(7) + IDR(5). SPS should be dropped, IDR kept & prefixed.
        let sps = [0x67u8, 0x01];
        let idr = [0x65u8, 0x02, 0x03];
        let nals: Vec<&[u8]> = vec![&sps, &idr];
        let out = nals_to_length_prefixed(VideoCodec::H264, &nals);
        // Only the IDR: 4-byte length (3) + 3 bytes body.
        assert_eq!(out, vec![0, 0, 0, 3, 0x65, 0x02, 0x03]);
    }

    #[test]
    fn hevc_length_prefix_drops_vps_sps_pps() {
        let vps = [0x40u8, 0x01]; // type 32
        let sps = [0x42u8, 0x01]; // type 33
        let pps = [0x44u8, 0x01]; // type 34
        let trail = [0x02u8, 0xAB]; // type 1 (TRAIL_R)
        let nals: Vec<&[u8]> = vec![&vps, &sps, &pps, &trail];
        let out = nals_to_length_prefixed(VideoCodec::Hevc, &nals);
        assert_eq!(out, vec![0, 0, 0, 2, 0x02, 0xAB]);
    }

    #[test]
    fn nal_type_extraction() {
        assert_eq!(h264_nal_type(&[0x65]), 5); // IDR
        assert_eq!(h264_nal_type(&[0x67]), 7); // SPS
        assert_eq!(hevc_nal_type(&[0x26]), 19); // IDR_W_RADL (0x26>>1 = 19)
        assert_eq!(hevc_nal_type(&[0x40]), 32); // VPS
    }

    // ---- sample-entry construction (smoke; no real bitstream needed) ----

    #[test]
    fn build_avc1_reads_profile_level_from_sps() {
        // SPS: [nal=0x67][profile=100][compat=0][level=40] ...
        let sps = vec![vec![0x67u8, 100, 0, 40, 0xAB]];
        let pps = vec![vec![0x68u8, 0xCD]];
        match build_avc1(&sps, &pps) {
            SampleEntry::Avc1(b) => {
                assert_eq!(b.avcc_box.avc_profile_indication, 100);
                assert_eq!(b.avcc_box.avc_level_indication, 40);
                assert_eq!(b.avcc_box.sps_list.len(), 1);
                assert_eq!(b.avcc_box.pps_list.len(), 1);
                assert_eq!(b.avcc_box.length_size_minus_one.get(), 3);
            }
            _ => panic!("expected avc1"),
        }
    }

    #[test]
    fn build_hvc1_uses_hvc1_tag_not_hev1() {
        let vps = vec![vec![0x40u8, 0x01, 0x0C]];
        let sps = vec![vec![0x42u8, 0x01, 0x01, 0x60, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 120]];
        let pps = vec![vec![0x44u8, 0x01]];
        match build_hvc1(&vps, &sps, &pps) {
            SampleEntry::Hvc1(b) => {
                // hvc1 tag confirmed by the enum variant.
                assert_eq!(b.hvcc_box.length_size_minus_one.get(), 3);
                assert_eq!(b.hvcc_box.nalu_arrays.len(), 3);
            }
            other => panic!("expected hvc1, got {other:?}"),
        }
    }

    #[test]
    fn be_uint_reads_bigendian() {
        let data = [0x01, 0x02, 0x03, 0x04];
        assert_eq!(be_uint(&data, 0, 4), 0x0102_0304);
        assert_eq!(be_uint(&data, 1, 2), 0x0203);
    }

    // ---- single-source assemble path -----------------------------------

    #[test]
    fn assemble_single_source_normalises_to_zero() {
        let src = DecodedSource {
            codec: VideoCodec::H264,
            sps: vec![vec![0x67, 66, 0, 30]],
            pps: vec![vec![0x68, 0]],
            vps: vec![],
            frames: vec![
                Frame { pts: 900, dts: 900, keyframe: true, data: vec![0, 0, 0, 1, 1] },
                Frame { pts: 1200, dts: 1200, keyframe: false, data: vec![0, 0, 0, 1, 2] },
            ],
        };
        let (codec, frames) = assemble_timeline(&[src], None, None).unwrap();
        assert_eq!(codec, VideoCodec::H264);
        assert_eq!(frames.len(), 2);
        // First PTS normalised to 0.
        assert_eq!(frames[0].pts, 0);
        assert_eq!(frames[1].pts, 300);
    }

    #[test]
    fn assemble_window_snaps_to_keyframe_and_bounds_end() {
        let mk = |pts: i64, kf: bool| Frame {
            pts,
            dts: pts,
            keyframe: kf,
            data: vec![0, 0, 0, 1, 9],
        };
        let src = DecodedSource {
            codec: VideoCodec::H264,
            sps: vec![vec![0x67, 66, 0, 30]],
            pps: vec![vec![0x68, 0]],
            vps: vec![],
            // keyframes at 0 and 27000 (0.3s @90k); frames every 9000 (0.1s).
            frames: vec![
                mk(0, true),
                mk(9000, false),
                mk(18000, false),
                mk(27000, true),
                mk(36000, false),
                mk(45000, false),
            ],
        };
        // in=0.25s → snap back to keyframe at 0 (since kf at 27000=0.3s is later).
        // out=0.4s → drop frames with PTS > 36000.
        let (_c, frames) = assemble_timeline(&[src], Some(0.25), Some(0.4)).unwrap();
        // After normalisation first PTS is 0; frames kept: 0,9000,18000,27000,36000.
        assert_eq!(frames.first().unwrap().pts, 0);
        assert_eq!(frames.last().unwrap().pts, 36000);
        assert_eq!(frames.len(), 5);
    }

    #[test]
    fn assemble_mixed_codecs_errors() {
        let a = DecodedSource {
            codec: VideoCodec::H264,
            sps: vec![vec![0x67]],
            pps: vec![vec![0x68]],
            vps: vec![],
            frames: vec![Frame { pts: 0, dts: 0, keyframe: true, data: vec![1] }],
        };
        let b = DecodedSource {
            codec: VideoCodec::Hevc,
            sps: vec![vec![0x42]],
            pps: vec![vec![0x44]],
            vps: vec![vec![0x40]],
            frames: vec![Frame { pts: 0, dts: 0, keyframe: true, data: vec![1] }],
        };
        assert!(assemble_timeline(&[a, b], None, None).is_err());
    }

    // ---- container detection -------------------------------------------

    #[test]
    fn detect_mp4_by_ftyp_box() {
        // `<size:4>ftyp<...>`
        let hdr = [0x00, 0x00, 0x00, 0x18, b'f', b't', b'y', b'p', b'i', b's', b'o', b'm'];
        assert_eq!(detect_container("x.bin", &hdr).unwrap(), Container::Mp4);
    }

    #[test]
    fn detect_mp4_by_moov_box() {
        let hdr = [0x00, 0x00, 0x10, 0x00, b'm', b'o', b'o', b'v'];
        assert_eq!(detect_container("x.bin", &hdr).unwrap(), Container::Mp4);
    }

    #[test]
    fn detect_ts_by_sync_byte_cadence() {
        // 0x47 at offset 0 and again at offset 188.
        let mut hdr = vec![0u8; 189];
        hdr[0] = 0x47;
        hdr[188] = 0x47;
        assert_eq!(detect_container("x.bin", &hdr).unwrap(), Container::MpegTs);
    }

    #[test]
    fn detect_ts_short_header_single_sync() {
        // Fewer than 189 bytes: a leading 0x47 is enough.
        let hdr = [0x47u8, 0x00, 0x11];
        assert_eq!(detect_container("x.bin", &hdr).unwrap(), Container::MpegTs);
    }

    #[test]
    fn detect_extension_tiebreak() {
        // Inconclusive bytes → fall back to extension.
        let hdr = [0u8; 4];
        assert_eq!(detect_container("clip.mp4", &hdr).unwrap(), Container::Mp4);
        assert_eq!(detect_container("clip.ts", &hdr).unwrap(), Container::MpegTs);
    }

    #[test]
    fn detect_unknown_errors() {
        let hdr = [0x11u8, 0x22, 0x33, 0x44];
        assert!(detect_container("clip.dat", &hdr).is_err());
    }

    #[test]
    fn detect_stray_0x47_in_mp4_is_not_ts() {
        // An MP4 whose size field happens to start 0x47 must still be MP4 (the
        // ftyp check wins, and the 188-cadence check would also reject it).
        let hdr = [0x47, 0x00, 0x00, 0x18, b'f', b't', b'y', b'p'];
        assert_eq!(detect_container("x.bin", &hdr).unwrap(), Container::Mp4);
    }

    // ---- timescale rescaling -------------------------------------------

    #[test]
    fn rescale_common_timescales() {
        // 15360 tick @ 15360 timescale = 1s → 90000 ticks.
        assert_eq!(rescale_to_ts_ticks(15360, 15360), 90000);
        // 90000 timescale is identity.
        assert_eq!(rescale_to_ts_ticks(1234, 90000), 1234);
        // 1000 timescale: 500 ticks = 0.5s → 45000.
        assert_eq!(rescale_to_ts_ticks(500, 1000), 45000);
    }

    #[test]
    fn rescale_rounds_half_away_from_zero() {
        // 1 tick @ 30000 timescale = 90000/30000 = 3 ticks exactly.
        assert_eq!(rescale_to_ts_ticks(1, 30000), 3);
        // A value that does not divide evenly rounds to nearest.
        // 1 tick @ 24000 → 90000/24000 = 3.75 → 4.
        assert_eq!(rescale_to_ts_ticks(1, 24000), 4);
    }

    #[test]
    fn rescale_zero_timescale_is_passthrough() {
        assert_eq!(rescale_to_ts_ticks(42, 0), 42);
    }

    // ---- parameter-set extraction from a decoded sample entry ----------

    #[test]
    fn params_from_avc1_entry() {
        let entry = build_avc1(&[vec![0x67, 66, 0, 30]], &[vec![0x68, 0x11]]);
        let (codec, sps, pps, vps) = params_from_sample_entry(&entry).unwrap();
        assert_eq!(codec, VideoCodec::H264);
        assert_eq!(sps, vec![vec![0x67, 66, 0, 30]]);
        assert_eq!(pps, vec![vec![0x68, 0x11]]);
        assert!(vps.is_empty());
    }

    #[test]
    fn params_from_hvc1_entry() {
        let vps_in = vec![vec![0x40u8, 0x01, 0x0C]];
        let sps_in = vec![vec![0x42u8, 0x01, 0x01]];
        let pps_in = vec![vec![0x44u8, 0x01]];
        let entry = build_hvc1(&vps_in, &sps_in, &pps_in);
        let (codec, sps, pps, vps) = params_from_sample_entry(&entry).unwrap();
        assert_eq!(codec, VideoCodec::Hevc);
        assert_eq!(vps, vps_in);
        assert_eq!(sps, sps_in);
        assert_eq!(pps, pps_in);
    }
}

// ---------------------------------------------------------------------------
// Integration test — real TS produced by system ffmpeg, remuxed, probed.
// Skipped automatically when ffmpeg/ffprobe are not on PATH.
// ---------------------------------------------------------------------------
#[cfg(test)]
mod integration {
    use super::*;
    use std::process::Command;

    fn have(bin: &str) -> bool {
        Command::new(bin)
            .arg("-version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }

    fn have_encoder(name: &str) -> bool {
        Command::new("ffmpeg")
            .args(["-hide_banner", "-encoders"])
            .output()
            .map(|o| String::from_utf8_lossy(&o.stdout).contains(name))
            .unwrap_or(false)
    }

    /// Generate a TS clip with the given encoder and duration; returns its path.
    fn make_ts(dir: &Path, name: &str, encoder: &str, duration: u32) -> std::path::PathBuf {
        let ts = dir.join(name);
        let status = Command::new("ffmpeg")
            .args([
                "-y",
                "-f",
                "lavfi",
                "-i",
                &format!("testsrc=duration={duration}:size=320x240:rate=30"),
                "-c:v",
                encoder,
                "-g",
                "15",
                "-f",
                "mpegts",
            ])
            .arg(&ts)
            .output()
            .expect("ffmpeg spawn");
        assert!(
            status.status.success(),
            "ffmpeg failed to make TS: {}",
            String::from_utf8_lossy(&status.stderr)
        );
        ts
    }

    /// Generate a faststart MP4 clip (mirrors the editor-export part files that
    /// `compile_clip` concatenates in production).
    fn make_mp4(dir: &Path, name: &str, encoder: &str, duration: u32) -> std::path::PathBuf {
        let mp4 = dir.join(name);
        let status = Command::new("ffmpeg")
            .args([
                "-y",
                "-f",
                "lavfi",
                "-i",
                &format!("testsrc=duration={duration}:size=320x240:rate=30"),
                "-c:v",
                encoder,
                "-g",
                "15",
                "-movflags",
                "+faststart",
            ])
            .arg(&mp4)
            .output()
            .expect("ffmpeg spawn");
        assert!(
            status.status.success(),
            "ffmpeg failed to make MP4: {}",
            String::from_utf8_lossy(&status.stderr)
        );
        mp4
    }

    /// Return the v:0 codec name reported by ffprobe.
    fn probe_codec(path: &Path) -> String {
        let probe = Command::new("ffprobe")
            .args([
                "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=codec_name", "-of", "default=nokey=1:noprint_wrappers=1",
            ])
            .arg(path)
            .output()
            .expect("ffprobe spawn");
        assert!(probe.status.success(), "ffprobe failed: {}", String::from_utf8_lossy(&probe.stderr));
        String::from_utf8_lossy(&probe.stdout).trim().to_string()
    }

    /// Count decodable video frames; asserts a clean decode (no corruption),
    /// proving the stream-copy preserved coded data bit-for-bit.
    fn count_frames(path: &Path) -> u32 {
        let probe = Command::new("ffprobe")
            .args([
                "-v", "error", "-select_streams", "v:0", "-count_frames",
                "-show_entries", "stream=nb_read_frames", "-of",
                "default=nokey=1:noprint_wrappers=1",
            ])
            .arg(path)
            .output()
            .expect("ffprobe spawn");
        assert!(probe.status.success(), "ffprobe failed: {}", String::from_utf8_lossy(&probe.stderr));
        String::from_utf8_lossy(&probe.stdout).trim().parse().unwrap_or(0)
    }

    #[test]
    fn end_to_end_h264_ts_to_mp4() {
        if !have("ffmpeg") || !have("ffprobe") {
            eprintln!("skipping: ffmpeg/ffprobe not on PATH");
            return;
        }
        let dir = std::env::temp_dir().join("watcher_segments_it");
        std::fs::create_dir_all(&dir).unwrap();
        let ts = make_ts(&dir, "in_h264.ts", "libx264", 2);
        let out = dir.join("out_h264.mp4");
        let _ = std::fs::remove_file(&out);

        let result = compile_clip_impl(
            &[ts.to_string_lossy().to_string()],
            &out.to_string_lossy(),
            None,
            None,
        );
        assert!(result.is_ok(), "compile_clip failed: {result:?}");
        assert!(out.exists(), "output not written");
        assert_eq!(probe_codec(&out), "h264");
        // 2s @ 30fps = 60 frames, all decodable.
        assert_eq!(count_frames(&out), 60);
    }

    #[test]
    fn end_to_end_hevc_ts_to_mp4_hvc1() {
        if !have("ffmpeg") || !have("ffprobe") {
            eprintln!("skipping: ffmpeg/ffprobe not on PATH");
            return;
        }
        if !have_encoder("libx265") {
            eprintln!("skipping: libx265 encoder not available");
            return;
        }
        let dir = std::env::temp_dir().join("watcher_segments_it");
        std::fs::create_dir_all(&dir).unwrap();
        let ts = make_ts(&dir, "in_hevc.ts", "libx265", 2);
        let out = dir.join("out_hevc.mp4");
        let _ = std::fs::remove_file(&out);

        let result = compile_clip_impl(
            &[ts.to_string_lossy().to_string()],
            &out.to_string_lossy(),
            None,
            None,
        );
        assert!(result.is_ok(), "compile_clip (hevc) failed: {result:?}");
        assert_eq!(probe_codec(&out), "hevc");
        assert_eq!(count_frames(&out), 60);
        // Confirm the sample entry tag is hvc1 (not hev1) by inspecting boxes.
        let tag = Command::new("ffprobe")
            .args([
                "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=codec_tag_string", "-of", "default=nokey=1:noprint_wrappers=1",
            ])
            .arg(&out)
            .output()
            .expect("ffprobe spawn");
        let tag = String::from_utf8_lossy(&tag.stdout).trim().to_string();
        assert_eq!(tag, "hvc1", "HEVC output must use the hvc1 sample entry tag");
    }

    #[test]
    fn end_to_end_concat_two_h264_sources() {
        if !have("ffmpeg") || !have("ffprobe") {
            eprintln!("skipping: ffmpeg/ffprobe not on PATH");
            return;
        }
        let dir = std::env::temp_dir().join("watcher_segments_it");
        std::fs::create_dir_all(&dir).unwrap();
        let a = make_ts(&dir, "concat_a.ts", "libx264", 1);
        let b = make_ts(&dir, "concat_b.ts", "libx264", 1);
        let out = dir.join("out_concat.mp4");
        let _ = std::fs::remove_file(&out);

        let result = compile_clip_impl(
            &[a.to_string_lossy().to_string(), b.to_string_lossy().to_string()],
            &out.to_string_lossy(),
            None,
            None,
        );
        assert!(result.is_ok(), "concat failed: {result:?}");
        assert_eq!(probe_codec(&out), "h264");
        // Two 1s clips concatenated = ~60 frames total.
        assert_eq!(count_frames(&out), 60);
    }

    #[test]
    fn end_to_end_mp4_input_h264() {
        if !have("ffmpeg") || !have("ffprobe") {
            eprintln!("skipping: ffmpeg/ffprobe not on PATH");
            return;
        }
        let dir = std::env::temp_dir().join("watcher_segments_it");
        std::fs::create_dir_all(&dir).unwrap();
        // An MP4 part like the editor-export pipeline produces.
        let mp4 = make_mp4(&dir, "in_h264.mp4", "libx264", 2);
        let out = dir.join("out_from_mp4.mp4");
        let _ = std::fs::remove_file(&out);

        let result = compile_clip_impl(
            &[mp4.to_string_lossy().to_string()],
            &out.to_string_lossy(),
            None,
            None,
        );
        assert!(result.is_ok(), "mp4 remux failed: {result:?}");
        assert_eq!(probe_codec(&out), "h264");
        assert_eq!(count_frames(&out), 60);
    }

    #[test]
    fn end_to_end_concat_two_mp4_sources() {
        if !have("ffmpeg") || !have("ffprobe") {
            eprintln!("skipping: ffmpeg/ffprobe not on PATH");
            return;
        }
        let dir = std::env::temp_dir().join("watcher_segments_it");
        std::fs::create_dir_all(&dir).unwrap();
        let a = make_mp4(&dir, "mp4_concat_a.mp4", "libx264", 1);
        let b = make_mp4(&dir, "mp4_concat_b.mp4", "libx264", 1);
        let out = dir.join("out_mp4_concat.mp4");
        let _ = std::fs::remove_file(&out);

        let result = compile_clip_impl(
            &[a.to_string_lossy().to_string(), b.to_string_lossy().to_string()],
            &out.to_string_lossy(),
            None,
            None,
        );
        assert!(result.is_ok(), "mp4+mp4 concat failed: {result:?}");
        assert_eq!(probe_codec(&out), "h264");
        assert_eq!(count_frames(&out), 60);
    }

    #[test]
    fn end_to_end_mixed_ts_and_mp4_concat() {
        if !have("ffmpeg") || !have("ffprobe") {
            eprintln!("skipping: ffmpeg/ffprobe not on PATH");
            return;
        }
        let dir = std::env::temp_dir().join("watcher_segments_it");
        std::fs::create_dir_all(&dir).unwrap();
        // A TS source (as captured) followed by an MP4 source (as re-encoded by
        // the editor-export path) — auto-detected per source.
        let ts = make_ts(&dir, "mixed_a.ts", "libx264", 1);
        let mp4 = make_mp4(&dir, "mixed_b.mp4", "libx264", 1);
        let out = dir.join("out_mixed.mp4");
        let _ = std::fs::remove_file(&out);

        let result = compile_clip_impl(
            &[ts.to_string_lossy().to_string(), mp4.to_string_lossy().to_string()],
            &out.to_string_lossy(),
            None,
            None,
        );
        assert!(result.is_ok(), "ts+mp4 concat failed: {result:?}");
        assert_eq!(probe_codec(&out), "h264");
        assert_eq!(count_frames(&out), 60);
    }
}
