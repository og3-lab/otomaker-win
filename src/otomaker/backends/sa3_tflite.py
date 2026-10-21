"""Stable Audio 3 on CPU via the official TFLite / LiteRT runtime (Windows).

Wraps upstream optimized/tflite (Stability-AI/stable-audio-3, MIT). The upstream
code is not bundled; it is imported at run time from OTOMAKER_SA3_TFLITE_DIR.
Verified against upstream commit 77e0398 (check it out with
`git checkout 77e0398`); later commits may rename the internals below.

Generation goes through sa3_gradio.run_generation, the upstream cached-model
path used by its web UI, so results match upstream ./sa3-gradio for the same
seed, model and precision.

Upstream internals used here (scripts/sa3_gradio.py at 77e0398):
  functions  run_generation (dit_name, decoder_name, precision, seed, prompt,
             negative_prompt, seconds, steps, cfg, apg, sigma_max,
             a2a_audio_path, inpaint_audio_path, inpaint_range_sec; returns
             (audio, timings) with timings["dit_load_ms"])
  caches     _dit_cache, _dit_lru, _dec_cache, _dec_lru, _enc_cache, _enc_lru,
             _latent_cache, _t5, _tok
  globals    _THREADS, _EXECUTOR, DEFAULT_DECODERS, PRECISIONS, SAMPLE_RATE
  modules    spec.render_spectrogram_png (stubbed when Pillow is missing)
  LiteRT     environment._env.CreateEnvironment,
             interpreter._interpreter_wrapper.CreateWrapperFromFile and
             compiled_model._cm.CreateCompiledModelFromFile of ai_edge_litert
             (2.3.0), wrapped to pass ASCII paths: the 8.3 short form, else
             the path relative to the runtime folder (environment paths:
             else empty); SentencePieceProcessor.LoadFromFile likewise

Weights come from `otomaker-download` (it shows the model licences and asks
for consent first): it fetches them into the Hugging Face cache (HF_HOME) and
links them under <tflite dir>/models/ (symlink, else hardlink, else copy), as
upstream weights.ensure_local does. A generation whose files are missing
fails with the otomaker-download command to run, instead of letting upstream
download them without that consent; OTOMAKER_SA3_AUTO_DOWNLOAD=1 restores
upstream's download on first use.

Environment:
  OTOMAKER_SA3_TFLITE_DIR  upstream optimized/tflite dir (default
                               <data folder>\\stable-audio-3\\optimized\\tflite,
                               see otomaker.paths; `otomaker-download` puts it there)
  OTOMAKER_SA3_MODEL       sm-sfx | sm-music | medium (default sm-music)
  OTOMAKER_SA3_PRECISION   w8a8 (default) | fp32
  OTOMAKER_SA3_DECODER     same-s | same-l (default: upstream's pairing, same-s)
  OTOMAKER_SA3_THREADS     XNNPACK threads (default: physical cores via psutil,
                               at most 10; logical cores if psutil is missing)
"""
from __future__ import annotations

import contextlib
import gc
import os
import sys
import time
import types
from concurrent.futures import Executor
from pathlib import Path

import numpy as np

from .. import paths
from .base import Backend, GenerationRequest, GenerationResult

DEFAULT_TFLITE_DIR = paths.default_tflite_dir()
UPSTREAM_COMMIT = "77e0398"   # the stable-audio-3 commit this backend was verified with

# Our model name → (upstream DiT name, max seconds). The names coincide today;
# the table keeps the public names stable if upstream renames.
MODELS = {
    "medium": ("medium", 380.0),
    "sm-music": ("sm-music", 120.0),
    "sm-sfx": ("sm-sfx", 120.0),
}
DEFAULT_MODEL = "sm-music"
# otomaker-download's name for each model
DOWNLOAD_NAMES = {"sm-sfx": "sfx", "sm-music": "music", "medium": "medium"}
# DiT sub-folder per model, as in upstream weights.DIT_SUBDIR (77e0398).
DIT_SUBDIR = {"sm-music": "sa3-sm-music", "sm-sfx": "sa3-sm-sfx", "medium": "sa3-m"}
DEFAULT_PRECISION = "w8a8"
MAX_DEFAULT_THREADS = 10


def model_files(model: str, precision: str = "w8a8", decoder: str = "same-s",
                encoder: bool = True) -> list[str]:
    """Files one model needs, relative to <tflite dir>/models and equal to their
    path in the Hugging Face repository: DiT, SAME codec (the encoder only for
    edit_audio; upstream ships the codec at w8a8 for every DiT precision) and
    the shared T5Gemma text encoder."""
    rels = [f"tflite/{DIT_SUBDIR[model]}/dit_{precision}.tflite"]
    if encoder:
        rels.append(f"tflite/{decoder}/enc_w8a8.tflite")
    rels += [f"tflite/{decoder}/dec_w8a8.tflite", "tflite/t5gemma/encoder_fp16.tflite"]
    return rels


