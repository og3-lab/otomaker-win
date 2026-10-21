"""SA3TFLiteBackend against a stub of the upstream runtime (no LiteRT, no weights)."""
import os
import sys

import numpy as np
import pytest

from otomaker.backends import BACKENDS, GenerationRequest, resolve_backend_name
from otomaker.backends import sa3_tflite
from otomaker.backends.sa3_tflite import SA3TFLiteBackend

STUB = '''
import concurrent.futures as _cf
import numpy as np
SAMPLE_RATE = 44100
PRECISIONS = ("fp32", "w8a8")
DEFAULT_DECODERS = {"sm-music": "same-s", "sm-sfx": "same-s", "medium": "same-s"}
_THREADS = 8
_EXECUTOR = _cf.ThreadPoolExecutor(max_workers=1)
_t5 = None
_tok = None
_dit_cache, _dit_lru, _dec_cache, _dec_lru = {}, [], {}, []
_enc_cache, _enc_lru, _latent_cache = {}, [], {}
calls = []
print("import banner on stdout")
def run_generation(dit_name, decoder_name, precision, prompt, negative_prompt, seconds, steps,
                   seed, cfg, apg, sigma_max, a2a_audio_path=None, inpaint_audio_path=None,
                   inpaint_range_sec=None, lora_specs=None, cfg_batched=True):
    global _t5
    print("progress on stdout")
    first = not _dit_cache
    _t5 = object()
    _dit_cache["dit"] = object(); _dit_lru.append("dit")
    _dec_cache[(decoder_name, precision)] = object(); _dec_lru.append((decoder_name, precision))
    if a2a_audio_path or inpaint_audio_path:
        _enc_cache[(decoder_name, precision)] = object()
        _latent_cache["x"] = object()
    calls.append(dict(dit_name=dit_name, decoder_name=decoder_name, precision=precision,
                      seed=seed, seconds=seconds, steps=steps, cfg=cfg, apg=apg,
                      sigma_max=sigma_max, a2a=a2a_audio_path, inpaint=inpaint_audio_path,
                      range=inpaint_range_sec, threads=_THREADS))
    # float64 on purpose: the backend must hand float32 to the server.
    audio = np.zeros((2, int(round(seconds * SAMPLE_RATE))), np.float64)
    return audio, {"dit_load_ms": 12.0 if first else 0.0}
'''


