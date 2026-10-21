"""Download what OtoMaker needs before the first run: the Stable Audio 3 runtime
and the model files.

    otomaker-download sfx music              # CPU (sa3-tflite): runtime + small SFX + small music
    otomaker-download --models sfx,music --accept-licenses   # the same, without asking (see below)
    otomaker-download --runtime-only         # only the runtime (no model, no licence question)
    otomaker-download medium --dry-run       # show what would be fetched, fetch nothing
    otomaker-download sfx --comfy --comfy-dir D:\\ComfyUI\\models   # GPU (sa3-comfy)

Models: sfx (sm-sfx), music (sm-music), medium, all. The text encoder
(T5Gemma) is shared by all of them and is added once. Both Hugging Face
repositories are public (not gated): no account or token is needed.

Runtime (CPU only): when <tflite dir>\\scripts\\sa3_gradio.py is missing, the
Stability-AI/stable-audio-3 archive of the verified commit is downloaded from
GitHub, checked against its SHA256 and only optimized\\tflite, LICENSE and
README.md are extracted into <data folder>\\stable-audio-3 (MIT; the same
commit and hash as installer\\install.ps1). The data folder is described in
otomaker.paths; --tflite-dir or OTOMAKER_SA3_TFLITE_DIR choose another place.

CPU models come from stabilityai/stable-audio-3-optimized and are placed the
way upstream weights.ensure_local places them (stable-audio-3 commit
77e0398): downloaded into the Hugging Face cache (HF_HOME) and exposed under
<tflite dir>\\models\\tflite\\… as a symlink, else a hardlink, else a copy.

GPU (--comfy): checkpoints and the text encoder come from
Comfy-Org/stable-audio-3 and are written straight into --comfy-dir as
checkpoints\\<file> and text_encoders\\<file>, the layout of ComfyUI's models
folder (or of a folder listed in ComfyUI's extra_model_paths.yaml).

Licences: before any model file is downloaded the terms are shown. In a
terminal you are asked to agree (y/N). --accept-licenses records that the
user has read and agreed to them; only pass it on the user's explicit
instruction (an AI assistant must show the terms and wait for the user's
answer first). Without it and without an interactive terminal, nothing at
all is downloaded and the command stops with exit code 4.

Exit codes: 0 done (or nothing to do), 1 the user did not agree,
2 error, 4 consent needed but no terminal to ask in (rerun with
--accept-licenses once the user has agreed).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .backends import sa3_comfy, sa3_tflite

TFLITE_REPO = "stabilityai/stable-audio-3-optimized"
COMFY_REPO = "Comfy-Org/stable-audio-3"

# The runtime archive. Keep equal to $Sa3Commit / $Sa3ArchiveSha256 in
# installer\install.ps1 (tests/test_download.py checks this).
SA3_COMMIT = "77e0398c26f7d22d801ec1bb036307e8b231f741"
SA3_ARCHIVE_SHA256 = "04e85c047a1f85c3f66976768b1dd02e0774823944c6f1b2229c29e95cba71fe"
SA3_URL = f"https://github.com/Stability-AI/stable-audio-3/archive/{SA3_COMMIT}.zip"

LICENSES = (
    ("Stable Audio 3 model weights: Stability AI Community License",
     "https://stability.ai/community-license-agreement",
     "Free for research, non-commercial use and for organisations or individuals "
     "with less than US$1M in annual revenue; above that an Enterprise License "
     "from Stability AI is required."),
    ("T5Gemma text encoder: Gemma Terms of Use",
     "https://ai.google.dev/gemma/terms",
     "Includes the Gemma Prohibited Use Policy."),
)

# Our CLI name → backend model name.
ALIASES = {"sfx": "sm-sfx", "music": "sm-music", "medium": "medium",
           "sm-sfx": "sm-sfx", "sm-music": "sm-music"}
ALL_MODELS = ["sm-sfx", "sm-music", "medium"]

DIT_SUBDIR = sa3_tflite.DIT_SUBDIR
PRECISIONS = ("w8a8", "fp32")
DECODERS = ("same-s", "same-l")


@dataclass(frozen=True)
class Item:
    repo: str
    filename: str   # path inside the Hugging Face repository
    target: Path    # where the file ends up on this PC


def tflite_items(models: list[str], tflite_dir: Path, precision: str = "w8a8",
                 decoder: str = "same-s") -> list[Item]:
    """DiT + SAME codec (encoder for edit_audio, decoder) per model, then the
    shared T5Gemma. Local paths mirror upstream: models/tflite/<same as repo>."""
    if not models:
        return []
    rels: list[str] = []
    for m in models:
        rels += [r for r in sa3_tflite.model_files(m, precision, decoder)
                 if not r.startswith("tflite/t5gemma/")]
    rels.append("tflite/t5gemma/encoder_fp16.tflite")
    rels = list(dict.fromkeys(rels))
    return [Item(TFLITE_REPO, r, tflite_dir / "models" / Path(r)) for r in rels]


def comfy_items(models: list[str], comfy_dir: Path) -> list[Item]:
    rels = [f"checkpoints/{sa3_comfy.MODELS[m][0]}" for m in models]
    rels.append(f"text_encoders/{sa3_comfy.CLIP}")
    rels = list(dict.fromkeys(rels))
    return [Item(COMFY_REPO, r, comfy_dir / Path(r)) for r in rels]


def present(item: Item) -> bool:
    return item.target.exists() or item.target.is_symlink()


def remote_sizes(items: list[Item]) -> dict[tuple[str, str], int]:
    """File sizes from the Hub (one small request per repo); {} if offline."""
    sizes: dict[tuple[str, str], int] = {}
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        for repo in dict.fromkeys(i.repo for i in items):
            for f in api.get_paths_info(repo, [i.filename for i in items if i.repo == repo]):
                if getattr(f, "size", None) is not None:
                    sizes[(repo, f.path)] = int(f.size)
    except Exception as e:  # sizes are informational only
        print(f"(could not read file sizes from Hugging Face: {e})", file=sys.stderr)
    return sizes


def _gb(n: int) -> str:
    return f"{n / 1e9:.2f} GB"


def link_or_copy(cached: Path, target: Path) -> str:
    """Expose a cached file at target like upstream weights._link_or_copy:
    symlink (needs Developer Mode on Windows) → hardlink (same drive) → copy."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        target.unlink()
    try:
        target.symlink_to(cached)
        return "symlink"
    except OSError:
        pass
    try:
        os.link(cached, target)
        return "hardlink"
    except OSError:
        shutil.copy2(cached, target)
        return "copy"


