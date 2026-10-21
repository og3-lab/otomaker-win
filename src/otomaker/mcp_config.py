"""Add or remove OtoMaker in an MCP client's JSON config (Claude Desktop style).

Used by installer\\install.ps1 and installer\\uninstall.ps1, which call it with
the OtoMaker virtual environment's Python:

    python -m otomaker.mcp_config add    --config FILE --command EXE [--name otomaker]
    python -m otomaker.mcp_config remove --config FILE [--only-under DIR] [--name otomaker]
    python -m otomaker.mcp_config show   --config FILE [--name otomaker]

Only the "mcpServers" entry with that name is touched; every other key and
server is kept as it was (key order included). An existing file is copied to
<file>.bak-YYYYMMDD-HHMMSS before it is changed. The file is written as UTF-8
without a BOM (an existing BOM is accepted on reading) through a temporary
file, so a failure never leaves a half-written config. A file that is not
valid JSON (for example one with comments) is left untouched.

Exit codes: 0 done (or nothing to do), 1 the entry points elsewhere and was
kept (remove --only-under), 3 the existing file could not be read as JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

NAME = "otomaker"


class ConfigError(Exception):
    """The existing config file is not a JSON object we can safely edit."""


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON ({e}); it was not changed") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not hold a JSON object; it was not changed")
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise ConfigError(f'"mcpServers" in {path} is not an object; it was not changed')
    return data


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"{path.name}.bak-{stamp}")
    n = 1
    while dest.exists():
        dest = path.with_name(f"{path.name}.bak-{stamp}-{n}")
        n += 1
    shutil.copy2(path, dest)
    return dest


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".otomaker-tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def entry_for(command: str) -> dict:
    return {"command": command, "args": []}


def add(path: Path, command: str, name: str = NAME) -> tuple[str, Path | None]:
    """Register name → command. Returns (what happened, backup path)."""
    data = load(path)
    servers = data.setdefault("mcpServers", {})
    new = entry_for(command)
    old = servers.get(name)
    if old == new:
        return "unchanged", None
    bak = backup(path)
    servers[name] = new
    save(path, data)
    return ("replaced" if old is not None else "added"), bak


def _under(command: str, folder: str) -> bool:
    try:
        c = os.path.normcase(os.path.abspath(command))
        d = os.path.normcase(os.path.abspath(folder))
    except (TypeError, ValueError):
        return False
    return c == d or c.startswith(d.rstrip("\\/") + os.sep)


def remove(path: Path, name: str = NAME, only_under: str | None = None) -> tuple[str, Path | None]:
    """Drop the entry. With only_under, keep it if its command is outside that folder."""
    data = load(path)
    servers = data.get("mcpServers") or {}
    if name not in servers:
        return "absent", None
    cmd = servers[name].get("command") if isinstance(servers[name], dict) else None
    if only_under and not (isinstance(cmd, str) and _under(cmd, only_under)):
        return "elsewhere", None
    bak = backup(path)
    del servers[name]
    save(path, data)
    return "removed", bak


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m otomaker.mcp_config",
                                 description="Add or remove OtoMaker in an MCP client JSON config.")
    ap.add_argument("action", choices=("add", "remove", "show"))
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--name", default=NAME)
    ap.add_argument("--command", help="otomaker-mcp.exe path (add)")
    ap.add_argument("--only-under", help="remove only if the command is inside this folder")
    args = ap.parse_args(argv)
    try:
        if args.action == "show":
            servers = load(args.config).get("mcpServers") or {}
            if args.name in servers:
                print(json.dumps(servers[args.name], ensure_ascii=False))
            return 0
        if args.action == "add":
            if not args.command:
                ap.error("add needs --command")
            what, bak = add(args.config, args.command, args.name)
        else:
            what, bak = remove(args.config, args.name, args.only_under)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    print(what)
    if bak:
        print(f"backup: {bak}")
    return 1 if what == "elsewhere" else 0


if __name__ == "__main__":
    sys.exit(main())