def put_models(tflite_dir, models=("sm-sfx", "sm-music", "medium"),
               precisions=("w8a8", "fp32"), decoders=("same-s", "same-l")):
    for m in models:
        for prec in precisions:
            for dec in decoders:
                for rel in sa3_tflite.model_files(m, prec, dec):
                    f = tflite_dir / "models" / rel
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(b"w")


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    scripts = tmp_path / "tflite" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "sa3_gradio.py").write_text(STUB, encoding="utf-8")
    put_models(tmp_path / "tflite")
    monkeypatch.delitem(sys.modules, "sa3_gradio", raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    for var in ("OTOMAKER_SA3_MODEL", "OTOMAKER_SA3_PRECISION",
                "OTOMAKER_SA3_THREADS", "OTOMAKER_SA3_DECODER", "OTOMAKER_SA3_AUTO_DOWNLOAD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OTOMAKER_SA3_TFLITE_DIR", str(tmp_path / "tflite"))
    yield tmp_path / "tflite"
    sys.modules.pop("sa3_gradio", None)


def make(upstream, monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("sa3_gradio", None)
    return SA3TFLiteBackend()


def test_default_backend_is_tflite(monkeypatch):
    assert "sa3-tflite" in BACKENDS and "sa3-comfy" in BACKENDS
    monkeypatch.delenv("OTOMAKER_BACKEND", raising=False)
    assert resolve_backend_name() == "sa3-tflite"
    assert resolve_backend_name("sa3-tflite") == "sa3-tflite"
    with pytest.raises(RuntimeError, match="OTOMAKER_BACKEND"):
        resolve_backend_name("auto")


@pytest.mark.parametrize("model,dit,max_s", [
    ("sm-sfx", "sm-sfx", 120), ("sm-music", "sm-music", 120), ("medium", "medium", 380)])
def test_model_mapping(upstream, monkeypatch, model, dit, max_s):
    b = make(upstream, monkeypatch, OTOMAKER_SA3_MODEL=model)
    assert (b.dit, b.max_seconds, b.sample_rate) == (dit, max_s, 44100)
    assert b.precision == "w8a8" and b.decoder == "same-s"
    b._generate([1], GenerationRequest(prompt="p", seconds=1))
    c = b._g.calls[-1]
    assert (c["dit_name"], c["decoder_name"], c["precision"]) == (dit, "same-s", "w8a8")


def test_bad_settings(upstream, monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="OTOMAKER_SA3_MODEL"):
        make(upstream, monkeypatch, OTOMAKER_SA3_MODEL="large")
    monkeypatch.setenv("OTOMAKER_SA3_MODEL", "sm-sfx")
    with pytest.raises(RuntimeError, match="OTOMAKER_SA3_PRECISION"):
        make(upstream, monkeypatch, OTOMAKER_SA3_PRECISION="w4a4")
    with pytest.raises(RuntimeError, match="OTOMAKER_SA3_TFLITE_DIR"):
        SA3TFLiteBackend(upstream_dir=tmp_path / "missing")


def test_default_dir_is_inside_the_otomaker_folder(monkeypatch):
    # Run from a checkout (the install.cmd layout), the runtime defaults to a
    # folder next to the code, like outputs\.
    from otomaker import paths
    root = paths.CHECKOUT_DIR
    assert (root / "pyproject.toml").is_file()
    assert sa3_tflite.DEFAULT_TFLITE_DIR == root / "stable-audio-3" / "optimized" / "tflite"
    monkeypatch.delenv("OTOMAKER_SA3_TFLITE_DIR", raising=False)
    monkeypatch.setattr(sa3_tflite, "DEFAULT_TFLITE_DIR", root / "no-such-runtime")
    with pytest.raises(RuntimeError, match="no-such-runtime") as e:
        SA3TFLiteBackend()
    assert "otomaker-download" in str(e.value)   # the message says what to run


@pytest.mark.parametrize("model,env,cmd", [
    ("sm-sfx", {}, "otomaker-download sfx`"),
    ("medium", {"OTOMAKER_SA3_PRECISION": "fp32", "OTOMAKER_SA3_DECODER": "same-l"},
     "otomaker-download medium --precision fp32 --decoder same-l`"),
])
def test_missing_model_files_name_the_download_command(upstream, monkeypatch, model, env, cmd):
    import shutil
    shutil.rmtree(upstream / "models")
    b = make(upstream, monkeypatch, OTOMAKER_SA3_MODEL=model, **env)
    with pytest.raises(RuntimeError, match="not downloaded yet") as e:
        b._generate([1], GenerationRequest(prompt="p", seconds=1))
    assert cmd in str(e.value) and "consent" in str(e.value)
    with pytest.raises(RuntimeError, match="not downloaded yet"):
        b._preload()
    assert b._g.calls == []   # upstream was never asked to fetch them itself
    monkeypatch.setenv("OTOMAKER_SA3_AUTO_DOWNLOAD", "1")   # upstream's lazy download, on request
    b._generate([1], GenerationRequest(prompt="p", seconds=1))
    assert len(b._g.calls) == 1


def test_the_encoder_is_needed_only_for_edits(upstream, monkeypatch):
    (upstream / "models" / "tflite" / "same-s" / "enc_w8a8.tflite").unlink()
    b = make(upstream, monkeypatch)
    b._generate([1], GenerationRequest(prompt="p", seconds=1))
    with pytest.raises(RuntimeError, match="enc_w8a8.tflite"):
        b._generate([1], GenerationRequest(prompt="p", seconds=1, init_audio="a.wav"))


@pytest.mark.skipif(os.name != "nt", reason="Windows paths")
def test_ascii_path_forms(tmp_path, monkeypatch):
    from otomaker.backends.sa3_tflite import _ascii_path, _needs_cwd
    assert _ascii_path(r"C:\plain\model.tflite") == r"C:\plain\model.tflite"
    assert _ascii_path(None) is None
    jp = tmp_path / "日本語フォルダ"
    (jp / "models").mkdir(parents=True)
    f = jp / "models" / "m.tflite"
    f.write_bytes(b"x")
    monkeypatch.setattr(sa3_tflite, "_short_path", lambda p: p)   # no ASCII short form
    assert _needs_cwd(jp)
    monkeypatch.chdir(jp)
    assert _ascii_path(str(f)) == os.path.join("models", "m.tflite")
    # a file that does not exist yet (the XNNPACK weight cache) works the same way
    assert _ascii_path(str(f) + ".xnnwc") == os.path.join("models", "m.tflite.xnnwc")
    # outside the working directory there is no ASCII form: keep the path
    other = tmp_path / "別の場所" / "x.tflite"
    assert _ascii_path(str(other)) == str(other)
    monkeypatch.setattr(sa3_tflite, "_short_path", lambda p: r"C:\SHORT~1\M.TFL")
    assert _ascii_path(str(other)) == r"C:\SHORT~1\M.TFL"
    assert not _needs_cwd(jp)


@pytest.mark.skipif(os.name != "nt", reason="Windows paths")
def test_non_ascii_runtime_folder_becomes_the_working_directory(tmp_path, monkeypatch):
    scripts = tmp_path / "日本語" / "tflite" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "sa3_gradio.py").write_text(STUB, encoding="utf-8")
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sa3_tflite, "_short_path", lambda p: p)
    sys.modules.pop("sa3_gradio", None)
    monkeypatch.chdir(tmp_path)   # restored after the test
    try:
        b = SA3TFLiteBackend(upstream_dir=scripts.parent)
        assert os.getcwd() == str(b.tflite_dir)
    finally:
        sys.modules.pop("sa3_gradio", None)


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_litert_and_sentencepiece_wrappers_install_once():
    pytest.importorskip("ai_edge_litert")
    spm = pytest.importorskip("sentencepiece")
    from ai_edge_litert import compiled_model, environment, interpreter
    sa3_tflite._litert_ascii_paths()
    sa3_tflite._sentencepiece_unicode_paths()
    first = (environment._env.CreateEnvironment, interpreter._interpreter_wrapper.CreateWrapperFromFile,
             compiled_model._cm.CreateCompiledModelFromFile, spm.SentencePieceProcessor.LoadFromFile)
    sa3_tflite._litert_ascii_paths()
    sa3_tflite._sentencepiece_unicode_paths()
    second = (environment._env.CreateEnvironment, interpreter._interpreter_wrapper.CreateWrapperFromFile,
              compiled_model._cm.CreateCompiledModelFromFile, spm.SentencePieceProcessor.LoadFromFile)
    assert first == second and all(getattr(f, "_ascii_wrapped", False) or
                                   getattr(f, "_unicode_wrapped", False) for f in first)


