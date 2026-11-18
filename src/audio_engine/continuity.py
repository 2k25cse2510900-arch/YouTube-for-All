"""Audio Continuity Processor for seamless segment stitching, loudness normalization, and acoustic diagnostics."""

from dataclasses import dataclass, field
import math
from pathlib import Path
import shutil
import struct
import subprocess
from typing import List, Optional, Tuple
import wave

from src.common.logger import setup_logger

logger = setup_logger("audio_continuity")


@dataclass
class AudioMetrics:
    """Acoustic metrics measured from a WAV audio stream."""

    duration_seconds: float
    sample_rate: int
    channels: int
    bit_depth: int
    peak_dbfs: float
    rms_dbfs: float
    clipped_samples: int
    clipping_ratio: float
    silence_gaps: List[Tuple[float, float]] = field(default_factory=list)
    max_silence_gap_seconds: float = 0.0
    leading_silence_seconds: float = 0.0
    trailing_silence_seconds: float = 0.0


class AudioContinuityProcessor:
    """Manages audio continuity, smooth segment concatenation, loudness compliance, and artifact analysis."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        self.ffmpeg_bin = ffmpeg_bin
        self._ffmpeg_available = shutil.which(ffmpeg_bin) is not None

    def analyze_wav(self, file_path: Path, silence_threshold_dbfs: float = -45.0) -> AudioMetrics:
        """Analyze a PCM WAV file to extract peak, RMS, clipping, and silence intervals."""
        p = Path(file_path)
        if not p.is_file():
            raise FileNotFoundError(f"Audio file not found: {p}")

        with wave.open(str(p), "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            raw_bytes = wf.readframes(n_frames)

        duration = n_frames / float(sample_rate) if sample_rate > 0 else 0.0
        bit_depth = sample_width * 8

        if n_frames == 0 or len(raw_bytes) == 0:
            return AudioMetrics(
                duration_seconds=0.0,
                sample_rate=sample_rate,
                channels=n_channels,
                bit_depth=bit_depth,
                peak_dbfs=-100.0,
                rms_dbfs=-100.0,
                clipped_samples=0,
                clipping_ratio=0.0,
                silence_gaps=[],
                max_silence_gap_seconds=0.0,
                leading_silence_seconds=0.0,
                trailing_silence_seconds=0.0,
            )

        # Unpack 16-bit signed PCM
        if sample_width == 2:
            n_samples = len(raw_bytes) // 2
            samples = struct.unpack(f"<{n_samples}h", raw_bytes)
        elif sample_width == 1:
            # 8-bit unsigned PCM: convert 0..255 to -128..127 scaled to 16-bit
            samples = [(b - 128) * 256 for b in raw_bytes]
            n_samples = len(samples)
        else:
            # Fallback for 24-bit or 32-bit: approximate with int16 slice
            n_samples = len(raw_bytes) // sample_width
            step = sample_width
            samples = [
                int.from_bytes(raw_bytes[i * step : (i + 1) * step], byteorder="little", signed=True)
                >> ((sample_width - 2) * 8)
                for i in range(n_samples)
            ]

        # Combine channels to mono for analysis
        if n_channels > 1:
            mono_samples = []
            for i in range(0, len(samples), n_channels):
                mono_samples.append(sum(samples[i : i + n_channels]) // n_channels)
            analysis_samples = mono_samples
        else:
            analysis_samples = list(samples)

        total_samples = len(analysis_samples)

        # 1. Peak & Clipping Analysis
        max_abs = 0
        sum_sq = 0.0
        clipped_count = 0
        clip_threshold = 32760  # Near 16-bit maximum (32767)

        for s in analysis_samples:
            val = abs(s)
            if val > max_abs:
                max_abs = val
            sum_sq += s * s
            if val >= clip_threshold:
                clipped_count += 1

        peak_dbfs = 20.0 * math.log10(max(max_abs, 1) / 32768.0)
        rms = math.sqrt(sum_sq / total_samples) if total_samples > 0 else 0.0
        rms_dbfs = 20.0 * math.log10(max(rms, 1.0) / 32768.0)
        clipping_ratio = clipped_count / total_samples if total_samples > 0 else 0.0

        # 2. Silence & Gap Detection (Windowed: 50ms chunks)
        chunk_size = max(1, int(sample_rate * 0.05))
        silence_amp_thresh = 32768.0 * (10.0 ** (silence_threshold_dbfs / 20.0))

        chunk_is_silent: List[bool] = []
        for i in range(0, total_samples, chunk_size):
            chunk = analysis_samples[i : i + chunk_size]
            c_rms = math.sqrt(sum(x * x for x in chunk) / len(chunk))
            chunk_is_silent.append(c_rms < silence_amp_thresh)

        # Identify contiguous silent intervals
        silence_intervals: List[Tuple[float, float]] = []
        in_silence = False
        silence_start_chunk = 0

        for idx, silent in enumerate(chunk_is_silent):
            if silent and not in_silence:
                in_silence = True
                silence_start_chunk = idx
            elif not silent and in_silence:
                in_silence = False
                t_start = (silence_start_chunk * chunk_size) / float(sample_rate)
                t_end = (idx * chunk_size) / float(sample_rate)
                silence_intervals.append((round(t_start, 3), round(t_end, 3)))

        if in_silence:
            t_start = (silence_start_chunk * chunk_size) / float(sample_rate)
            t_end = duration
            silence_intervals.append((round(t_start, 3), round(t_end, 3)))

        # Categorize gaps: leading, trailing, internal
        leading_silence = 0.0
        trailing_silence = 0.0
        internal_gaps: List[Tuple[float, float]] = []

        for start_s, end_s in silence_intervals:
            if start_s == 0.0:
                leading_silence = end_s
            elif end_s >= round(duration - 0.05, 2):
                trailing_silence = round(duration - start_s, 3)
            else:
                internal_gaps.append((start_s, end_s))

        max_gap = max((e - s for s, e in internal_gaps), default=0.0)

        return AudioMetrics(
            duration_seconds=round(duration, 3),
            sample_rate=sample_rate,
            channels=n_channels,
            bit_depth=bit_depth,
            peak_dbfs=round(peak_dbfs, 2),
            rms_dbfs=round(rms_dbfs, 2),
            clipped_samples=clipped_count,
            clipping_ratio=round(clipping_ratio, 6),
            silence_gaps=internal_gaps,
            max_silence_gap_seconds=round(max_gap, 3),
            leading_silence_seconds=round(leading_silence, 3),
            trailing_silence_seconds=round(trailing_silence, 3),
        )

    def trim_silence_pcm(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        threshold_dbfs: float = -45.0,
        pad_ms: int = 50,
    ) -> Tuple[Path, float, float]:
        """Trim leading and trailing dead air from a 16-bit PCM WAV file.

        Returns:
            Tuple of (output_path, leading_trimmed_ms, trailing_trimmed_ms)
        """
        in_p = Path(input_path)
        out_p = Path(output_path) if output_path else in_p
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(in_p), "rb") as wf:
            params = wf.getparams()
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())

        if sample_width != 2 or len(raw) == 0:
            if in_p != out_p:
                shutil.copy(in_p, out_p)
            return out_p, 0.0, 0.0

        n_samples = len(raw) // 2
        samples = struct.unpack(f"<{n_samples}h", raw)
        chunk_size = max(1, int(sample_rate * 0.01)) * n_channels  # 10ms chunks
        amp_thresh = 32768.0 * (10.0 ** (threshold_dbfs / 20.0))

        first_loud = 0
        last_loud = n_samples

        # Scan for speech onset
        for i in range(0, n_samples, chunk_size):
            chunk = samples[i : i + chunk_size]
            rms = math.sqrt(sum(x * x for x in chunk) / len(chunk))
            if rms >= amp_thresh:
                pad_samples = int((pad_ms / 1000.0) * sample_rate) * n_channels
                first_loud = max(0, i - pad_samples)
                break

        # Scan backwards for speech offset
        for i in range(n_samples - chunk_size, 0, -chunk_size):
            chunk = samples[i : i + chunk_size]
            rms = math.sqrt(sum(x * x for x in chunk) / len(chunk))
            if rms >= amp_thresh:
                pad_samples = int((pad_ms / 1000.0) * sample_rate) * n_channels
                last_loud = min(n_samples, i + chunk_size + pad_samples)
                break

        trimmed = samples[first_loud:last_loud]
        leading_trimmed_ms = round((first_loud / float(sample_rate * n_channels)) * 1000.0, 2)
        trailing_trimmed_ms = round(((n_samples - last_loud) / float(sample_rate * n_channels)) * 1000.0, 2)

        with wave.open(str(out_p), "wb") as wf:
            wf.setparams(params)
            wf.writeframes(struct.pack(f"<{len(trimmed)}h", *trimmed))

        logger.debug(
            "Trimmed '%s' (Lead: %.1fms, Trail: %.1fms) -> '%s'",
            in_p.name, leading_trimmed_ms, trailing_trimmed_ms, out_p.name,
        )
        return out_p, leading_trimmed_ms, trailing_trimmed_ms

    def condense_internal_silence(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        max_silence_ms: int = 120,
        threshold_dbfs: Optional[float] = -38.0,
        pad_ms: int = 20,
        crossfade_ms: int = 10,
        gap_rules: Optional[List[Tuple[float, int]]] = None,
    ) -> Path:
        """Condense internal dead-air gaps inside an audio take to natural conversational pauses.

        - Intelligent silence detection with configurable dBFS threshold or dynamic noise floor (None/"auto").
        - Preserves unvoiced consonants, plosives, and fricatives by maintaining pad_ms boundaries.
        - Applies smooth cosine micro-crossfades over cut boundaries to eliminate clicks and pops.
        - Supports gap_rules [(approx_timestamp_sec, target_ms)] to distinguish intra-sentence gaps
          (60-120ms) from deliberate dramatic or punctuation pauses (150-250ms).
        """
        in_p = Path(input_path)
        out_p = Path(output_path) if output_path else in_p
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(in_p), "rb") as wf:
            params = wf.getparams()
            sr = wf.getframerate()
            n_ch = wf.getnchannels()
            sw = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())

        if sw != 2 or len(frames) == 0:
            if in_p != out_p:
                shutil.copy(in_p, out_p)
            return out_p

        samples = struct.unpack(f"<{len(frames)//2}h", frames)

        # Multi-channel handling: perform analysis on mono downmix
        if n_ch > 1:
            analysis_samples = [
                sum(samples[i : i + n_ch]) // n_ch
                for i in range(0, len(samples), n_ch)
            ]
        else:
            analysis_samples = list(samples)

        # 10ms frame analysis
        win_len = int(sr * 0.01)
        n_windows = len(analysis_samples) // win_len

        # Dynamic noise floor detection if threshold_dbfs is None or "auto"
        if threshold_dbfs is None or threshold_dbfs == "auto":
            all_rms = [
                math.sqrt(sum(x * x for x in analysis_samples[i * win_len : (i + 1) * win_len]) / win_len)
                for i in range(n_windows)
            ]
            sorted_rms = sorted(all_rms)
            p10 = sorted_rms[int(len(sorted_rms) * 0.10)] if sorted_rms else 100.0
            # Set threshold 6dB above 10th percentile noise floor, clamped between -48dBFS and -32dBFS
            min_floor = 32768.0 * (10.0 ** (-48.0 / 20.0))
            max_floor = 32768.0 * (10.0 ** (-32.0 / 20.0))
            thresh_amp = max(min_floor, min(max_floor, p10 * 2.0))
        else:
            thresh_amp = 32768.0 * (10.0 ** (float(threshold_dbfs) / 20.0))

        is_silent = []
        for i in range(n_windows):
            chunk = analysis_samples[i * win_len : (i + 1) * win_len]
            rms = math.sqrt(sum(x * x for x in chunk) / len(chunk))
            is_silent.append(rms < thresh_amp)

        # Identify contiguous silent intervals (>= 50ms)
        silent_blocks = []
        in_s = False
        s_idx = 0
        for i, s in enumerate(is_silent):
            if s and not in_s:
                in_s = True
                s_idx = i
            elif not s and in_s:
                in_s = False
                dur_ms = (i - s_idx) * 10
                if dur_ms >= 50:
                    silent_blocks.append((s_idx * win_len, i * win_len, dur_ms))
        if in_s:
            dur_ms = (n_windows - s_idx) * 10
            if dur_ms >= 50:
                silent_blocks.append((s_idx * win_len, n_windows * win_len, dur_ms))

        # Filter out leading and trailing boundary regions
        internal_blocks = []
        for start_s, end_s, dur_ms in silent_blocks:
            if start_s > win_len and end_s < (len(analysis_samples) - win_len):
                internal_blocks.append((start_s, end_s, dur_ms))

        if not internal_blocks:
            if in_p != out_p:
                shutil.copy(in_p, out_p)
            return out_p

        # Modify samples from end to start to keep preceding indices intact
        mod_samples = list(samples)
        pad_s = int((pad_ms / 1000.0) * sr) * n_ch
        xfade_s = int((crossfade_ms / 1000.0) * sr) * n_ch

        for start_s, end_s, orig_ms in reversed(internal_blocks):
            # Scale sample positions for multi-channel
            start_pos = start_s * n_ch
            end_pos = end_s * n_ch
            t_mid = (start_s + end_s) / (2.0 * sr)

            target_ms = max_silence_ms
            if gap_rules:
                for rule_t, rule_target in gap_rules:
                    if abs(t_mid - rule_t) < 0.45:
                        target_ms = rule_target
                        break

            if orig_ms > target_ms:
                target_s = int((target_ms / 1000.0) * sr) * n_ch
                cut_s = (end_pos - start_pos) - target_s
                if cut_s > 0:
                    cut_start = start_pos + pad_s
                    cut_end = cut_start + cut_s
                    if cut_end <= end_pos:
                        before_cut = mod_samples[:cut_start]
                        after_cut = mod_samples[cut_end:]

                        if len(before_cut) >= xfade_s and len(after_cut) >= xfade_s and xfade_s > 0:
                            ov_prev = before_cut[-xfade_s:]
                            ov_curr = after_cut[:xfade_s]
                            blended = []
                            for k in range(xfade_s):
                                theta = (k / float(xfade_s)) * (math.pi / 2.0)
                                w_curr = math.sin(theta)
                                w_prev = math.cos(theta)
                                blended.append(int(ov_prev[k] * w_prev + ov_curr[k] * w_curr))
                            mod_samples = before_cut[:-xfade_s] + blended + after_cut[xfade_s:]
                        else:
                            mod_samples = before_cut + after_cut

        with wave.open(str(out_p), "wb") as wf:
            wf.setparams(params)
            wf.writeframes(struct.pack(f"<{len(mod_samples)}h", *mod_samples))

        logger.info(
            "Condensed internal silence for '%s' -> '%s' (Original: %.3fs, New: %.3fs)",
            in_p.name, out_p.name, len(samples) / (sr * n_ch), len(mod_samples) / (sr * n_ch)
        )
        return out_p

    def stitch_segments(
        self,
        segment_paths: List[Path],
        output_path: Path,
        crossfade_ms: int = 15,
        pause_between_ms: int = 80,
    ) -> Path:
        """Stitch multiple audio segments seamlessly into one continuous WAV file.

        Applies micro-crossfade or smooth pause bridging between segments to eliminate clicks, pops,
        and jarring abrupt transitions.
        """
        valid_paths = [Path(p) for p in segment_paths if Path(p).is_file()]
        if not valid_paths:
            raise ValueError("No valid audio segment paths provided for stitching.")

        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        if len(valid_paths) == 1:
            shutil.copy(valid_paths[0], out_p)
            return out_p

        # Read first file to get parameters
        with wave.open(str(valid_paths[0]), "rb") as wf:
            target_params = wf.getparams()
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            n_channels = wf.getnchannels()

        all_samples: List[int] = []
        crossfade_samples = int((crossfade_ms / 1000.0) * sample_rate) * n_channels
        pause_samples = int((pause_between_ms / 1000.0) * sample_rate) * n_channels

        for idx, sp in enumerate(valid_paths):
            with wave.open(str(sp), "rb") as wf:
                raw = wf.readframes(wf.getnframes())
                if wf.getsampwidth() != sample_width or wf.getframerate() != sample_rate or wf.getnchannels() != n_channels:
                    # Parameter mismatch: use ffmpeg to re-encode this segment to match target
                    matched_sp = sp.with_suffix(".matched.wav")
                    cmd = [
                        self.ffmpeg_bin, "-y", "-i", str(sp),
                        "-ar", str(sample_rate), "-ac", str(n_channels),
                        "-c:a", "pcm_s16le", str(matched_sp)
                    ]
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    with wave.open(str(matched_sp), "rb") as mwf:
                        raw = mwf.readframes(mwf.getnframes())
                    matched_sp.unlink(missing_ok=True)

            n_s = len(raw) // 2
            current_segment = list(struct.unpack(f"<{n_s}h", raw))

            if idx == 0:
                all_samples.extend(current_segment)
            else:
                # Bridge previous segment to current segment
                if pause_between_ms > 0:
                    # Insert smooth silent bridge
                    all_samples.extend([0] * pause_samples)
                    all_samples.extend(current_segment)
                elif crossfade_samples > 0 and len(all_samples) >= crossfade_samples and len(current_segment) >= crossfade_samples:
                    # Apply cosine crossfade over overlap region
                    overlap_prev = all_samples[-crossfade_samples:]
                    all_samples = all_samples[:-crossfade_samples]
                    overlap_curr = current_segment[:crossfade_samples]
                    rest_curr = current_segment[crossfade_samples:]

                    blended = []
                    half_len = crossfade_samples
                    for k in range(half_len):
                        # Cosine crossfade weighting: fade out prev, fade in curr
                        theta = (k / float(half_len)) * (math.pi / 2.0)
                        w_curr = math.sin(theta)
                        w_prev = math.cos(theta)
                        mixed = int(overlap_prev[k] * w_prev + overlap_curr[k] * w_curr)
                        mixed = max(-32768, min(32767, mixed))
                        blended.append(mixed)

                    all_samples.extend(blended)
                    all_samples.extend(rest_curr)
                else:
                    all_samples.extend(current_segment)

        # Write output WAV
        with wave.open(str(out_p), "wb") as out_wf:
            out_wf.setnchannels(n_channels)
            out_wf.setsampwidth(sample_width)
            out_wf.setframerate(sample_rate)
            packed = struct.pack(f"<{len(all_samples)}h", *all_samples)
            out_wf.writeframes(packed)

        logger.info("Stitched %d segments into '%s' (%d total samples)", len(valid_paths), out_p.name, len(all_samples))
        return out_p

    def normalize_loudness(
        self,
        input_path: Path,
        output_path: Path,
        target_lufs: float = -16.0,
        true_peak: float = -1.5,
    ) -> Path:
        """Apply EBU R128 loudness normalization (-16 LUFS integrated, -1.5 dBFS true peak).

        Uses FFmpeg loudnorm filter when available; falls back to peak normalization otherwise.
        """
        in_p = Path(input_path)
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        if not in_p.is_file():
            raise FileNotFoundError(f"Input file not found: {in_p}")

        if self._ffmpeg_available:
            try:
                cmd = [
                    self.ffmpeg_bin,
                    "-y",
                    "-i",
                    str(in_p),
                    "-af",
                    f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11.0",
                    "-ar",
                    "48000",
                    "-c:a",
                    "pcm_s16le",
                    str(out_p),
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info("Normalized loudness of '%s' -> '%s' (Target: %.1f LUFS)", in_p.name, out_p.name, target_lufs)
                return out_p
            except Exception as err:
                logger.warning("FFmpeg loudnorm failed (%s); falling back to peak normalization.", err)

        # Fallback: Python peak normalization to -1.5 dBFS
        return self._peak_normalize_pcm(in_p, out_p, target_peak_dbfs=true_peak)

    def _peak_normalize_pcm(self, in_p: Path, out_p: Path, target_peak_dbfs: float = -1.5) -> Path:
        """Normalize audio peak amplitude using standard Python PCM manipulation."""
        metrics = self.analyze_wav(in_p)
        if metrics.duration_seconds == 0.0 or metrics.peak_dbfs <= -90.0:
            shutil.copy(in_p, out_p)
            return out_p

        target_amp = 32768.0 * (10.0 ** (target_peak_dbfs / 20.0))
        current_peak_amp = 32768.0 * (10.0 ** (metrics.peak_dbfs / 20.0))
        gain = target_amp / max(current_peak_amp, 1.0)

        with wave.open(str(in_p), "rb") as wf:
            params = wf.getparams()
            raw = wf.readframes(wf.getnframes())

        n_s = len(raw) // 2
        samples = struct.unpack(f"<{n_s}h", raw)
        scaled_samples = [max(-32768, min(32767, int(s * gain))) for s in samples]

        with wave.open(str(out_p), "wb") as wf:
            wf.setparams(params)
            wf.writeframes(struct.pack(f"<{len(scaled_samples)}h", *scaled_samples))

        logger.info("Peak normalized '%s' -> '%s' (Gain: %.2fx)", in_p.name, out_p.name, gain)
        return out_p

    def convert_format(
        self,
        input_path: Path,
        output_path: Path,
        target_sample_rate: int = 44100,
        channels: int = 2,
    ) -> Path:
        """Convert any audio file to broadcast-standard 16-bit PCM WAV (e.g., 44.1kHz stereo)."""
        in_p = Path(input_path)
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        if not in_p.is_file():
            raise FileNotFoundError(f"Input file not found: {in_p}")

        if self._ffmpeg_available:
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-i",
                str(in_p),
                "-ar",
                str(target_sample_rate),
                "-ac",
                str(channels),
                "-c:a",
                "pcm_s16le",
                str(out_p),
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return out_p

        # If ffmpeg not available, copy if already matching
        with wave.open(str(in_p), "rb") as wf:
            if wf.getframerate() == target_sample_rate and wf.getnchannels() == channels and wf.getsampwidth() == 2:
                shutil.copy(in_p, out_p)
                return out_p
        raise RuntimeError(f"FFmpeg is required to convert sample rate/channels from {in_p} to {out_p}")
