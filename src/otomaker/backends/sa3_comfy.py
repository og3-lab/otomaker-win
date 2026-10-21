"""Stable Audio 3 through a running ComfyUI server (HTTP API, usually on a GPU).

The backend only talks to ComfyUI; starting and stopping ComfyUI is the
caller's job. One /prompt per seed with this node graph (CheckpointLoaderSimple → CLIPLoader →
CLIPTextEncode ×2 → EmptyLatentAudio → KSampler (lcm/simple) → VAEDecodeAudio
→ SaveAudio). The FLAC that SaveAudio writes is fetched with /view and decoded
in memory; ComfyUI keeps its own copy in its output folder.

Text-to-audio only: init_audio (variation) and inpaint_audio raise
NotImplementedError.

Environment:
  OTOMAKER_COMFY_HOST           host:port of ComfyUI (default 127.0.0.1:8188,
                                    ComfyUI's own default)
  OTOMAKER_SA3_MODEL            sm-sfx | sm-music | medium (default sm-music)
  OTOMAKER_COMFY_LENGTH_SUFFIX  1 (default) = append "Length: N seconds" to
                                    the prompt; 0 = send it as is.
                                    The text actually sent is returned as
                                    GenerationResult.prompt_used, which the
                                    server stores as "prompt_used" in the .json.

  OTOMAKER_COMFY_FREE           1 = unload_models / the idle reaper send POST
                                    /free (unloads every model in that ComfyUI,
                                    including other tools' models). Default off:
                                    nothing is sent and a note goes to stderr.

If ComfyUI cannot be reached before it accepts a prompt, the call raises
ComfyUnreachable (a RuntimeError), so the server can fall back to another
backend (OTOMAKER_FALLBACK). Once ComfyUI has accepted a prompt, any
failure is a plain RuntimeError and nothing falls back.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import Executor, ThreadPoolExecutor

import numpy as np

from .base import Backend, BackendUnavailable, GenerationRequest, GenerationResult

DEFAULT_HOST = "127.0.0.1:8188"   # ComfyUI's default
CLIP = "t5gemma_b_b_ul2.safetensors"
SAMPLE_RATE = 44100
MIN_SECONDS = 1.0  # ComfyUI answers HTTP 400 below 1 s

# Our model name → (checkpoint file, max seconds).
MODELS = {
    "sm-sfx": ("stable_audio_3_small_sfx.safetensors", 120.0),
    "sm-music": ("stable_audio_3_small_music.safetensors", 120.0),
    "medium": ("stable_audio_3_medium.safetensors", 380.0),
}
DEFAULT_MODEL = "sm-music"

_SAVE_NODE = "13"


class ComfyUnreachable(BackendUnavailable):
    """ComfyUI did not answer (refused, timed out, …). Only raised before ComfyUI
    accepted a prompt, so nothing was generated."""


def _log(msg: str) -> None:
    print(f"[otomaker] sa3-comfy: {msg}", file=sys.stderr)


def _flag(value: str | bool | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def length_text(prompt: str, gen_seconds: float) -> str:
    """'<prompt>. Length: N seconds'."""
    body = prompt.strip().rstrip(". ")
    tail = f"Length: {int(round(gen_seconds))} seconds"
    return f"{body}. {tail}" if body else tail


def workflow(ckpt: str, text: str, negative: str, seconds: float, seed: int,
             steps: int, cfg: float) -> dict:
    sampler = {"steps": int(steps), "cfg": float(cfg), "sampler_name": "lcm",
               "scheduler": "simple", "denoise": 1.0}
    return {
        "25": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "26": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "stable_audio", "device": "default"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["26", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["26", 0]}},
        "11": {"class_type": "EmptyLatentAudio", "inputs": {"seconds": float(seconds), "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {"model": ["25", 0], "positive": ["6", 0], "negative": ["7", 0],
              "latent_image": ["11", 0], "seed": int(seed), **sampler}},
        "12": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["3", 0], "vae": ["25", 2]}},
        _SAVE_NODE: {"class_type": "SaveAudio", "inputs": {"audio": ["12", 0], "filename_prefix": "otomaker"}},
    }


class SA3ComfyBackend(Backend):
    """included_model_load is True for the first generation of this process and
    the first one after models were freed with /free. ComfyUI does not report
    whether it actually (re)loaded the checkpoint, so this is a guess: a
    ComfyUI that already had the model in memory still reports True once, and
    one that evicted it on its own reports False."""
    name = "sa3-comfy"
    sample_rate = SAMPLE_RATE

    poll_interval = 0.3
    timeout_seconds = 1800.0   # give up waiting for one prompt after this long
    http_timeout = 30.0

    def __init__(self, host: str | None = None, model: str | None = None,
                 length_suffix: bool | str | None = None,
                 free: bool | str | None = None) -> None:
        super().__init__()
        host = (host or os.environ.get("OTOMAKER_COMFY_HOST") or DEFAULT_HOST).strip()
        if "://" in host:
            host = urllib.parse.urlsplit(host).netloc
        self.host = host.rstrip("/")
        port = urllib.parse.urlsplit(f"http://{self.host}").port
        self.port = port if port is not None else 80

        self.model = (model or os.environ.get("OTOMAKER_SA3_MODEL") or DEFAULT_MODEL).strip()
        if self.model not in MODELS:
            raise RuntimeError(f"unknown OTOMAKER_SA3_MODEL {self.model!r}; "
                               f"choose one of {', '.join(MODELS)}")
        self.ckpt, self.max_seconds = MODELS[self.model]
        self.length_suffix = _flag(
            length_suffix if length_suffix is not None
            else os.environ.get("OTOMAKER_COMFY_LENGTH_SUFFIX"), True)
        # /free unloads everything in that ComfyUI, so it is opt-in.
        self.free = _flag(free if free is not None
                          else os.environ.get("OTOMAKER_COMFY_FREE"), False)
        self.model_label = f"{self.model} ({self.ckpt}, comfyui @ {self.host})"

        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sa3-comfy")
        self._used = False       # a generation has been sent since start / last /free
        self._fresh = True       # next generation counts as including the model load

    # ── HTTP ─────────────────────────────────────────────────────────────────
    def _http(self, path: str, data: dict | None = None) -> bytes:
        url = f"http://{self.host}{path}"
        body = json.dumps(data).encode("utf-8") if data is not None else None
        r = urllib.request.Request(url, data=body,
                                   headers={"Content-Type": "application/json"} if body else {})
        try:
            with urllib.request.urlopen(r, timeout=self.http_timeout) as f:
                return f.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:1500]
            raise RuntimeError(f"ComfyUI at {self.host} answered HTTP {e.code} for {path}: {detail}") from None
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            # A timeout may come after ComfyUI queued the prompt, so it never falls back.
            err = RuntimeError if isinstance(reason, TimeoutError) else ComfyUnreachable
            raise err(
                f"cannot reach ComfyUI at http://{self.host} ({reason}). Start ComfyUI there "
                "(this server does not start it) or set OTOMAKER_COMFY_HOST.") from None

    def _json(self, path: str, data: dict | None = None):
        return json.loads(self._http(path, data))

    # ── Backend ──────────────────────────────────────────────────────────────
    @property
    def executor(self) -> Executor:
        return self._pool

    def loaded(self) -> bool:
        # What ComfyUI holds is not visible; "used since start / last unload"
        # lets the idle reaper free the models once after a period of use.
        return self._used

    def _preload(self) -> None:
        # ComfyUI loads checkpoints when a prompt runs; only check it is up.
        self._json("/system_stats")

    def _unload(self) -> bool:
        was, self._used = self._used, False
        if not self.free:
            _log("OTOMAKER_COMFY_FREE is not 1: models left loaded in ComfyUI, /free not called")
            return False
        self._http("/free", {"unload_models": True, "free_memory": True})
        self._fresh = True
        return was

    def prompt_text(self, req: GenerationRequest) -> str:
        if not self.length_suffix:
            return req.prompt
        return length_text(req.prompt, max(MIN_SECONDS, req.seconds))

    def _run_one(self, graph: dict) -> tuple[np.ndarray, int]:
        # Only this submit can report ComfyUnreachable (nothing was queued yet).
        pid = self._json("/prompt", {"prompt": graph, "client_id": "otomaker"})["prompt_id"]
        try:
            return self._fetch(pid)
        except ComfyUnreachable as e:
            # ComfyUI accepted the prompt, so a lost connection is an ordinary error.
            raise RuntimeError(str(e)) from e

    def _fetch(self, pid: str) -> tuple[np.ndarray, int]:
        deadline = time.time() + self.timeout_seconds
        while True:
            h = self._json(f"/history/{urllib.parse.quote(str(pid))}")
            if pid in h:
                break
            if time.time() > deadline:
                raise RuntimeError(f"ComfyUI prompt {pid} did not finish within {self.timeout_seconds:g}s")
            time.sleep(self.poll_interval)
        entry = h[pid]
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            raise RuntimeError("ComfyUI generation failed: "
                               + json.dumps(status, ensure_ascii=False)[:1500])
        try:
            f = entry["outputs"][_SAVE_NODE]["audio"][0]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"ComfyUI prompt {pid} produced no audio: "
                               + json.dumps(entry.get("outputs", {}), ensure_ascii=False)[:500]) from None
        q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                                    "type": f.get("type", "output")})
        data = self._http(f"/view?{q}")

        import soundfile as sf
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        audio = audio.T
        if audio.shape[0] == 1:
            audio = np.concatenate([audio, audio])
        return np.ascontiguousarray(audio, dtype=np.float32), int(sr)

    def _generate(self, seeds: list[int], req: GenerationRequest) -> GenerationResult:
        if req.init_audio:
            raise NotImplementedError(
                "sa3-comfy does text-to-audio only; variation (init_audio) is not supported. "
                "Use the sa3-tflite backend for edit_audio.")
        if req.inpaint_audio:
            raise NotImplementedError(
                "sa3-comfy does text-to-audio only; inpaint / continue is not supported. "
                "Use the sa3-tflite backend for edit_audio.")
        gen_seconds = max(MIN_SECONDS, float(req.seconds))
        text = self.prompt_text(req)
        res = GenerationResult(prompt_used=text, included_model_load=self._fresh)
        t0 = time.time()
        for seed in seeds:
            graph = workflow(self.ckpt, text, req.negative_prompt or "", gen_seconds, seed,
                             req.steps, req.cfg)
            try:
                audio, sr = self._run_one(graph)
            except ComfyUnreachable as e:
                if res.audios:   # a candidate exists already: do not finish the rest elsewhere
                    raise RuntimeError(str(e)) from e
                raise
            self._used = True
            self._fresh = False
            if sr != self.sample_rate:
                _log(f"ComfyUI returned {sr} Hz, expected {self.sample_rate} Hz; audio kept as is")
            if req.seconds < gen_seconds:
                audio = np.ascontiguousarray(audio[:, :int(round(req.seconds * sr))])
            res.audios.append(audio)
        res.wall_seconds = time.time() - t0
        return res
