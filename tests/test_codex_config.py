"""codex_config: the installer's text edit of the Codex config.toml."""
import tomllib

import pytest

from otomaker import codex_config as cc

EXE = r"C:\Users\山田 太郎\OtoMaker\.venv\Scripts\otomaker-mcp.exe"
WANT = {"command": EXE, "args": [], "startup_timeout_sec": 60, "tool_timeout_sec": 300}

OTHER = """\
# my Codex settings
model = "gpt-5"   # keep this comment

[mcp_servers.other]
command = "other.exe"
args = ["--x"]

# profiles below
[profiles.fast]
model = "gpt-5-mini"
"""


def parse(p):
    raw = p.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # UTF-8 without BOM
    return tomllib.loads(raw.decode("utf-8"))


@pytest.fixture(autouse=True)
def _no_real_codex_home(monkeypatch, tmp_path):
    # Never let a test fall back to the real %USERPROFILE%\.codex.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home-from-env"))


def test_add_creates_missing_file(tmp_path):
    cfg = tmp_path / ".codex" / "config.toml"
    what, bak = cc.add(cfg, EXE)
    assert (what, bak) == ("added", None)
    assert parse(cfg) == {"mcp_servers": {"otomaker": WANT}}
    text = cfg.read_text(encoding="utf-8")
    assert "山田 太郎" in text and "\r\n" not in text
    assert text.startswith("[mcp_servers.otomaker]\n")


