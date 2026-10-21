"""mcp_config: the installer's edit of an MCP client JSON config."""
import json

import pytest

from otomaker import mcp_config as mc

EXE = r"C:\Users\山田 太郎\OtoMaker\.venv\Scripts\otomaker-mcp.exe"


def read(p):
    raw = p.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # UTF-8 without BOM
    return json.loads(raw.decode("utf-8"))


def test_add_creates_missing_file(tmp_path):
    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    what, bak = mc.add(cfg, EXE)
    assert (what, bak) == ("added", None)
    assert read(cfg) == {"mcpServers": {"otomaker": {"command": EXE, "args": []}}}
    assert "山田 太郎" in cfg.read_text(encoding="utf-8")  # not \u-escaped


def test_add_keeps_everything_else_and_backs_up(tmp_path):
    cfg = tmp_path / "c.json"
    orig = {"globalShortcut": "Ctrl+Space", "mcpServers": {"other": {"command": "x.exe", "env": {"A": "1"}}},
            "zLast": [1, 2]}
    cfg.write_bytes(b"\xef\xbb\xbf" + json.dumps(orig).encode("utf-8"))  # BOM accepted on input
    what, bak = mc.add(cfg, EXE)
    assert what == "added"
    assert bak is not None and bak.read_bytes().startswith(b"\xef\xbb\xbf")
    data = read(cfg)
    assert list(data) == ["globalShortcut", "mcpServers", "zLast"]
    assert data["mcpServers"]["other"] == orig["mcpServers"]["other"]
    assert data["mcpServers"]["otomaker"]["command"] == EXE


def test_add_again_is_unchanged_and_writes_nothing(tmp_path):
    cfg = tmp_path / "c.json"
    mc.add(cfg, EXE)
    before = cfg.read_bytes()
    assert mc.add(cfg, EXE) == ("unchanged", None)
    assert cfg.read_bytes() == before
    assert list(tmp_path.glob("*.bak-*")) == []


def test_invalid_json_is_left_alone(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text('{ // comment\n "mcpServers": {} }', encoding="utf-8")
    with pytest.raises(mc.ConfigError):
        mc.add(cfg, EXE)
    assert cfg.read_text(encoding="utf-8").startswith("{ // comment")
    assert mc.main(["add", "--config", str(cfg), "--command", EXE]) == 3


def test_remove_only_under_folder(tmp_path):
    cfg = tmp_path / "c.json"
    mc.add(cfg, EXE)
    assert mc.remove(cfg, only_under=r"D:\Elsewhere") == ("elsewhere", None)
    assert "otomaker" in read(cfg)["mcpServers"]
    what, bak = mc.remove(cfg, only_under=r"C:\Users\山田 太郎\OtoMaker")
    assert what == "removed" and bak is not None
    assert read(cfg) == {"mcpServers": {}}
    assert mc.remove(cfg) == ("absent", None)


def test_remove_missing_file(tmp_path):
    assert mc.remove(tmp_path / "none.json") == ("absent", None)
    assert not (tmp_path / "none.json").exists()
