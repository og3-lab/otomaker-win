"""Post-processing and export for generated clips (numpy + ffmpeg + soundfile).

Audio arrays are (channels, samples) float32, the layout every backend returns.
ffmpeg is used only for resampling and EBU R128 loudness normalization; OGG
Vorbis is written by soundfile's bundled libsndfile, so OGG output does not
depend on how the ffmpeg build was compiled.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf


def db_to_lin(db: float) -> float:
    return float(10 ** (db / 20))


def lin_to_db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-12)))


def stats(audio: np.ndarray) -> dict:
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    rms = float(np.sqrt((audio ** 2).mean())) if audio.size else 0.0
    return {"peak": round(peak, 3), "peak_dbfs": round(lin_to_db(peak), 2),
            "rms": round(rms, 4)}


def peak_ceiling(audio: np.ndarray, ceiling_db: float) -> tuple[np.ndarray, float]:
    """Attenuate the whole clip if its peak exceeds the ceiling. Never boosts.
    Returns (audio, applied gain in dB)."""
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    limit = db_to_lin(ceiling_db)
    if peak <= limit:
        return audio, 0.0
    return audio * (limit / peak), lin_to_db(limit / peak)


def peak_normalize(audio: np.ndarray, target_db: float) -> tuple[np.ndarray, float]:
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak <= 0:
        return audio, 0.0
    gain = db_to_lin(target_db) / peak
    return audio * gain, lin_to_db(gain)


def read(path: str | Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return np.ascontiguousarray(data.T), int(sr)


def write(path: Path, audio: np.ndarray, sr: int, fmt: str, ogg_quality: float = 0.6) -> None:
    data = np.clip(audio, -1.0, 1.0).T
    if fmt == "wav":
        sf.write(str(path), data, sr, format="WAV", subtype="PCM_24")
    elif fmt == "flac":
        sf.write(str(path), data, sr, format="FLAC", subtype="PCM_24")
    elif fmt == "ogg":
        # Written in 1 s blocks: libsndfile 1.2.2's Vorbis encoder crashes the
        # process (no Python exception) on Windows when ~30 s arrive in one call.
        with sf.SoundFile(str(path), "w", sr, data.shape[1], format="OGG", subtype="VORBIS",
                          compression_level=float(np.clip(1.0 - ogg_quality, 0.0, 1.0))) as f:
            for i in range(0, data.shape[0], sr):
                f.write(data[i:i + sr])
    else:
        raise ValueError(f"unknown format {fmt}")


def _short_path(p: str) -> str:
    """The real 8.3 short name of p on Windows ('' elsewhere or when 8.3 names are off)."""
    if os.name != "nt":
        return ""
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, len(buf))
    return buf.value if 0 < n < len(buf) else ""


def _profile_patterns() -> list[re.Pattern]:
    up = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    up = up.rstrip("\\/")
    if not up or up == "~":
        return []
    sep = r"[\\/]+"

    def pat(p: str) -> str:
        return sep.join(re.escape(x) for x in re.split(sep, p.rstrip("\\/")))
    alts = {pat(up)}
    sp = _short_path(up)
    if sp:
        alts.add(pat(sp))
    parent, leaf = os.path.split(up)
    stem = re.sub(r"[\s.]", "", leaf)[:6]
    if stem:  # 8.3 form of the profile folder: first 6 chars without spaces + ~N
        alts.add(pat(parent) + sep + re.escape(stem) + r"~\d+")
    return [re.compile(f"(?:{a})(?=$|{sep})", re.I) for a in sorted(alts, key=len, reverse=True)]


def redact_paths(obj, _pats=None):
    """Replace the user-profile prefix (long or 8.3 short form, any case, \\ or /)
    in every string of obj with %USERPROFILE%, so sidecars carry no user name."""
    pats = _profile_patterns() if _pats is None else _pats
    if isinstance(obj, str):
        for p in pats:
            obj = p.sub("%USERPROFILE%", obj)
        return obj
    if isinstance(obj, dict):
        return {redact_paths(k, pats): redact_paths(v, pats) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_paths(v, pats) for v in obj]
    return obj


def write_sidecar(audio_path: Path, meta: dict) -> Path:
    p = audio_path.with_suffix(audio_path.suffix + ".json")
    p.write_text(json.dumps(redact_paths(meta), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ── edits ────────────────────────────────────────────────────────────────────
def trim(audio: np.ndarray, sr: int, start: float, end: float | None) -> np.ndarray:
    s = max(0, int(round(start * sr)))
    e = audio.shape[-1] if end is None else min(audio.shape[-1], int(round(end * sr)))
    if e <= s:
        raise ValueError(f"empty trim range {start}–{end}s")
    return audio[:, s:e]


def _loud_windows(audio: np.ndarray, sr: int, threshold_db: float
                  ) -> tuple[int, np.ndarray] | None:
    """(window length, indices of 5 ms RMS windows louder than threshold), or
    None when the clip is shorter than one window."""
    win = max(1, int(sr * 0.005))
    mono = np.abs(audio).max(axis=0)
    n = len(mono) // win
    if n == 0:
        return None
    env = np.sqrt((mono[: n * win].reshape(n, win) ** 2).mean(axis=1))
    return win, np.nonzero(env > db_to_lin(threshold_db))[0]


def audible_end(audio: np.ndarray, sr: int, threshold_db: float = -60.0) -> float:
    """Seconds up to the end of the last 5 ms window louder than threshold.

    Generated tracks often end in a fade or in digital silence; continuing
    from the file end would carry that gap into the middle of the result."""
    found = _loud_windows(audio, sr, threshold_db)
    if found is None:
        return audio.shape[-1] / sr
    win, loud = found
    return 0.0 if loud.size == 0 else min(audio.shape[-1], (loud[-1] + 1) * win) / sr


def trim_silence(audio: np.ndarray, sr: int, threshold_db: float = -50.0,
                 pad_ms: float = 10.0) -> np.ndarray:
    """Cut leading/trailing audio quieter than threshold (5 ms RMS windows)."""
    found = _loud_windows(audio, sr, threshold_db)
    if found is None:
        return audio
    win, loud = found
    if loud.size == 0:
        return audio
    pad = int(sr * pad_ms / 1000)
    s = max(0, loud[0] * win - pad)
    e = min(audio.shape[-1], (loud[-1] + 1) * win + pad)
    return audio[:, s:e]


def fade(audio: np.ndarray, sr: int, fade_in_ms: float, fade_out_ms: float) -> np.ndarray:
    out = audio.copy()
    n_in = min(out.shape[-1], int(sr * fade_in_ms / 1000))
    n_out = min(out.shape[-1], int(sr * fade_out_ms / 1000))
    if n_in > 0:
        out[:, :n_in] *= np.sin(np.linspace(0, np.pi / 2, n_in)) ** 2
    if n_out > 0:
        out[:, -n_out:] *= np.cos(np.linspace(0, np.pi / 2, n_out)) ** 2
    return out


def make_loop(audio: np.ndarray, sr: int, crossfade_ms: float) -> np.ndarray:
    """Seamless loop: fold the last `crossfade` into the start with an
    equal-power crossfade, so out[-1] → out[0] continues the original audio.
    Output is shorter than the input by the crossfade length."""
    n = int(sr * crossfade_ms / 1000)
    L = audio.shape[-1]
    if n <= 0:
        return audio
    if 2 * n >= L:
        raise ValueError(f"crossfade {crossfade_ms} ms is too long for a {L / sr:.2f}s clip")
    t = np.linspace(0, np.pi / 2, n, dtype=np.float32)
    head, tail = audio[:, :n], audio[:, L - n:]
    blended = head * np.sin(t) + tail * np.cos(t)
    return np.concatenate([blended, audio[:, n: L - n]], axis=1)


def to_mono(audio: np.ndarray) -> np.ndarray:
    return audio.mean(axis=0, keepdims=True)


# ── ffmpeg: resample + loudness ──────────────────────────────────────────────
def _ffmpeg(args: list[str]) -> str:
    exe = os.environ.get("OTOMAKER_FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found: install it (Windows: winget install --id Gyan.FFmpeg -e) "
                           "and/or set OTOMAKER_FFMPEG to the full path of ffmpeg.exe "
                           "(winget does not always put it on PATH). Needed for resampling and loudness.")
    r = subprocess.run([exe, "-hide_banner", "-nostdin", "-y", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-800:]}")
    return r.stderr


def ffmpeg_process(audio: np.ndarray, sr: int, out_sr: int,
                   target_lufs: float | None, true_peak_db: float) -> tuple[np.ndarray, dict]:
    """Resample to out_sr and optionally loudness-normalize (two-pass loudnorm,
    linear when possible). Returns (audio, info)."""
    info: dict = {}
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.wav", Path(td) / "out.wav"
        sf.write(str(src), audio.T, sr, format="WAV", subtype="FLOAT")
        resample = f"aresample={out_sr}:filter_size=64:phase_shift=10:cutoff=0.97"
        chain = [resample]
        if target_lufs is not None:
            # loudnorm accepts TP in [-9, 0]; a lower ceiling is applied afterwards
            # by the caller's peak_ceiling step.
            base = f"loudnorm=I={target_lufs}:TP={max(-9.0, true_peak_db)}:LRA=20"
            err = _ffmpeg(["-i", str(src), "-af", base + ":print_format=json", "-f", "null", "-"])
            m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
            if not m:
                raise RuntimeError("loudnorm analysis produced no stats")
            st = json.loads(m.group(0))
            info["input_lufs"] = round(float(st["input_i"]), 2)
            info["input_true_peak_db"] = round(float(st["input_tp"]), 2)
            chain = [base + (f":measured_I={st['input_i']}:measured_TP={st['input_tp']}"
                             f":measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}"
                             f":offset={st['target_offset']}:linear=true:print_format=json"),
                     resample]
        err = _ffmpeg(["-i", str(src), "-af", ",".join(chain), "-c:a", "pcm_f32le", str(dst)])
        if target_lufs is not None:
            m = re.search(r"\{[^{}]*\"output_i\"[^{}]*\}", err, re.S)
            if m:
                st = json.loads(m.group(0))
                info["output_lufs"] = round(float(st["output_i"]), 2)
                info["loudnorm_mode"] = st.get("normalization_type", "")
        out, _ = read(dst)
    return out, info