def test_add_keeps_other_tables_and_comments(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(OTHER, encoding="utf-8")
    what, bak = cc.add(cfg, EXE)
    assert what == "added"
    assert bak is not None and bak.read_text(encoding="utf-8") == OTHER
    text = cfg.read_text(encoding="utf-8")
    assert text.startswith(OTHER)  # appended at the end, everything before byte-identical
    data = parse(cfg)
    assert data["mcp_servers"]["otomaker"] == WANT
    assert data["mcp_servers"]["other"] == {"command": "other.exe", "args": ["--x"]}
    assert data["profiles"] == {"fast": {"model": "gpt-5-mini"}}


def test_add_again_is_unchanged_and_writes_nothing(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(OTHER, encoding="utf-8")
    cc.add(cfg, EXE)
    for b in tmp_path.glob("*.bak-*"):
        b.unlink()
    before = cfg.read_bytes()
    assert cc.add(cfg, EXE) == ("unchanged", None)
    assert cfg.read_bytes() == before
    assert list(tmp_path.glob("*.bak-*")) == []


def test_replace_existing_table_with_child_tables(tmp_path):
    cfg = tmp_path / "config.toml"
    orig = (
        'model = "gpt-5"\n'
        "\n"
        "[mcp_servers.otomaker]\n"
        "# old registration\n"
        'command = "D:\\\\Old\\\\otomaker-mcp.exe"\n'
        "tool_timeout_sec = 30\n"
        "\n"
        "[mcp_servers.otomaker.env]\n"
        'OTOMAKER_HOME = "D:\\\\Old\\\\data"\n'
        "\n"
        "# the other server\n"
        "[mcp_servers.other]\n"
        'command = "other.exe"\n'
        "\n"
        "[mcp_servers.'otomaker'.tools.generate_audio]\n"   # a child table further down, quoted key
        "enabled = true\n"
        "\n"
        "[tui]\n"
        "notifications = true\n"
    )
    cfg.write_text(orig, encoding="utf-8")
    what, bak = cc.add(cfg, EXE)
    assert what == "replaced" and bak is not None
    data = parse(cfg)
    assert data["mcp_servers"]["otomaker"] == WANT  # env and tools tables are gone
    assert data["mcp_servers"]["other"] == {"command": "other.exe"}
    assert data["tui"] == {"notifications": True}
    text = cfg.read_text(encoding="utf-8")
    assert "# the other server\n[mcp_servers.other]" in text
    assert "Old" not in text and "old registration" not in text
    assert text.count("[mcp_servers.otomaker]") == 1
    # the new table sits where the old one was
    assert text.index("[mcp_servers.otomaker]") < text.index("[mcp_servers.other]")


def test_crlf_and_bom_input(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_bytes(b"\xef\xbb\xbf" + OTHER.replace("\n", "\r\n").encode("utf-8"))
    assert cc.add(cfg, EXE)[0] == "added"
    raw = cfg.read_bytes()
    assert b"\n" not in raw.replace(b"\r\n", b"")  # every line ends in CRLF, like the original
    assert parse(cfg)["mcp_servers"]["otomaker"] == WANT


def test_path_with_quote_uses_basic_string(tmp_path):
    cfg = tmp_path / "config.toml"
    exe = r"C:\Users\O'Brien\OtoMaker\.venv\Scripts\otomaker-mcp.exe"
    cc.add(cfg, exe)
    assert parse(cfg)["mcp_servers"]["otomaker"]["command"] == exe


def test_env_table_is_written(tmp_path):
    cfg = tmp_path / "config.toml"
    cc.add(cfg, EXE, env={"OTOMAKER_HOME": r"D:\音\data"})
    assert parse(cfg)["mcp_servers"]["otomaker"]["env"] == {"OTOMAKER_HOME": r"D:\音\data"}
    assert "[mcp_servers.otomaker.env]" in cfg.read_text(encoding="utf-8")


def test_invalid_toml_is_left_alone(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('model = "gpt-5\n[broken\n', encoding="utf-8")
    before = cfg.read_bytes()
    with pytest.raises(cc.ConfigError):
        cc.add(cfg, EXE)
    assert cfg.read_bytes() == before
    assert list(tmp_path.glob("*.bak-*")) == []
    assert cc.main(["add", "--home", str(tmp_path), "--command", EXE]) == 3


def test_inline_definition_is_left_alone(tmp_path):
    # Not a [mcp_servers.otomaker] table: editing as text could break it, so refuse.
    cfg = tmp_path / "config.toml"
    orig = '[mcp_servers]\notomaker = { command = "x.exe" }\n'
    cfg.write_text(orig, encoding="utf-8")
    with pytest.raises(cc.ConfigError):
        cc.add(cfg, EXE)
    with pytest.raises(cc.ConfigError):
        cc.remove(cfg)
    assert cfg.read_text(encoding="utf-8") == orig


def test_header_inside_multiline_string_is_not_trusted(tmp_path):
    # A line that looks like our header but sits in a multi-line string must not be "replaced".
    cfg = tmp_path / "config.toml"
    orig = 'notes = """\n[mcp_servers.otomaker]\ncommand = "fake"\n"""\n'
    cfg.write_text(orig, encoding="utf-8")
    with pytest.raises(cc.ConfigError):
        cc.add(cfg, EXE)
    assert cfg.read_text(encoding="utf-8") == orig


def test_remove_keeps_everything_else(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(OTHER, encoding="utf-8")
    cc.add(cfg, EXE, env={"A": "1"})
    assert cc.remove(cfg, only_under=r"D:\Elsewhere") == ("elsewhere", None)
    assert "otomaker" in parse(cfg)["mcp_servers"]
    what, bak = cc.remove(cfg, only_under=r"C:\Users\山田 太郎\OtoMaker")
    assert what == "removed" and bak is not None
    assert cfg.read_text(encoding="utf-8") == OTHER  # back to the original text, comments included
    assert cc.remove(cfg) == ("absent", None)


def test_remove_table_in_the_middle(tmp_path):
    cfg = tmp_path / "config.toml"
    orig = ("a = 1\n\n[mcp_servers.otomaker]\ncommand = 'x.exe'\n\n[mcp_servers.otomaker.env]\nA = '1'\n\n"
            "# keep me\n[b]\nc = 2\n")
    cfg.write_text(orig, encoding="utf-8")
    assert cc.remove(cfg)[0] == "removed"
    assert cfg.read_text(encoding="utf-8") == "a = 1\n\n# keep me\n[b]\nc = 2\n"


def test_remove_missing_file(tmp_path):
    assert cc.remove(tmp_path / "config.toml") == ("absent", None)
    assert not (tmp_path / "config.toml").exists()


def test_codex_home_env_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "ch"))
    assert cc.config_path() == tmp_path / "ch" / "config.toml"
    assert cc.config_path(tmp_path / "given") == tmp_path / "given" / "config.toml"
    monkeypatch.delenv("CODEX_HOME")
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path / "user"))
    assert cc.config_path() == tmp_path / "user" / ".codex" / "config.toml"


def test_main_uses_codex_home(monkeypatch, tmp_path, capsys):
    home = tmp_path / "ch"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    assert cc.main(["detect"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == str(home / "config.toml")
    assert cc.main(["add", "--command", EXE]) == 0
    assert parse(home / "config.toml")["mcp_servers"]["otomaker"] == WANT
    capsys.readouterr()
    assert cc.main(["show"]) == 0
    assert EXE.replace("\\", "\\\\") in capsys.readouterr().out
    assert cc.main(["remove", "--only-under", r"D:\Elsewhere"]) == 1
    assert cc.main(["remove"]) == 0
    assert "otomaker" not in parse(home / "config.toml").get("mcp_servers", {})


def test_detect(tmp_path):
    none = lambda _name: None  # noqa: E731
    home = tmp_path / ".codex"
    assert cc.detect(home, which=none) is None
    assert cc.detect(home, which=lambda _n: r"C:\bin\codex.cmd").startswith("command:")
    home.mkdir()
    assert cc.detect(home, which=none).startswith("folder:")
    (home / "config.toml").write_text("", encoding="utf-8")
    assert cc.detect(home, which=none).startswith("config:")


def test_detect_without_codex_writes_nothing(monkeypatch, tmp_path):
    home = tmp_path / "nocodex"
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    assert cc.main(["detect", "--home", str(home)]) == 2
    assert not home.exists()