def fetch(item: Item, comfy: bool) -> str:
    from huggingface_hub import hf_hub_download
    if comfy:
        # The models folder layout equals the repo layout, so write there directly.
        root = item.target.parents[len(Path(item.filename).parts) - 1]
        hf_hub_download(repo_id=item.repo, filename=item.filename, local_dir=str(root))
        return "downloaded"
    cached = Path(hf_hub_download(repo_id=item.repo, filename=item.filename))
    return link_or_copy(cached, item.target)


# ── runtime ──────────────────────────────────────────────────────────────────
def runtime_present(tflite_dir: Path) -> bool:
    return (tflite_dir / "scripts" / "sa3_gradio.py").is_file()


def runtime_root(tflite_dir: Path) -> Path | None:
    """The stable-audio-3 folder that holds tflite_dir as optimized\\tflite, or
    None if tflite_dir is not laid out that way (then it cannot be fetched)."""
    if tflite_dir.name == "tflite" and tflite_dir.parent.name == "optimized":
        return tflite_dir.parent.parent
    return None


def _download(url: str, dest: Path) -> str:
    """Stream url to dest; return the SHA256 (hex) of what was written."""
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "otomaker-download"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            h.update(chunk)
            f.write(chunk)
    return h.hexdigest()


def fetch_runtime(root: Path, url: str = SA3_URL, sha256: str = SA3_ARCHIVE_SHA256,
                  commit: str = SA3_COMMIT) -> int:
    """Download and verify the stable-audio-3 archive, extract optimized/tflite,
    LICENSE and README.md into root (the stable-audio-3 folder). Returns the
    number of files. Nothing is left behind on failure."""
    if root.exists():
        raise RuntimeError(f"{root} exists but has no optimized\\tflite\\scripts\\sa3_gradio.py. "
                           "Rename or delete it, then run otomaker-download again.")
    root.parent.mkdir(parents=True, exist_ok=True)
    part = root.parent / f"stable-audio-3-{commit[:7]}.zip.part"
    tmp = root.parent / "stable-audio-3.partial"
    for p in (part, tmp):
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    try:
        print(f"  downloading the runtime: {url}", flush=True)
        got = _download(url, part)
        if got.lower() != sha256.lower():
            raise RuntimeError(f"SHA256 mismatch for {url} (tampered or changed at the source): "
                               f"expected {sha256}, got {got}")
        print(f"    SHA256 verified ({got})")
        prefix = f"stable-audio-3-{commit}/"
        count = 0
        with zipfile.ZipFile(part) as z:
            for info in z.infolist():
                if not info.filename.startswith(prefix) or info.is_dir():
                    continue
                rel = PurePosixPath(info.filename[len(prefix):])
                if not (str(rel).startswith("optimized/tflite/") or str(rel) in ("LICENSE", "README.md")):
                    continue
                if rel.is_absolute() or ".." in rel.parts or ":" in str(rel):
                    raise RuntimeError(f"unexpected path in the runtime archive: {info.filename}")
                dest = tmp.joinpath(*rel.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                count += 1
        (tmp / "optimized" / "tflite" / "models" / "tflite").mkdir(parents=True, exist_ok=True)
        (tmp / "OTOMAKER_RUNTIME.txt").write_text(
            f"Stability-AI/stable-audio-3 commit {commit} (MIT)\n"
            f"Extracted by otomaker-download from {url} (optimized/tflite, LICENSE, README.md only)\n",
            encoding="ascii")
        if not runtime_present(tmp / "optimized" / "tflite"):
            raise RuntimeError("the runtime archive has no optimized/tflite/scripts/sa3_gradio.py")
        tmp.rename(root)
        return count
    finally:
        if part.exists():
            part.unlink()
        if tmp.is_dir():
            shutil.rmtree(tmp, ignore_errors=True)


# ── consent ──────────────────────────────────────────────────────────────────
def ask_consent(stdin=None) -> bool:
    stdin = stdin or sys.stdin
    print("Agree to these terms and download? [y/N] ", end="", flush=True)
    try:
        answer = stdin.readline()
    except (EOFError, OSError):
        answer = ""
    return answer.strip().lower() in ("y", "yes")


def _stdin_is_interactive() -> bool:
    """A person can answer on stdin. On Windows isatty() is also true for NUL
    (`< NUL`, `< /dev/null`), which is how tools such as AI assistants often
    run commands, so a real console is required there (GetConsoleMode)."""
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
        if os.name != "nt":
            return True
        import ctypes
        import msvcrt
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        mode = ctypes.c_uint32()
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except (AttributeError, ValueError, OSError):
        return False


def print_licenses() -> None:
    print("The model files are not part of OtoMaker. By downloading them you accept:")
    for title, url, note in LICENSES:
        print(f"  - {title}\n    {url}\n    {note}")
    print("  Attribution: This Stability AI Model is licensed under the Stability AI "
          "Community License, Copyright (c) Stability AI Ltd. All Rights Reserved. "
          "Powered by Stability AI.")


def _model_list(value: str) -> list[str]:
    names = [v.strip() for v in value.split(",") if v.strip()]
    bad = [n for n in names if n not in ALIASES and n != "all"]
    if bad or not names:
        raise argparse.ArgumentTypeError(
            f"unknown model {', '.join(bad) or value!r}; choose from sfx, music, medium, all")
    return names


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="otomaker-download",
        description="Download the Stable Audio 3 runtime and model files for OtoMaker "
                    "(no Hugging Face token needed).")
    ap.add_argument("models", nargs="*", metavar="MODEL",
                    choices=sorted(set(ALIASES) | {"all"}),
                    help="sfx, music, medium or all (sm-sfx / sm-music also accepted)")
    ap.add_argument("--models", dest="model_list", type=_model_list, action="append", default=[],
                    metavar="LIST", help="the same as a comma-separated list, e.g. sfx,music")
    ap.add_argument("--runtime-only", action="store_true",
                    help="only fetch the Stable Audio 3 runtime (CPU), no model files")
    ap.add_argument("--comfy", action="store_true",
                    help=f"GPU files for ComfyUI (sa3-comfy) from {COMFY_REPO} instead of the "
                         f"CPU files from {TFLITE_REPO}")
    ap.add_argument("--comfy-dir", type=Path,
                    help="ComfyUI models folder (gets checkpoints\\ and text_encoders\\); "
                         "required with --comfy")
    ap.add_argument("--tflite-dir", type=Path,
                    help="optimized\\tflite folder of the runtime (default: "
                         "$OTOMAKER_SA3_TFLITE_DIR or <data folder>\\stable-audio-3\\optimized\\tflite)")
    ap.add_argument("--precision", choices=PRECISIONS, default="w8a8",
                    help="CPU DiT precision (default w8a8, as OTOMAKER_SA3_PRECISION)")
    ap.add_argument("--decoder", choices=DECODERS, default="same-s",
                    help="CPU codec (default same-s, as OTOMAKER_SA3_DECODER)")
    ap.add_argument("--accept-licenses", "--yes", "-y", dest="accept", action="store_true",
                    help="the user has read and agreed to the model licences shown by this "
                         "command: download without asking. Only on the user's explicit consent.")
    ap.add_argument("--dry-run", action="store_true", help="list the files and sizes, download nothing")
    return ap


