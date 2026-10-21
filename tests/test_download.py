"""otomaker-download without the network: the Hub calls are replaced by fakes."""
import io
import os
from pathlib import Path

import pytest

from otomaker import download as dl


@pytest.fixture
def hub(monkeypatch, tmp_path):
    """Fake hf_hub_download (records calls, writes a small file) and no size lookups."""
    import huggingface_hub
    calls = []
    cache = tmp_path / "hf-cache"

    def fake(repo_id, filename, local_dir=None, **kw):
        calls.append((repo_id, filename, local_dir))
        p = Path(local_dir) / filename if local_dir else cache / repo_id.replace("/", "--") / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"weights")
        return str(p)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake)
    monkeypatch.setattr(dl, "remote_sizes", lambda items: {(i.repo, i.filename): 10 for i in items})
    return calls


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    d = tmp_path / "tflite"
    (d / "scripts").mkdir(parents=True)
    (d / "scripts" / "sa3_gradio.py").write_text("")
    monkeypatch.setenv("OTOMAKER_SA3_TFLITE_DIR", str(d))
    return d


def test_tflite_items_match_upstream_layout(tmp_path):
    items = dl.tflite_items(["sm-sfx", "sm-music"], tmp_path)
    names = [i.filename for i in items]
    assert names == ["tflite/sa3-sm-sfx/dit_w8a8.tflite", "tflite/same-s/enc_w8a8.tflite",
                     "tflite/same-s/dec_w8a8.tflite", "tflite/sa3-sm-music/dit_w8a8.tflite",
                     "tflite/t5gemma/encoder_fp16.tflite"]   # shared files only once
    assert all(i.repo == "stabilityai/stable-audio-3-optimized" for i in items)
    assert items[0].target == tmp_path / "models" / "tflite" / "sa3-sm-sfx" / "dit_w8a8.tflite"
    medium = dl.tflite_items(["medium"], tmp_path, "fp32")[0]
    assert medium.filename == "tflite/sa3-m/dit_fp32.tflite"


def test_comfy_items_use_the_backend_file_names(tmp_path):
    items = dl.comfy_items(["medium"], tmp_path)
    assert [i.filename for i in items] == ["checkpoints/stable_audio_3_medium.safetensors",
                                           "text_encoders/t5gemma_b_b_ul2.safetensors"]
    assert all(i.repo == "Comfy-Org/stable-audio-3" for i in items)
    assert items[1].target == tmp_path / "text_encoders" / "t5gemma_b_b_ul2.safetensors"