def default_threads() -> int:
    """Physical core count (logical count if unknown), capped at MAX_DEFAULT_THREADS."""
    n = None
    try:
        import psutil
        n = psutil.cpu_count(logical=False)
    except Exception:
        pass
    n = n or os.cpu_count() or 4
    return max(1, min(int(n), MAX_DEFAULT_THREADS))


def _stub_spec_if_no_pillow() -> None:
    """sa3_gradio imports spec.render_spectrogram_png (web UI only), which needs
    Pillow at import time. Without Pillow, register a stand-in so generation
    still works; the spectrogram is never used here."""
    if "spec" in sys.modules:
        return
    try:
        import PIL  # noqa: F401
    except ImportError:
        mod = types.ModuleType("spec")

        def render_spectrogram_png(*_a, **_k):
            raise RuntimeError("spectrogram rendering needs Pillow")

        mod.render_spectrogram_png = render_spectrogram_png
        sys.modules["spec"] = mod


def _short_path(p: str | None) -> str | None:
    """Windows 8.3 short form of a path, or p unchanged. For a path that does
    not exist yet (a weight cache about to be written) the existing parent is
    shortened and the name kept."""
    if not p or os.name != "nt" or p.isascii():
        return p
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, len(buf))
    if 0 < n < len(buf):
        return buf.value
    head, tail = os.path.split(str(p))
    if head and tail and head != p:
        short_head = _short_path(head)
        if short_head != head:
            return os.path.join(short_head, tail)
    return p


def _ascii_path(p):
    """A form of p the LiteRT C++ code can open on Windows, where it hands the
    UTF-8 bytes of the path to the ANSI file API: p itself if ASCII, else its
    8.3 short form if that is ASCII, else its path relative to the working
    directory if that is ASCII (see _needs_cwd), else the short form."""
    if p is None or os.name != "nt":
        return p
    s = os.fspath(p)
    if not s or s.isascii():
        return p
    short = _short_path(s)
    if short and short.isascii():
        return short
    try:
        rel = os.path.relpath(s)
    except ValueError:   # on another drive
        rel = ""
    if rel.isascii() and rel and not rel.startswith(".."):
        return rel
    # A short form that still has non-ASCII characters works for the
    # environment (measured: the venv under a Japanese folder on cp932), so
    # prefer it to the long form.
    return short or p


def _env_path(p) -> str:
    """A path for LiteRT's CreateEnvironment: the _ascii_path form, or "" when
    there is no ASCII form. The environment's paths (the ai_edge_litert package
    folder and its NPU vendor plugins in the venv) only locate GPU / NPU
    accelerators; the CPU (XNNPACK) path does not need them (measured: the
    same samples with all three empty). A non-ASCII one fails or not
    depending on its bytes ("No mapping for the Unicode character…", measured
    on cp932 for C:\\…\\山田太郎 but not C:\\…\\ユーザー), so it is never passed."""
    if not p:
        return ""
    a = os.fspath(_ascii_path(p))
    return a if a.isascii() else ""


def _needs_cwd(folder: Path) -> bool:
    """True if neither folder nor its 8.3 short form is ASCII (a Japanese
    folder name, for instance, keeps its Japanese characters in the short
    form). LiteRT can then open the model files under it only through ASCII
    paths relative to the working directory."""
    if os.name != "nt":
        return False
    s = str(folder)
    return not s.isascii() and not (_short_path(s) or "").isascii()