def main(argv: list[str] | None = None, stdin=None, interactive: bool | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    requested = list(args.models) + [n for group in args.model_list for n in group]
    if args.runtime_only:
        if requested or args.comfy:
            ap.error("--runtime-only takes no models and no --comfy")
        names: list[str] = []
    elif not requested:
        ap.error("name the models to download (sfx, music, medium, all; e.g. --models sfx,music) "
                 "or pass --runtime-only")
    else:
        names = ALL_MODELS if "all" in requested else \
            list(dict.fromkeys(ALIASES[m] for m in requested))
    if interactive is None:
        interactive = stdin is not None or _stdin_is_interactive()

    need_runtime: Path | None = None
    if args.comfy:
        if args.comfy_dir is None:
            ap.error("--comfy needs --comfy-dir (your ComfyUI models folder)")
        dest = args.comfy_dir.expanduser().resolve()
        items = comfy_items(names, dest)
        print(f"GPU (ComfyUI) files from {COMFY_REPO} into {dest}")
    else:
        dest = Path(args.tflite_dir or os.environ.get("OTOMAKER_SA3_TFLITE_DIR")
                    or sa3_tflite.DEFAULT_TFLITE_DIR).expanduser().resolve()
        items = tflite_items(names, dest, args.precision, args.decoder)
        print(f"CPU (TFLite) runtime and files in {dest}")
        if runtime_present(dest):
            print("  have  runtime (Stability-AI/stable-audio-3, optimized/tflite)")
        else:
            need_runtime = runtime_root(dest)
            if need_runtime is None:
                print(f"error: the Stable Audio 3 runtime is not at {dest}, and that folder is "
                      "not named ...\\optimized\\tflite, so it cannot be fetched there. Pass "
                      "--tflite-dir <folder>\\stable-audio-3\\optimized\\tflite or omit it.",
                      file=sys.stderr)
                if not args.dry_run:
                    return 2
            else:
                print(f"  get   runtime: Stability-AI/stable-audio-3 commit {SA3_COMMIT[:7]} (MIT), "
                  f"optimized/tflite only, into {need_runtime}")

    todo = [i for i in items if not present(i)]
    sizes = remote_sizes(todo) if todo else {}
    for i in items:
        if i in todo:
            size = sizes.get((i.repo, i.filename))
            print(f"  get   {i.filename}  ({_gb(size) if size is not None else 'size unknown'})")
        else:
            print(f"  have  {i.filename}")
    if not todo and need_runtime is None:
        print("Everything is already in place.")
        return 0
    if todo:
        total = sum(sizes.get((i.repo, i.filename), 0) for i in todo)
        print(f"Model files to download: {len(todo)}, {_gb(total)} "
              f"(through the Hugging Face cache, HF_HOME)")
        print_licenses()

    if args.dry_run:
        print("Dry run: nothing was downloaded (model files need the licence consent first).")
        return 0
    if todo and not args.accept:
        if not interactive:
            print("Not downloading anything: the model licences above need the user's explicit "
                  "agreement and there is no terminal to ask in. Show the user the terms and "
                  "URLs; once they agree, run this again with --accept-licenses.")
            return 4
        if not ask_consent(stdin):
            print("Not agreed: nothing was downloaded.")
            return 1

    if need_runtime is not None:
        try:
            n = fetch_runtime(need_runtime)
        except Exception as e:
            print(f"error: could not fetch the runtime: {e}", file=sys.stderr)
            return 2
        print(f"    -> {dest} ({n} files)")
    if todo:
        try:
            import huggingface_hub  # noqa: F401
        except ImportError:
            print("error: huggingface_hub is missing. Install otomaker with the tflite extra, "
                  "e.g. uv sync --extra tflite --no-dev", file=sys.stderr)
            return 2
        for i in todo:
            print(f"  downloading {i.filename}", flush=True)
            mode = fetch(i, args.comfy)
            print(f"    -> {i.target} ({mode})")
    print("Done.")
    return 0


def _entry() -> None:
    sys.exit(main())


if __name__ == "__main__":
    _entry()
