"""Where the data folder is (otomaker.paths)."""
from pathlib import Path

from otomaker import paths


def test_checkout_uses_its_own_folder(monkeypatch):
    monkeypatch.delenv("OTOMAKER_HOME", raising=False)
    assert paths.is_checkout()   # the tests run from the repository
    assert paths.data_home() == paths.CHECKOUT_DIR
    assert paths.default_tflite_dir() == paths.CHECKOUT_DIR / "stable-audio-3" / "optimized" / "tflite"
    assert paths.default_output_dir() == paths.CHECKOUT_DIR / "outputs"


def test_installed_package_uses_localappdata(monkeypatch, tmp_path):
    # e.g. uvx: the code sits in uv's cache, so data must not go next to it.
    monkeypatch.delenv("OTOMAKER_HOME", raising=False)
    monkeypatch.setattr(paths, "CHECKOUT_DIR", tmp_path / "site-packages-ish")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "ローカル"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    home = paths.data_home()
    assert home in (tmp_path / "ローカル" / "OtoMaker", tmp_path / "xdg" / "otomaker")
    assert paths.default_tflite_dir() == home / "stable-audio-3" / "optimized" / "tflite"


def test_otomaker_home_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("OTOMAKER_HOME", str(tmp_path / "h"))
    assert paths.data_home() == (tmp_path / "h").resolve()
    assert paths.sa3_root() == (tmp_path / "h").resolve() / "stable-audio-3"


def test_is_checkout_needs_pyproject_and_src(tmp_path):
    assert not paths.is_checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    assert not paths.is_checkout(tmp_path)
    (tmp_path / "src" / "otomaker").mkdir(parents=True)
    assert paths.is_checkout(Path(tmp_path))