def _litert_ascii_paths() -> None:
    """LiteRT on Windows passes paths to the ANSI file API: a path with
    characters the code page lacks fails ("No mapping for the Unicode
    character…" for the environment), and on any code page a non-ASCII model
    path fails ("Could not open …", measured on cp932 with a Japanese folder).
    Wrap the three places paths enter LiteRT (environment, Interpreter from
    file, CompiledModel from file and its XNNPACK weight cache) so they get
    the _ascii_path form."""
    if os.name != "nt":
        return
    try:
        from ai_edge_litert import compiled_model as cm_mod
        from ai_edge_litert import environment as env_mod
        from ai_edge_litert import interpreter as interp_mod
    except ImportError:
        return

    env = env_mod._env
    if not getattr(env.CreateEnvironment, "_ascii_wrapped", False):
        real_env = env.CreateEnvironment

        def create_env(runtime_path="", compiler_plugin_path="", dispatch_library_path=""):
            return real_env(runtime_path=_env_path(runtime_path),
                            compiler_plugin_path=_env_path(compiler_plugin_path),
                            dispatch_library_path=_env_path(dispatch_library_path))

        create_env._ascii_wrapped = True
        env.CreateEnvironment = create_env

    wrapper = interp_mod._interpreter_wrapper
    if not getattr(wrapper.CreateWrapperFromFile, "_ascii_wrapped", False):
        real_interp = wrapper.CreateWrapperFromFile

        def create_interp(model_path, *args, **kwargs):
            return real_interp(_ascii_path(model_path), *args, **kwargs)

        create_interp._ascii_wrapped = True
        wrapper.CreateWrapperFromFile = create_interp

    cm = cm_mod._cm
    if not getattr(cm.CreateCompiledModelFromFile, "_ascii_wrapped", False):
        real_cm = cm.CreateCompiledModelFromFile

        def create_cm(env_capsule, model_path, *args, **kwargs):
            if kwargs.get("xnnpack_weight_cache_path"):
                kwargs["xnnpack_weight_cache_path"] = _ascii_path(
                    kwargs["xnnpack_weight_cache_path"])
            return real_cm(env_capsule, _ascii_path(model_path), *args, **kwargs)

        create_cm._ascii_wrapped = True
        cm.CreateCompiledModelFromFile = create_cm


def _sentencepiece_unicode_paths() -> None:
    """SentencePiece's LoadFromFile cannot open a non-ASCII path on Windows
    either ("NOT_FOUND … No such file"). Read such a file in Python and hand
    the bytes to LoadFromSerializedProto instead."""
    if os.name != "nt":
        return
    try:
        import sentencepiece as spm
    except ImportError:
        return
    cls = spm.SentencePieceProcessor
    if getattr(cls.LoadFromFile, "_unicode_wrapped", False):
        return
    real = cls.LoadFromFile

    def load_from_file(self, filename):
        s = os.fspath(filename)
        if s.isascii():
            return real(self, filename)
        with open(s, "rb") as f:
            return self.LoadFromSerializedProto(f.read())

    load_from_file._unicode_wrapped = True
    cls.LoadFromFile = load_from_file


