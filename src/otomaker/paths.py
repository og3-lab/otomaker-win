"""Where OtoMaker keeps its runtime, models links and outputs.

The data folder is, in order:
  1. OTOMAKER_HOME, if set;
  2. the OtoMaker folder itself when running from it (the install.cmd / zip
     layout and `uv sync` checkouts: pyproject.toml next to src\\otomaker);
  3. %LOCALAPPDATA%\\OtoMaker otherwise (an installed package, for example
     `uvx --from git+https://… otomaker-mcp`, whose code sits in uv's cache).

A folder name with non-ASCII characters (a Japanese user name, for instance)
is fine: the sa3-tflite backend hands LiteRT ASCII paths itself.
"""
from __future__ import annotations

import os
from pathlib import Path

# src/otomaker/paths.py -> the folder that holds pyproject.toml in a checkout
CHECKOUT_DIR = Path(__file__).resolve().parents[2]


def is_checkout(folder: Path | None = None) -> bool:
    folder = CHECKOUT_DIR if folder is None else folder
    return (folder / "pyproject.toml").is_file() and (folder / "src" / "otomaker").is_dir()


def user_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "OtoMaker"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "otomaker"


def data_home() -> Path:
    env = os.environ.get("OTOMAKER_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if is_checkout():
        return CHECKOUT_DIR
    return user_data_dir()


def sa3_root(home: Path | None = None) -> Path:
    """The stable-audio-3 folder (holds optimized\\tflite)."""
    return (home or data_home()) / "stable-audio-3"


def default_tflite_dir(home: Path | None = None) -> Path:
    return sa3_root(home) / "optimized" / "tflite"


def default_output_dir(home: Path | None = None) -> Path:
    return (home or data_home()) / "outputs"
