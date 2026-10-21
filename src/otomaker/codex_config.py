"""Add or remove OtoMaker in the OpenAI Codex config (config.toml).

Used by installer\\install.ps1 and installer\\uninstall.ps1, which call it with
the OtoMaker virtual environment's Python:

    python -m otomaker.codex_config detect [--home DIR]
    python -m otomaker.codex_config add    --command EXE [--home DIR] [--name otomaker]
    python -m otomaker.codex_config remove [--only-under DIR] [--home DIR] [--name otomaker]
    python -m otomaker.codex_config show   [--home DIR] [--name otomaker]

The config file is <home>\\config.toml, where home is --home, else the
CODEX_HOME environment variable, else %USERPROFILE%\\.codex.

"detect" tells whether Codex is used on this PC: config.toml or the home folder
exists, or a codex command is on PATH. It prints the config path and exits 0,
or exits 2 when none of these is found (then nothing should be registered).

The file may hold other settings and comments, and tomllib can only read, so
the file is edited as text: only the [mcp_servers.<name>] table and its child
tables ([mcp_servers.<name>.env] and so on) are replaced, removed, or appended
at the end. Before anything is written, the new text is parsed with tomllib
and compared with the old one: everything outside mcp_servers.<name> must be
equal, and the entry must be exactly the intended one. Otherwise the file is
left untouched. An existing file is copied to <file>.bak-YYYYMMDD-HHMMSS
before it is changed, the file is written as UTF-8 without a BOM with the
original line endings (CRLF or LF) through a temporary file, and read back
once more; if that read fails the original bytes are put back.

Exit codes: 0 done (or nothing to do), 1 the entry points elsewhere and was
kept (remove --only-under), 2 Codex not found (detect), 3 the existing file
could not be read or safely edited.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable

from .mcp_config import _under, backup

NAME = "otomaker"
STARTUP_TIMEOUT_SEC = 60   # Codex default is 10; the first start loads Python and the backend
TOOL_TIMEOUT_SEC = 300     # Codex default is 60; one generation takes 30-60 s or more


class ConfigError(Exception):
    """The existing config.toml cannot be read or safely edited."""


def _toml():
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError as e:  # pragma: no cover - the installer uses Python 3.12
        raise ConfigError("Python 3.11 or later is needed to check config.toml; it was not changed") from e
    return tomllib


def codex_home(home: str | os.PathLike | None = None) -> Path:
    if home:
        return Path(home)
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env)
    return Path.home() / ".codex"


def config_path(home: str | os.PathLike | None = None) -> Path:
    return codex_home(home) / "config.toml"


def detect(home: str | os.PathLike | None = None,
           which: Callable[[str], str | None] | None = None) -> str | None:
    """Why we think Codex is used here, or None."""
    h = codex_home(home)
    if (h / "config.toml").exists():
        return f"config: {h / 'config.toml'}"
    if h.is_dir():
        return f"folder: {h}"
    exe = (which or shutil.which)("codex")
    if exe:
        return f"command: {exe}"
    return None


def entry_for(command: str, env: dict[str, str] | None = None) -> dict:
    e: dict = {"command": command, "args": [],
               "startup_timeout_sec": STARTUP_TIMEOUT_SEC, "tool_timeout_sec": TOOL_TIMEOUT_SEC}
    if env:
        e["env"] = dict(env)
    return e


# --- TOML text helpers -------------------------------------------------------

_BARE = re.compile(r"[A-Za-z0-9_-]+")


def _toml_str(s: str) -> str:
    if "'" not in s and not any(ord(c) < 0x20 or ord(c) == 0x7F for c in s):
        return "'" + s + "'"  # literal string: Windows paths stay readable
    out = []
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif c == '"':
            out.append('\\"')
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append(f"\\u{ord(c):04X}")
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


def _toml_key(k: str) -> str:
    return k if _BARE.fullmatch(k) else _toml_str(k)


def render(name: str, entry: dict, nl: str = "\n") -> list[str]:
    head = f"mcp_servers.{_toml_key(name)}"
    lines = [f"[{head}]"]
    for k, v in entry.items():
        if k == "env":
            continue
        if isinstance(v, str):
            val = _toml_str(v)
        elif isinstance(v, bool):
            val = "true" if v else "false"
        elif isinstance(v, int):
            val = str(v)
        elif isinstance(v, list):
            val = "[" + ", ".join(_toml_str(str(x)) for x in v) + "]"
        else:  # pragma: no cover - entry_for only makes the types above
            raise TypeError(k)
        lines.append(f"{_toml_key(k)} = {val}")
    if entry.get("env"):
        lines.append("")
        lines.append(f"[{head}.env]")
        for k, v in entry["env"].items():
            lines.append(f"{_toml_key(k)} = {_toml_str(v)}")
    return [ln + nl for ln in lines]


def _parse_key_path(s: str) -> list[str] | None:
    """'mcp_servers."otomaker".env' -> ['mcp_servers', 'otomaker', 'env']; None if not a key path."""
    keys: list[str] = []
    i, n = 0, len(s)
    while True:
        while i < n and s[i] in " \t":
            i += 1
        if i >= n:
            return None
        c = s[i]
        if c == '"':
            j, buf = i + 1, []
            while j < n and s[j] != '"':
                if s[j] == "\\" and j + 1 < n:
                    esc = s[j + 1]
                    if esc in "uU":
                        width = 4 if esc == "u" else 8
                        try:
                            buf.append(chr(int(s[j + 2:j + 2 + width], 16)))
                        except ValueError:
                            return None
                        j += 2 + width
                        continue
                    buf.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(esc, esc))
                    j += 2
                    continue
                buf.append(s[j])
                j += 1
            if j >= n:
                return None
            keys.append("".join(buf))
            i = j + 1
        elif c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                return None
            keys.append(s[i + 1:j])
            i = j + 1
        else:
            m = _BARE.match(s, i)
            if not m:
                return None
            keys.append(m.group())
            i = m.end()
        while i < n and s[i] in " \t":
            i += 1
        if i >= n:
            return keys
        if s[i] != ".":
            return None
        i += 1


_HEADER = re.compile(r"^[ \t]*(\[\[?)(.*?)(\]\]?)[ \t]*(#.*)?$")


def _header_keys(line: str) -> list[str] | None:
    m = _HEADER.match(line.rstrip("\r\n"))
    if not m or len(m.group(1)) != len(m.group(3)):
        return None
    return _parse_key_path(m.group(2))


def _is_ours(keys: list[str] | None, name: str) -> bool:
    return keys is not None and len(keys) >= 2 and keys[0] == "mcp_servers" and keys[1] == name


def _spans(lines: list[str], name: str) -> list[tuple[int, int]]:
    """[start, end) line ranges of our table and its child tables.

    Comments and blank lines at the end of a range are left out: they usually
    introduce the next table, so they are kept."""
    spans = []
    i, n = 0, len(lines)
    while i < n:
        if _is_ours(_header_keys(lines[i]), name):
            j = i + 1
            while j < n:
                k = _header_keys(lines[j])
                if k is not None and not _is_ours(k, name):
                    break
                j += 1
            end = j
            if j < n:  # trailing comments/blank lines belong to the next table
                while end > i + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
                    end -= 1
            spans.append((i, end))
            i = j
        else:
            i += 1
    return spans


# --- reading / checking / writing ---------------------------------------------

def _read(path: Path) -> tuple[bytes | None, str, str]:
    """(original bytes or None, text without BOM, newline)."""
    if not path.exists():
        return None, "", "\n"
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ConfigError(f"{path} is not UTF-8 ({e}); it was not changed") from e
    nl = "\r\n" if "\r\n" in text else "\n"
    return raw, text, nl


def _loads(text: str, path: Path) -> dict:
    try:
        return _toml().loads(text)
    except _toml().TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML ({e}); it was not changed") from e


def _without(data: dict, name: str) -> dict:
    d = copy.deepcopy(data)
    servers = d.get("mcp_servers")
    if isinstance(servers, dict):
        servers.pop(name, None)
        if not servers:
            d.pop("mcp_servers")
    return d


def _servers(data: dict, path: Path) -> dict:
    servers = data.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f"mcp_servers in {path} is not a table; it was not changed")
    return servers


def _check(old: dict, new_text: str, name: str, want: dict | None, path: Path) -> None:
    try:
        new = _toml().loads(new_text)
    except _toml().TOMLDecodeError as e:
        raise ConfigError(f"the edited {path} would not be valid TOML ({e}); it was not changed") from e
    if _without(new, name) != _without(old, name):
        raise ConfigError(f"editing {path} as text would change other settings; it was not changed")
    got = (new.get("mcp_servers") or {}).get(name)
    if got != want:
        raise ConfigError(f"[mcp_servers.{name}] in {path} could not be edited as text; it was not changed")


def _write(path: Path, text: str, original: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".otomaker-tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)
    try:
        _toml().loads(path.read_bytes().decode("utf-8"))
    except Exception as e:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
        raise ConfigError(f"{path} could not be read back after writing ({e}); the original was restored") from e


def _join_cut(lines: list[str], at: int) -> None:
    """After removing lines before index `at`, drop blank lines so no run of more than one remains."""
    while at < len(lines) and at > 0 and not lines[at].strip() and not lines[at - 1].strip():
        del lines[at]


def load(path: Path) -> dict:
    _, text, _ = _read(path)
    return _loads(text, path)


def show(path: Path, name: str = NAME) -> dict | None:
    return _servers(load(path), path).get(name)


def add(path: Path, command: str, name: str = NAME,
        env: dict[str, str] | None = None) -> tuple[str, Path | None]:
    """Register name -> command. Returns (what happened, backup path)."""
    raw, text, nl = _read(path)
    old = _loads(text, path)
    want = entry_for(command, env)
    before = _servers(old, path).get(name)
    if before == want:
        return "unchanged", None
    lines = text.splitlines(keepends=True)
    spans = _spans(lines, name)
    if before is not None and not spans:
        raise ConfigError(f"{name} in {path} is not written as a [mcp_servers.{name}] table; "
                          "it was not changed")
    block = render(name, want, nl)
    if spans:
        first = spans[0][0]
        for s, e in reversed(spans):
            del lines[s:e]
            if s != first:
                _join_cut(lines, s)
        if first < len(lines) and lines[first].strip():
            block = block + [nl]
        lines[first:first] = block
    else:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += nl
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append(nl)
        lines.extend(block)
    new_text = "".join(lines)
    _check(old, new_text, name, want, path)
    bak = backup(path)
    _write(path, new_text, raw)
    return ("replaced" if before is not None else "added"), bak


def remove(path: Path, name: str = NAME, only_under: str | None = None) -> tuple[str, Path | None]:
    """Drop the entry. With only_under, keep it if its command is outside that folder."""
    raw, text, _ = _read(path)
    old = _loads(text, path)
    entry = _servers(old, path).get(name)
    if entry is None:
        return "absent", None
    cmd = entry.get("command") if isinstance(entry, dict) else None
    if only_under and not (isinstance(cmd, str) and _under(cmd, only_under)):
        return "elsewhere", None
    lines = text.splitlines(keepends=True)
    spans = _spans(lines, name)
    if not spans:
        raise ConfigError(f"{name} in {path} is not written as a [mcp_servers.{name}] table; "
                          "remove it by hand")
    for s, e in reversed(spans):
        del lines[s:e]
        _join_cut(lines, s)
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    new_text = "".join(lines)
    _check(old, new_text, name, None, path)
    bak = backup(path)
    _write(path, new_text, raw)
    return "removed", bak


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m otomaker.codex_config",
                                 description="Add or remove OtoMaker in the OpenAI Codex config.toml.")
    ap.add_argument("action", choices=("detect", "add", "remove", "show"))
    ap.add_argument("--home", help="Codex home folder (default: CODEX_HOME, else %%USERPROFILE%%\\.codex)")
    ap.add_argument("--name", default=NAME)
    ap.add_argument("--command", help="otomaker-mcp.exe path (add)")
    ap.add_argument("--only-under", help="remove only if the command is inside this folder")
    args = ap.parse_args(argv)
    path = config_path(args.home)
    try:
        if args.action == "detect":
            why = detect(args.home)
            if not why:
                return 2
            print(path)
            print(why)
            return 0
        if args.action == "show":
            entry = show(path, args.name)
            if entry is not None:
                print(json.dumps(entry, ensure_ascii=False))
            return 0
        if args.action == "add":
            if not args.command:
                ap.error("add needs --command")
            what, bak = add(path, args.command, args.name)
        else:
            what, bak = remove(path, args.name, args.only_under)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    print(what)
    if bak:
        print(f"backup: {bak}")
    return 1 if what == "elsewhere" else 0


if __name__ == "__main__":
    sys.exit(main())