class SA3TFLiteBackend(Backend):
    name = "sa3-tflite"

    def __init__(self, upstream_dir: Path | str | None = None, model: str | None = None,
                 precision: str | None = None, threads: int | None = None,
                 decoder: str | None = None) -> None:
        super().__init__()
        self.tflite_dir = Path(upstream_dir or os.environ.get("OTOMAKER_SA3_TFLITE_DIR")
                               or DEFAULT_TFLITE_DIR).expanduser().resolve()
        scripts = self.tflite_dir / "scripts"
        if not (scripts / "sa3_gradio.py").is_file():
            raise RuntimeError(
                f"Stable Audio 3 TFLite runtime not found at {self.tflite_dir}. "
                "Run `otomaker-download --runtime-only` (or `otomaker-download "
                "<models>`, which also fetches the runtime), with the same uvx --from "
                "source as otomaker-mcp if you use uvx; or set OTOMAKER_SA3_TFLITE_DIR "
                "to the optimized/tflite folder of a stable-audio-3 checkout "
                f"(verified with commit {UPSTREAM_COMMIT}).")

        self.model = (model or os.environ.get("OTOMAKER_SA3_MODEL") or DEFAULT_MODEL).strip()
        if self.model not in MODELS:
            raise RuntimeError(f"unknown OTOMAKER_SA3_MODEL {self.model!r}; "
                               f"choose one of {', '.join(MODELS)}")
        self.dit, self.max_seconds = MODELS[self.model]

        t = threads if threads is not None else os.environ.get("OTOMAKER_SA3_THREADS")
        try:
            self.threads = int(t) if t not in (None, "") else default_threads()
        except ValueError:
            raise RuntimeError(f"OTOMAKER_SA3_THREADS must be an integer, got {t!r}") from None
        if self.threads < 1:
            raise RuntimeError(f"OTOMAKER_SA3_THREADS must be >= 1, got {self.threads}")

        # Upstream prints banners/progress to stdout, which would corrupt the
        # stdio JSON-RPC stream. Import with stdout pointed at stderr; every
        # model call is wrapped the same way.
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        if _needs_cwd(self.tflite_dir):
            # LiteRT can reach the model files only through ASCII paths
            # relative to the runtime folder. The server resolves relative
            # tool inputs against its own start folder, so they are unaffected.
            os.chdir(self.tflite_dir)
            print(f"[otomaker] {self.tflite_dir} has no ASCII form; working "
                  "directory set to it so LiteRT can open the models", file=sys.stderr)
        with contextlib.redirect_stdout(sys.stderr):
            _stub_spec_if_no_pillow()
            _litert_ascii_paths()
            _sentencepiece_unicode_paths()
            import sa3_gradio as g
        self._g = g
        self.sample_rate = int(g.SAMPLE_RATE)
        g._THREADS = self.threads   # read by every interpreter upstream creates

        self.precision = (precision or os.environ.get("OTOMAKER_SA3_PRECISION")
                          or DEFAULT_PRECISION).strip()
        if self.precision not in tuple(g.PRECISIONS):
            raise RuntimeError(f"unknown OTOMAKER_SA3_PRECISION {self.precision!r}; "
                               f"choose one of {', '.join(g.PRECISIONS)}")
        self.decoder = (decoder or os.environ.get("OTOMAKER_SA3_DECODER")
                        or g.DEFAULT_DECODERS.get(self.dit, "same-s")).strip()
        self.model_label = f"{self.dit} + {self.decoder} ({self.precision}, tflite)"

    @property
    def executor(self) -> Executor:
        # Upstream's single owner thread: an XNNPACK interpreter must never be
        # invoked from two threads at once.
        return self._g._EXECUTOR

    def loaded(self) -> bool:
        g = self._g
        return bool(g._dit_cache or g._dec_cache or g._enc_cache or g._t5 is not None)

    def _unload(self) -> bool:
        g = self._g
        was = self.loaded()
        g._dit_cache.clear()
        g._dit_lru.clear()
        g._dec_cache.clear()
        g._dec_lru.clear()
        g._enc_cache.clear()
        g._enc_lru.clear()
        g._latent_cache.clear()
        g._t5 = None
        g._tok = None
        gc.collect()
        return was

    def _run(self, seed: int, **kw):
        return self._g.run_generation(dit_name=self.dit, decoder_name=self.decoder,
                                      precision=self.precision, seed=seed, **kw)

    def _preload(self) -> None:
        # The DiT interpreter is built with its conditioning bound, so the
        # simplest full load is a tiny generation (cached by file path; later
        # lengths only re-bind).
        self._check_files(encoder=False)
        with contextlib.redirect_stdout(sys.stderr):
            self._run(0, prompt="", negative_prompt="", seconds=2.0, steps=1,
                      cfg=1.0, apg=1.0, sigma_max=1.0)

    def missing_files(self, encoder: bool = False) -> list[Path]:
        root = self.tflite_dir / "models"
        rels = model_files(self.model, self.precision, self.decoder, encoder)
        return [root / r for r in rels if not ((root / r).exists() or (root / r).is_symlink())]

    def _check_files(self, encoder: bool) -> None:
        if os.environ.get("OTOMAKER_SA3_AUTO_DOWNLOAD", "").strip() == "1":
            return
        missing = self.missing_files(encoder)
        if not missing:
            return
        cmd = f"otomaker-download {DOWNLOAD_NAMES[self.model]}"
        if self.precision != DEFAULT_PRECISION:
            cmd += f" --precision {self.precision}"
        if self.decoder != "same-s":
            cmd += f" --decoder {self.decoder}"
        raise RuntimeError(
            f"model files for {self.model} are not downloaded yet (missing: "
            f"{', '.join(p.name for p in missing)} under {self.tflite_dir / 'models'}). "
            f"Run `{cmd}` (with the same uvx --from source as otomaker-mcp if you use "
            "uvx). It shows the model licences and needs the user's consent; "
            "then call this tool again.")

    def _generate(self, seeds: list[int], req: GenerationRequest) -> GenerationResult:
        self._check_files(encoder=bool(req.init_audio or req.inpaint_audio))
        kw = dict(prompt=req.prompt, negative_prompt=req.negative_prompt,
                  seconds=req.seconds, steps=req.steps, cfg=req.cfg, apg=1.0,
                  sigma_max=1.0)
        if req.init_audio:
            kw.update(a2a_audio_path=req.init_audio, sigma_max=req.init_strength)
        if req.inpaint_audio:
            if req.inpaint_range is None:
                raise ValueError("inpaint needs a time range (start, end) in seconds")
            kw.update(inpaint_audio_path=req.inpaint_audio,
                      inpaint_range_sec=tuple(req.inpaint_range))
        res = GenerationResult()
        with contextlib.redirect_stdout(sys.stderr):
            t0 = time.time()
            for i, seed in enumerate(seeds):
                audio, timings = self._run(seed, **kw)
                res.audios.append(np.ascontiguousarray(audio, dtype=np.float32))
                if i == 0:
                    res.included_model_load = timings.get("dit_load_ms", 0) > 0
            res.wall_seconds = time.time() - t0
        return res