def test_dry_run_downloads_nothing_and_shows_licences(hub, runtime, capsys):
    assert dl.main(["sfx", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert hub == []
    assert "https://stability.ai/community-license-agreement" in out
    assert "https://ai.google.dev/gemma/terms" in out
    assert "US$1M" in out and "Powered by Stability AI" in out
    assert "get   tflite/sa3-sm-sfx/dit_w8a8.tflite" in out
    assert not (runtime / "models").exists()


@pytest.mark.parametrize("answer", ["\n", "n\n", ""])
def test_no_consent_downloads_nothing(hub, runtime, answer, capsys):
    assert dl.main(["music"], stdin=io.StringIO(answer)) == 1
    assert hub == [] and "Not agreed" in capsys.readouterr().out


def test_consent_downloads_and_links_into_the_runtime(hub, runtime):
    assert dl.main(["music"], stdin=io.StringIO("y\n")) == 0
    assert [c[1] for c in hub] == ["tflite/sa3-sm-music/dit_w8a8.tflite", "tflite/same-s/enc_w8a8.tflite",
                                   "tflite/same-s/dec_w8a8.tflite", "tflite/t5gemma/encoder_fp16.tflite"]
    assert all(c[2] is None for c in hub)   # into the HF cache, then linked like upstream
    dit = runtime / "models" / "tflite" / "sa3-sm-music" / "dit_w8a8.tflite"
    assert dit.read_bytes() == b"weights"


def test_yes_skips_the_question_and_present_files_are_skipped(hub, runtime, capsys):
    t5 = runtime / "models" / "tflite" / "t5gemma" / "encoder_fp16.tflite"
    t5.parent.mkdir(parents=True)
    t5.write_bytes(b"old")
    assert dl.main(["sfx", "--yes"], stdin=io.StringIO("")) == 0
    assert "tflite/t5gemma/encoder_fp16.tflite" not in [c[1] for c in hub]
    assert t5.read_bytes() == b"old"
    assert "have  tflite/t5gemma/encoder_fp16.tflite" in capsys.readouterr().out
    hub.clear()
    assert dl.main(["sfx", "--yes"]) == 0 and hub == []   # everything in place now


def test_missing_runtime_is_an_error_unless_dry_run(hub, tmp_path, monkeypatch):
    monkeypatch.setenv("OTOMAKER_SA3_TFLITE_DIR", str(tmp_path / "nowhere"))
    assert dl.main(["sfx", "--yes"]) == 2 and hub == []
    assert dl.main(["sfx", "--dry-run"]) == 0


def test_comfy_writes_into_the_models_folder(hub, tmp_path):
    models = tmp_path / "ComfyUI" / "models"
    assert dl.main(["sfx", "--comfy", "--comfy-dir", str(models), "--yes"]) == 0
    assert hub == [("Comfy-Org/stable-audio-3", "checkpoints/stable_audio_3_small_sfx.safetensors", str(models)),
                   ("Comfy-Org/stable-audio-3", "text_encoders/t5gemma_b_b_ul2.safetensors", str(models))]
    assert (models / "checkpoints" / "stable_audio_3_small_sfx.safetensors").is_file()


def test_comfy_needs_a_folder(hub):
    with pytest.raises(SystemExit):
        dl.main(["sfx", "--comfy", "--yes"])
    assert hub == []


def test_all_means_every_model(hub, runtime, capsys):
    dl.main(["all", "--dry-run"])
    out = capsys.readouterr().out
    for sub in ("sa3-sm-sfx", "sa3-sm-music", "sa3-m"):
        assert f"tflite/{sub}/dit_w8a8.tflite" in out


# ── consent without a terminal (an AI assistant running the command) ─────────
def test_without_a_terminal_nothing_is_downloaded_until_accepted(hub, runtime, capsys):
    assert dl.main(["--models", "sfx,music"], interactive=False) == 4
    out = capsys.readouterr().out
    assert hub == [] and not (runtime / "models").exists()
    assert "--accept-licenses" in out and "https://stability.ai/community-license-agreement" in out
    assert dl.main(["--models", "sfx,music", "--accept-licenses"], interactive=False) == 0
    assert "tflite/sa3-sm-music/dit_w8a8.tflite" in [c[1] for c in hub]


def test_models_option_and_positional_names_combine(hub, runtime, capsys):
    assert dl.main(["sfx", "--models", "music", "--models", "medium", "--dry-run"]) == 0
    out = capsys.readouterr().out
    for sub in ("sa3-sm-sfx", "sa3-sm-music", "sa3-m"):
        assert f"tflite/{sub}/dit_w8a8.tflite" in out
    with pytest.raises(SystemExit):
        dl.main(["--models", "large"])
    with pytest.raises(SystemExit):   # nothing named
        dl.main([])


# ── the runtime ──────────────────────────────────────────────────────────────
def make_archive(path, commit, extra=None):
    import zipfile
    pre = f"stable-audio-3-{commit}/"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(pre + "optimized/tflite/scripts/sa3_gradio.py", "# upstream")
        z.writestr(pre + "optimized/tflite/models/tokenizer.model", "tok")
        z.writestr(pre + "LICENSE", "MIT")
        z.writestr(pre + "README.md", "readme")
        z.writestr(pre + "training/big.bin", "not needed")
        for name, data in (extra or {}).items():
            z.writestr(pre + name, data)
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def github(monkeypatch, tmp_path):
    """Fake GitHub: dl._download copies a local archive; returns a setter for it."""
    import hashlib
    state = {"archive": None, "urls": []}

    def fake_download(url, dest):
        state["urls"].append(url)
        data = state["archive"].read_bytes()
        Path(dest).write_bytes(data)
        return hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(dl, "_download", fake_download)
    return state


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A data folder with no runtime yet, with a Japanese name like a Japanese user name."""
    h = tmp_path / "ユーザー" / "OtoMaker"
    tflite = h / "stable-audio-3" / "optimized" / "tflite"
    monkeypatch.delenv("OTOMAKER_SA3_TFLITE_DIR", raising=False)
    monkeypatch.setattr(dl.sa3_tflite, "DEFAULT_TFLITE_DIR", tflite)
    return h


def test_runtime_is_fetched_verified_and_trimmed(hub, github, home, tmp_path, monkeypatch, capsys):
    sha = make_archive(tmp_path / "a.zip", dl.SA3_COMMIT)
    github["archive"] = tmp_path / "a.zip"
    monkeypatch.setattr(dl, "SA3_ARCHIVE_SHA256", sha)
    monkeypatch.setattr(dl.fetch_runtime, "__defaults__", (dl.SA3_URL, sha, dl.SA3_COMMIT))
    assert dl.main(["sfx", "--accept-licenses"], interactive=False) == 0
    root = home / "stable-audio-3"
    assert github["urls"] == [dl.SA3_URL]
    assert (root / "optimized" / "tflite" / "scripts" / "sa3_gradio.py").read_text() == "# upstream"
    assert (root / "LICENSE").is_file() and not (root / "training").exists()
    assert dl.SA3_COMMIT in (root / "OTOMAKER_RUNTIME.txt").read_text()
    assert (root / "optimized" / "tflite" / "models" / "tflite" / "sa3-sm-sfx" / "dit_w8a8.tflite").is_file()
    assert sorted(p.name for p in home.iterdir()) == ["stable-audio-3"]   # no .part / .partial left
    github["urls"].clear()
    assert dl.main(["sfx"], interactive=False) == 0 and github["urls"] == []   # in place now


def test_runtime_only_needs_no_consent(hub, github, home, tmp_path, monkeypatch):
    sha = make_archive(tmp_path / "a.zip", dl.SA3_COMMIT)
    github["archive"] = tmp_path / "a.zip"
    monkeypatch.setattr(dl.fetch_runtime, "__defaults__", (dl.SA3_URL, sha, dl.SA3_COMMIT))
    assert dl.main(["--runtime-only"], interactive=False) == 0
    assert hub == [] and dl.runtime_present(home / "stable-audio-3" / "optimized" / "tflite")


def test_runtime_with_a_wrong_hash_leaves_nothing(hub, github, home, tmp_path, capsys):
    make_archive(tmp_path / "a.zip", dl.SA3_COMMIT)
    github["archive"] = tmp_path / "a.zip"   # the real SHA256 constant will not match
    assert dl.main(["sfx", "--accept-licenses"], interactive=False) == 2
    assert "SHA256 mismatch" in capsys.readouterr().err
    assert hub == [] and list(home.iterdir()) == []


def test_runtime_is_not_fetched_without_consent(hub, github, home):
    assert dl.main(["sfx"], interactive=False) == 4
    assert github["urls"] == [] and not home.exists()


def test_runtime_archive_paths_are_checked(github, tmp_path):
    sha = make_archive(tmp_path / "a.zip", dl.SA3_COMMIT, {"optimized/tflite/../../evil.txt": "x"})
    github["archive"] = tmp_path / "a.zip"
    with pytest.raises(RuntimeError, match="unexpected path"):
        dl.fetch_runtime(tmp_path / "out" / "stable-audio-3", sha256=sha)
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "out" / "stable-audio-3").exists()


def test_an_unrelated_folder_in_the_way_is_not_overwritten(github, tmp_path):
    root = tmp_path / "stable-audio-3"
    root.mkdir()
    with pytest.raises(RuntimeError, match="Rename or delete"):
        dl.fetch_runtime(root)
    assert github["urls"] == []


def test_runtime_pin_matches_the_installer():
    ps1 = (Path(__file__).parents[1] / "installer" / "install.ps1").read_text(encoding="utf-8-sig")
    assert f'$Sa3Commit = "{dl.SA3_COMMIT}"' in ps1
    assert f'$Sa3ArchiveSha256 = "{dl.SA3_ARCHIVE_SHA256}"' in ps1


def test_nul_stdin_is_not_a_person(tmp_path):
    # `< NUL` passes isatty() on Windows; it must still count as "no terminal".
    import subprocess
    import sys
    code = "from otomaker.download import _stdin_is_interactive as f; print(f())"
    with open(os.devnull, "rb") as nul:
        out = subprocess.run([sys.executable, "-c", code], stdin=nul, capture_output=True, text=True)
    assert out.stdout.strip() == "False", out.stderr
    out = subprocess.run([sys.executable, "-c", code], input="", capture_output=True, text=True)
    assert out.stdout.strip() == "False", out.stderr