def test_threads(upstream, monkeypatch):
    b = make(upstream, monkeypatch, OTOMAKER_SA3_THREADS="3")
    b._generate([1], GenerationRequest(prompt="p", seconds=1))
    assert b._g._THREADS == 3 and b._g.calls[-1]["threads"] == 3
    monkeypatch.delenv("OTOMAKER_SA3_THREADS")
    assert 1 <= make(upstream, monkeypatch).threads <= sa3_tflite.MAX_DEFAULT_THREADS


def test_generate_shape_seed_and_quiet_stdout(upstream, monkeypatch, capsys):
    b = make(upstream, monkeypatch, OTOMAKER_SA3_MODEL="sm-sfx")
    r1 = b._generate([5, 6], GenerationRequest(prompt="p", seconds=2, steps=4, cfg=3.0))
    r2 = b._generate([7], GenerationRequest(prompt="p", seconds=3))
    g = b._g
    assert [c["seed"] for c in g.calls] == [5, 6, 7]
    assert g.calls[0]["steps"] == 4 and g.calls[0]["cfg"] == 3.0
    assert g.calls[0]["apg"] == 1.0 and g.calls[0]["sigma_max"] == 1.0 and g.calls[0]["a2a"] is None
    for a in r1.audios + r2.audios:
        assert a.ndim == 2 and a.shape[0] == 2 and a.dtype == np.float32
    assert r1.audios[0].shape == (2, 88200) and r2.audios[0].shape == (2, 132300)
    assert r1.included_model_load and not r2.included_model_load
    assert capsys.readouterr().out == ""


def test_edit_requests_map_to_upstream_kwargs(upstream, monkeypatch):
    b = make(upstream, monkeypatch)
    g = b._g
    b._generate([1], GenerationRequest(prompt="p", seconds=4, init_audio="a.wav", init_strength=0.4))
    assert g.calls[-1]["a2a"] == "a.wav" and g.calls[-1]["sigma_max"] == 0.4
    b._generate([1], GenerationRequest(prompt="p", seconds=6, inpaint_audio="b.wav", inpaint_range=(4, 6)))
    assert g.calls[-1]["inpaint"] == "b.wav" and g.calls[-1]["range"] == (4, 6)
    assert g.calls[-1]["sigma_max"] == 1.0
    with pytest.raises(ValueError, match="time range"):
        b._generate([1], GenerationRequest(prompt="p", seconds=6, inpaint_audio="b.wav"))


def test_unload(upstream, monkeypatch):
    b = make(upstream, monkeypatch)
    assert not b.loaded()
    b._generate([1], GenerationRequest(prompt="p", seconds=1, init_audio="a.wav"))
    assert b.loaded()
    assert b._unload() is True and not b.loaded()
    g = b._g
    assert not (g._dit_cache or g._dit_lru or g._dec_cache or g._dec_lru or g._enc_cache
                or g._latent_cache) and g._t5 is None and g._tok is None
    assert b._unload() is False
    # Reloads on the next call.
    assert b._generate([2], GenerationRequest(prompt="p", seconds=1)).included_model_load


def test_preload_and_async_paths(upstream, monkeypatch, capsys):
    import asyncio
    b = make(upstream, monkeypatch)
    b._preload()
    assert b.loaded()
    res = asyncio.run(b.generate([9], GenerationRequest(prompt="p", seconds=1)))
    assert res.audios[0].shape == (2, 44100) and b._g.calls[-1]["seed"] == 9
    assert asyncio.run(b.unload()) is True
    assert capsys.readouterr().out == ""


@pytest.mark.skipif(os.name != "nt", reason="Windows paths")
def test_environment_paths_without_an_ascii_form_are_left_empty(monkeypatch):
    from otomaker.backends.sa3_tflite import _env_path
    monkeypatch.setattr(sa3_tflite, "_short_path", lambda p: p)
    assert _env_path(r"C:\Users\山田太郎\venv\ai_edge_litert") == ""
    assert _env_path(r"C:\plain\ai_edge_litert") == r"C:\plain\ai_edge_litert"
    assert _env_path("") == "" and _env_path(None) == ""
    monkeypatch.setattr(sa3_tflite, "_short_path", lambda p: r"C:\Users\YAMADA~1\venv")
    assert _env_path(r"C:\Users\山田太郎\venv") == r"C:\Users\YAMADA~1\venv"
