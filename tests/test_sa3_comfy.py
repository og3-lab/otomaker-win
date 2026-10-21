"""SA3ComfyBackend against a fake ComfyUI (http.server on a free local port).

Never touches a real ComfyUI: the fake listens on an OS-assigned port, and the
unload tests replace the HTTP call with a recorder."""
import io
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from otomaker import server
from otomaker.backends import BACKENDS, GenerationRequest, create_backend
from otomaker.backends.sa3_comfy import ComfyUnreachable, SA3ComfyBackend


class FakeComfy:
    def __init__(self, sample_rate=44100, channels=2, fail=False):
        self.sample_rate, self.channels, self.fail = sample_rate, channels, fail
        self.prompts: dict[str, dict] = {}
        self.history_polls: dict[str, int] = {}
        self.paths: list[tuple[str, str]] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body: bytes, ctype="application/json", code=200):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                fake.paths.append(("GET", self.path))
                u = urllib.parse.urlsplit(self.path)
                if u.path == "/system_stats":
                    return self._send(b"{}")
                if u.path.startswith("/history/"):
                    pid = u.path.rsplit("/", 1)[1]
                    n = fake.history_polls[pid] = fake.history_polls.get(pid, 0) + 1
                    if n < 2:   # not finished on the first poll
                        return self._send(b"{}")
                    if fake.fail:
                        entry = {"status": {"status_str": "error", "messages": ["boom"]}, "outputs": {}}
                    else:
                        entry = {"status": {"status_str": "success"}, "outputs": {"13": {"audio": [
                            {"filename": f"{pid}.flac", "subfolder": "audio", "type": "output"}]}}}
                    return self._send(json.dumps({pid: entry}).encode())
                if u.path == "/view":
                    q = urllib.parse.parse_qs(u.query)
                    pid = q["filename"][0].split(".")[0]
                    secs = fake.prompts[pid]["11"]["inputs"]["seconds"]
                    seed = fake.prompts[pid]["3"]["inputs"]["seed"]
                    n = int(round(secs * fake.sample_rate))
                    data = np.full((n, fake.channels), (seed % 10) / 20, np.float32)
                    buf = io.BytesIO()
                    sf.write(buf, data, fake.sample_rate, format="FLAC")
                    return self._send(buf.getvalue(), "audio/flac")
                self._send(b"not found", code=404)

            def do_POST(self):
                fake.paths.append(("POST", self.path))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/prompt":
                    pid = f"p{len(fake.prompts)}"
                    fake.prompts[pid] = body["prompt"]
                    return self._send(json.dumps({"prompt_id": pid, "number": 0}).encode())
                self._send(b"not found", code=404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.host = f"127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def comfy(monkeypatch):
    for var in ("OTOMAKER_COMFY_HOST", "OTOMAKER_SA3_MODEL",
                "OTOMAKER_COMFY_LENGTH_SUFFIX"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(SA3ComfyBackend, "poll_interval", 0.01)
    fake = FakeComfy()
    monkeypatch.setenv("OTOMAKER_COMFY_HOST", fake.host)
    yield fake
    fake.close()


def test_registered(comfy, monkeypatch):
    assert "sa3-comfy" in BACKENDS
    monkeypatch.setenv("OTOMAKER_SA3_MODEL", "sm-sfx")
    b = create_backend("sa3-comfy")
    assert isinstance(b, SA3ComfyBackend) and b.host == comfy.host


@pytest.mark.parametrize("model,ckpt,max_s", [
    ("sm-sfx", "stable_audio_3_small_sfx.safetensors", 120.0),
    ("sm-music", "stable_audio_3_small_music.safetensors", 120.0),
    ("medium", "stable_audio_3_medium.safetensors", 380.0),
])
def test_model_table(comfy, model, ckpt, max_s):
    b = SA3ComfyBackend(model=model)
    assert b.ckpt == ckpt and b.max_seconds == max_s and b.sample_rate == 44100


def test_unknown_model(comfy):
    with pytest.raises(RuntimeError, match="OTOMAKER_SA3_MODEL"):
        SA3ComfyBackend(model="large")


def test_default_host(monkeypatch):
    monkeypatch.delenv("OTOMAKER_COMFY_HOST", raising=False)
    monkeypatch.delenv("OTOMAKER_COMFY_FREE", raising=False)
    b = SA3ComfyBackend()
    assert b.host == "127.0.0.1:8188" and b.port == 8188 and b.free is False


def test_generate_workflow_and_audio(comfy, monkeypatch, capsys):
    monkeypatch.setenv("OTOMAKER_SA3_MODEL", "sm-sfx")
    b = SA3ComfyBackend()
    req = GenerationRequest(prompt="TrackType: SFX, door slam.", seconds=2.0,
                            negative_prompt="hiss", steps=6, cfg=3.0)
    res = b._generate([5, 6], req)

    assert len(comfy.prompts) == 2
    for (pid, g), seed in zip(sorted(comfy.prompts.items()), (5, 6)):
        assert g["25"]["inputs"]["ckpt_name"] == "stable_audio_3_small_sfx.safetensors"
        assert g["26"]["inputs"] == {"clip_name": "t5gemma_b_b_ul2.safetensors",
                                     "type": "stable_audio", "device": "default"}
        assert g["6"]["inputs"]["text"] == "TrackType: SFX, door slam. Length: 2 seconds"
        assert g["7"]["inputs"]["text"] == "hiss"
        assert g["11"]["inputs"] == {"seconds": 2.0, "batch_size": 1}
        k = g["3"]["inputs"]
        assert (k["seed"], k["steps"], k["cfg"], k["sampler_name"], k["scheduler"], k["denoise"]) \
            == (seed, 6, 3.0, "lcm", "simple", 1.0)
        assert g["12"]["class_type"] == "VAEDecodeAudio" and g["13"]["class_type"] == "SaveAudio"
        assert comfy.history_polls[pid] >= 2   # waited through an unfinished poll

    assert res.prompt_used == "TrackType: SFX, door slam. Length: 2 seconds"
    assert len(res.audios) == 2
    for a in res.audios:
        assert a.dtype == np.float32 and a.shape == (2, 88200)
    assert res.audios[0][0, 0] == pytest.approx(0.25, abs=1e-3)   # seed 5 → 5/20
    assert res.included_model_load is True and res.wall_seconds > 0
    assert b._generate([1], GenerationRequest(prompt="x", seconds=1.0)).included_model_load is False
    assert capsys.readouterr().out == ""


def test_short_request_made_at_one_second_then_cut(comfy):
    b = SA3ComfyBackend(model="sm-sfx")
    res = b._generate([1], GenerationRequest(prompt="click", seconds=0.5))
    g = comfy.prompts["p0"]
    assert g["11"]["inputs"]["seconds"] == 1.0
    assert g["6"]["inputs"]["text"] == "click. Length: 1 seconds"
    assert res.audios[0].shape == (2, 22050)


def test_length_suffix_off(comfy, monkeypatch):
    monkeypatch.setenv("OTOMAKER_COMFY_LENGTH_SUFFIX", "0")
    b = SA3ComfyBackend()
    res = b._generate([1], GenerationRequest(prompt="calm piano.", seconds=3.0))
    assert comfy.prompts["p0"]["6"]["inputs"]["text"] == "calm piano."
    assert res.prompt_used == "calm piano."
    assert SA3ComfyBackend(length_suffix=True).length_suffix is True


def test_mono_and_other_rate(monkeypatch, capsys):
    monkeypatch.setattr(SA3ComfyBackend, "poll_interval", 0.01)
    fake = FakeComfy(sample_rate=48000, channels=1)
    try:
        b = SA3ComfyBackend(host=fake.host)
        res = b._generate([3], GenerationRequest(prompt="x", seconds=1.0))
    finally:
        fake.close()
    assert res.audios[0].shape == (2, 48000)
    out = capsys.readouterr()
    assert out.out == "" and "48000 Hz" in out.err


def test_generation_error(monkeypatch):
    monkeypatch.setattr(SA3ComfyBackend, "poll_interval", 0.01)
    fake = FakeComfy(fail=True)
    try:
        with pytest.raises(RuntimeError, match="generation failed.*boom"):
            SA3ComfyBackend(host=fake.host)._generate([1], GenerationRequest(prompt="x", seconds=1))
    finally:
        fake.close()


def test_edits_not_supported(comfy, tmp_path):
    b = SA3ComfyBackend()
    with pytest.raises(NotImplementedError, match="init_audio"):
        b._generate([1], GenerationRequest(prompt="x", seconds=2, init_audio="a.wav"))
    with pytest.raises(NotImplementedError, match="inpaint"):
        b._generate([1], GenerationRequest(prompt="x", seconds=2, inpaint_audio="a.wav",
                                           inpaint_range=(0, 1)))
    assert comfy.prompts == {}


def test_unreachable(capsys):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()   # nothing listens here now
    b = SA3ComfyBackend(host=f"127.0.0.1:{port}")
    with pytest.raises(RuntimeError, match="cannot reach ComfyUI"):
        b._generate([1], GenerationRequest(prompt="x", seconds=1))
    with pytest.raises(RuntimeError, match="cannot reach ComfyUI"):
        b._preload()
    assert capsys.readouterr().out == ""


def test_unreachable_is_its_own_type(monkeypatch):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    b = SA3ComfyBackend(host=f"127.0.0.1:{port}")
    with pytest.raises(ComfyUnreachable):
        b._generate([1], GenerationRequest(prompt="x", seconds=1))


def test_connection_lost_after_submit_is_plain_error(monkeypatch):
    # ComfyUI accepted the prompt, then stopped answering: an error, not a reason to fall back.
    b = SA3ComfyBackend(host="127.0.0.1:8188")

    def http(path, data=None):
        if path == "/prompt":
            return json.dumps({"prompt_id": "p1"}).encode()
        raise ComfyUnreachable("cannot reach ComfyUI at http://127.0.0.1:8188 (reset)")
    monkeypatch.setattr(b, "_http", http)
    with pytest.raises(RuntimeError, match="cannot reach ComfyUI") as ei:
        b._generate([1], GenerationRequest(prompt="x", seconds=1))
    assert type(ei.value) is RuntimeError


def test_unreachable_after_a_candidate_is_plain_error(monkeypatch):
    # The first candidate exists, so the rest must not be finished on another backend.
    b = SA3ComfyBackend(host="127.0.0.1:8188")
    calls = []

    def run_one(graph):
        calls.append(graph)
        if len(calls) == 2:
            raise ComfyUnreachable("cannot reach ComfyUI at http://127.0.0.1:8188 (refused)")
        return np.zeros((2, 44100), np.float32), 44100
    monkeypatch.setattr(b, "_run_one", run_one)
    with pytest.raises(RuntimeError, match="cannot reach ComfyUI") as ei:
        b._generate([1, 2], GenerationRequest(prompt="x", seconds=1))
    assert type(ei.value) is RuntimeError and len(calls) == 2


def _recording(monkeypatch, b):
    calls = []
    monkeypatch.setattr(b, "_http", lambda path, data=None: calls.append((path, data)) or b"{}")
    return calls


def test_unload_with_free_flag_calls_free(monkeypatch, capsys):
    monkeypatch.setenv("OTOMAKER_COMFY_FREE", "1")
    b = SA3ComfyBackend(host="127.0.0.1:8188")
    calls = _recording(monkeypatch, b)
    b._used, b._fresh = True, False
    assert b._unload() is True
    assert calls == [("/free", {"unload_models": True, "free_memory": True})]
    assert b.loaded() is False and b._fresh is True
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("flag", [None, "0", ""])
def test_unload_without_free_flag_does_not_call(monkeypatch, capsys, flag):
    if flag is None:
        monkeypatch.delenv("OTOMAKER_COMFY_FREE", raising=False)
    else:
        monkeypatch.setenv("OTOMAKER_COMFY_FREE", flag)
    b = SA3ComfyBackend(host="127.0.0.1:8188")
    calls = _recording(monkeypatch, b)
    b._used, b._fresh = True, False
    assert b._unload() is False
    assert calls == []
    assert b.loaded() is False and b._fresh is False
    out = capsys.readouterr()
    assert out.out == "" and "/free not called" in out.err


@pytest.mark.anyio
async def test_server_records_prompt_sent(comfy, tmp_path, monkeypatch):
    from mcp import Client
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path / "out")
    server.set_backend(SA3ComfyBackend(model="sm-sfx"))
    try:
        async with Client(server.server) as c:
            r = await c.call_tool("generate_audio", {"audio_type": "sfx", "prompt": "glass break",
                                                     "duration_seconds": 0.5, "seed": 4})
        assert not r.is_error, r.content
        out = json.loads("".join(getattr(x, "text", "") for x in r.content))
    finally:
        server.set_backend(None)
    sent = comfy.prompts["p0"]["6"]["inputs"]["text"]
    assert sent.endswith("Length: 1 seconds")
    assert out["prompt_used"] == sent and out["included_model_load"] is True
    meta = json.loads(Path(out["candidates"][0]["metadata"]).read_text(encoding="utf-8"))
    assert meta["prompt_used"] == sent and meta["backend"] == "sa3-comfy"
    assert sf.info(out["candidates"][0]["path"]).frames == 22050
