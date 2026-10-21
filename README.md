# OtoMaker for Windows

**OtoMaker** is a free, local MCP server for Windows. Ask Claude Code, Claude Desktop, Cursor or any other [MCP](https://modelcontextprotocol.io) client for background music or a sound effect in plain language. The model ([Stable Audio 3](https://github.com/Stability-AI/stable-audio-3)) generates it on your PC. The server can then loop it, normalize the loudness and export WAV, OGG or FLAC for a game engine or video editor.

- **Platform:** Windows 10 / 11
- **Runs on the CPU by default.** An NVIDIA GPU with ComfyUI is faster and optional.
- **Instrumental only.** Stable Audio 3 cannot produce intelligible vocals or lyrics.

**English** | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

**Installing with an AI assistant (Claude Code and others):** ask it to follow [INSTALL_FOR_AI.md](INSTALL_FOR_AI.md).

## Tools

| Tool | What it does |
|---|---|
| `generate_audio` | Text to BGM, instrument loop/stem or sound effect. 1–4 candidates per call, `bpm`, structured SFX fields |
| `edit_audio` | `variation` (re-style the whole clip), `inpaint` (regenerate a time range), `continue` (extend). 1–4 candidates |
| `process_audio` | Trim, trim silence, mono, resample, loudness (LUFS) or peak normalization, seamless loop, fades, WAV / OGG / FLAC export. Never modifies the input |
| `unload_models` | Free the model memory right away |

Generated files are 44.1 kHz 24-bit stereo WAV in `outputs\` under the OtoMaker data folder (the OtoMaker folder itself with `install.cmd`, `%LOCALAPPDATA%\OtoMaker` with `uvx`). Each one has a `<file>.json` sidecar (for example `rain.wav.json`) with its prompt, seed, settings and the file paths involved. Paths under your user profile are written as `%USERPROFILE%`. Other paths are written as they are: if the output folder (`OTOMAKER_OUTPUT_DIR`) or an input file is in a folder outside your profile whose name contains your name, that name ends up in the `.json`.

## Requirements

- Windows 10 or 11 and an internet connection (for the installation and the model download)
- [ffmpeg](https://ffmpeg.org), used for resampling and loudness. For example: `winget install --id Gyan.FFmpeg -e`. If `ffmpeg` is not on `PATH`, set `OTOMAKER_FFMPEG` to the full path of `ffmpeg.exe`. The installer tells you when it cannot find it.
- Optional: an NVIDIA GPU with a running ComfyUI, for the `sa3-comfy` backend.

You do not need to install Python, uv or Git first: `install.cmd` sets them up inside the OtoMaker folder. The Stable Audio 3 runtime and the model files are not included in this package; they are downloaded during the installation.

Folder names with Japanese or other non-ASCII characters (for example under a Japanese user name) are fine. The TFLite runtime cannot open such paths itself, so OtoMaker hands it ASCII forms of them (the 8.3 short name, or a path relative to the runtime folder).

You do not need a Hugging Face account or token. The model repositories are public.

## Installation (install.cmd)

1. Extract the zip (for example to `C:\Tools\OtoMaker`). It cannot run from inside the zip.
2. Double-click `install.cmd` in the extracted folder. It goes through these steps:
   1. **uv**: uses the uv on `PATH`. If there is none, it downloads a pinned version of the official build ([astral-sh/uv](https://github.com/astral-sh/uv) GitHub Releases), checks its SHA256 and puts it in `runtime\uv\`.
   2. **Python 3.12 and the dependencies**: runs `uv sync --locked --extra tflite --no-dev`, with a uv-managed Python in `runtime\python\`.
   3. **The Stable Audio 3 runtime**: downloads the archive of the tested commit `77e0398` from GitHub, checks its SHA256 and extracts it to `stable-audio-3\optimized\tflite`.
   4. **Models**: you pick the models (`sfx` and `music` are recommended). The file list and the license terms are shown; type `y` to agree and download.
   5. **MCP registration**: asks (Y/N each) whether to register `otomaker` with Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`) and Claude Code (`claude mcp add --scope user`). The Claude Desktop config is backed up as `.bak-<date-time>` before the change; only `otomaker` is added under `mcpServers`, everything else stays as it was. If you use OpenAI Codex (`%USERPROFILE%\.codex\config.toml` or that folder exists, or the `codex` command is found; `CODEX_HOME` is honored), it also asks whether to add `[mcp_servers.otomaker]` to `config.toml`, with `tool_timeout_sec = 300` because a generation takes 30-60 s. The file is backed up the same way, and only that table is added or replaced; other settings and comments stay.
3. Restart Claude (and Codex). Quit Claude Desktop from its tray icon, then start it again.

The installer does not change `PATH` or any system setting. uv, Python and the package cache all stay inside the OtoMaker folder (`runtime\`, `.venv\`, `stable-audio-3\`). Only the model files go to the Hugging Face cache (see below). Running `install.cmd` again sets up only what is missing.

- **Get models later:** double-click `download-models.cmd`. Until a model is downloaded, a generation with it stops and names the command to run.
- **Remove the registration:** double-click `uninstall.cmd`. It removes `otomaker` from Claude Desktop, Claude Code and Codex (Y/N each). It does not delete the folder or the models; delete the places it lists yourself if you no longer need them. Your generated audio (`outputs\`) is in the folder too.
- **Other clients (Cursor and others):** put the full path of `<OtoMaker folder>\.venv\Scripts\otomaker-mcp.exe` as `"command"` in their MCP config.

## Manual setup (CPU, sa3-tflite)

The steps without `install.cmd`. They use [uv](https://docs.astral.sh/uv/) and [Git](https://git-scm.com).

1. In the OtoMaker folder, get the Stable Audio 3 runtime ([Stability-AI/stable-audio-3](https://github.com/Stability-AI/stable-audio-3), MIT). OtoMaker was tested with commit `77e0398`. Later commits may change the internals that OtoMaker uses.

   ```bat
   cd C:\Tools\OtoMaker
   git clone https://github.com/Stability-AI/stable-audio-3.git
   cd stable-audio-3
   git checkout 77e0398
   cd ..
   ```

   The runtime is now at `<OtoMaker folder>\stable-audio-3\optimized\tflite`, where OtoMaker looks by default. If you put it somewhere else, set `OTOMAKER_SA3_TFLITE_DIR` to its `optimized\tflite` folder.

2. Install the dependencies, including the TFLite extra. `--no-dev` leaves out the test tools:

   ```bat
   uv sync --extra tflite --no-dev
   ```

3. Download the models you want: `sfx` (small sound-effect model) and `music` (small music model), both up to 120 s, or `medium` (larger music model, up to 380 s). `all` gets all three. The text encoder that all models share is added once. The command lists the files and their sizes, shows the license terms and asks you to agree (`y`). `--accept-licenses` agrees without asking (only if you have read the terms; without it and without a terminal, nothing is downloaded). `--models sfx,music` is the same as listing the names. `--dry-run` only lists the files. If the runtime (step 1) is missing, the command also fetches it (the same pinned commit and SHA256 check as `install.cmd`).

   ```bat
   .venv\Scripts\otomaker-download.exe sfx music
   ```

   If you skip this step, a generation stops with the command to run. `OTOMAKER_SA3_AUTO_DOWNLOAD=1` lets the runtime download the files on first use instead.

4. Register the server with Claude Code (replace the path with yours):

   ```bat
   claude mcp add --scope user otomaker -- "C:\Tools\OtoMaker\.venv\Scripts\otomaker-mcp.exe"
   ```

   If the runtime is not in the default place, add `-e OTOMAKER_SA3_TFLITE_DIR=<path>`. Claude Desktop, Cursor and other clients take the same command in their MCP config, as `"command"` with the path to `otomaker-mcp.exe`.

`otomaker-mcp.exe` talks to the client over stdio. With `--http PORT` it serves streamable HTTP at `http://127.0.0.1:PORT/mcp` instead (reachable from this PC only), for clients that connect by URL. `--preload` loads the models at startup, so the first request does not wait for them.

**Where the model files go, and disk space.** The files are downloaded into the Hugging Face cache (`HF_HOME`, by default `%USERPROFILE%\.cache\huggingface`) and made visible in the runtime's `models\` folder. With Windows Developer Mode on, this is a symbolic link. Without it, it is a hard link if both folders are on the same drive, and otherwise a full copy, which uses the space twice. To avoid the copy, keep the OtoMaker folder on the same drive as `HF_HOME`, or set `HF_HOME` to a folder on that drive. On first use the runtime also writes a weight cache (`.xnnwc`) next to each DiT and codec model, almost as large as the model itself. Measured on a test PC with hard links: about 1.8 GB for `music` alone, about 1.0 GB more for each further small model, and about 3.2 GB more for `medium`. A copy adds the download size once more (1.25 GB for `music` alone).

## Setup (GPU, sa3-comfy)

`sa3-comfy` sends each request to a ComfyUI that you run yourself, at `OTOMAKER_COMFY_HOST` (default `127.0.0.1:8188`, ComfyUI's own default). This backend supports text-to-audio only (no `edit_audio`). Set `OTOMAKER_BACKEND=sa3-comfy`. To fall back to the CPU when ComfyUI is not running, also set `OTOMAKER_FALLBACK=sa3-tflite`. The result and its metadata record the fallback.

1. Download the ComfyUI files from [Comfy-Org/stable-audio-3](https://huggingface.co/Comfy-Org/stable-audio-3). The medium checkpoint is 9.2 GB, each small one 2.3 GB and the text encoder 1.2 GB. The files go into `checkpoints\` and `text_encoders\` under `--comfy-dir`:

   ```bat
   .venv\Scripts\otomaker-download.exe sfx music --comfy --comfy-dir C:\path\to\ComfyUI\models
   ```

2. If `--comfy-dir` was ComfyUI's own `models` folder, you are done. For any other folder, open `tools\comfy_extra_paths.yaml` and copy its `otomaker:` block into the `extra_model_paths.yaml` of your ComfyUI (next to its `main.py`; if the file does not exist, copy `extra_model_paths.yaml.example` to that name first). Set `base_path` to your folder and restart ComfyUI.

By default `unload_models` and the idle unload do not touch ComfyUI's memory, because ComfyUI's `/free` unloads every model in it, including the models of other tools. Set `OTOMAKER_COMFY_FREE=1` to send `/free`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OTOMAKER_BACKEND` | `sa3-tflite` | `sa3-tflite` (CPU) or `sa3-comfy` (ComfyUI) |
| `OTOMAKER_FALLBACK` | off | Backend for a `generate_audio` call when ComfyUI cannot be reached, e.g. `sa3-tflite` |
| `OTOMAKER_HOME` | the OtoMaker folder; `%LOCALAPPDATA%\OtoMaker` when installed with `uvx` | Data folder: the runtime and `outputs\` go here |
| `OTOMAKER_SA3_TFLITE_DIR` | `<data folder>\stable-audio-3\optimized\tflite` | The `optimized\tflite` folder of the runtime |
| `OTOMAKER_SA3_MODEL` | `sm-music` | `sm-music`, `sm-sfx` (up to 120 s) or `medium` (up to 380 s) |
| `OTOMAKER_SA3_PRECISION` | `w8a8` | `w8a8` or `fp32` (TFLite) |
| `OTOMAKER_SA3_DECODER` | the upstream pairing | `same-s` or `same-l` (TFLite) |
| `OTOMAKER_SA3_AUTO_DOWNLOAD` | `0` | `1` lets the runtime download missing model files on first use (without the license prompt of `otomaker-download`) |
| `OTOMAKER_SA3_THREADS` | physical cores, at most 10 | CPU threads for the TFLite runtime. Cores are counted with psutil, which the `tflite` extra installs |
| `OTOMAKER_COMFY_HOST` | `127.0.0.1:8188` | Address of ComfyUI (`sa3-comfy`) |
| `OTOMAKER_COMFY_LENGTH_SUFFIX` | `1` | `1` appends "Length: N seconds" to the prompt for ComfyUI; `0` sends the prompt as is |
| `OTOMAKER_COMFY_FREE` | `0` | `1` lets `unload_models` and the idle unload send `/free` to ComfyUI (unloads all of its models) |
| `OTOMAKER_OUTPUT_DIR` | `<data folder>\outputs` | Where audio files are written |
| `OTOMAKER_IDLE_UNLOAD_MIN` | `10` | Free the models after this many idle minutes (`0` = never) |
| `OTOMAKER_FFMPEG` | `ffmpeg` on `PATH` | Full path to `ffmpeg.exe` |
| `HF_HOME` | `%USERPROFILE%\.cache\huggingface` | Hugging Face cache for the model downloads |

Pass them with `claude mcp add ... -e NAME=value`, or in the `env` block of your client's MCP config.

## Prompting tips

1. Write English, one or two sentences, up to about 45 words. Avoid vocal words such as "vocals", "singer" or "lyrics".
2. Music: genre and adjectives, then lead instruments, supporting layers, drums and mood. Put the tempo in `bpm`.
3. Sound effects: fill in `sound_source`, `sound_action`, `sound_material` and `sound_space`. The server adds the prefix the model was trained with.
4. Match the length to the content: impacts 1–3 s, actions 3–6 s, ambience 6–15 s, loops 6–20 s, full tracks 120–300 s.
5. Timing instructions such as "climax at 15 s" are not followed reliably. Generate first, then use `edit_audio` with `inpaint` or `continue`.
6. Results vary a lot by seed. Ask for 2–4 `variations` and pick the best.

Peak normalization uses a safety ceiling: `peak_ceiling_db` (default −1) turns down louder peaks and never boosts quieter audio. Use `process_audio` to normalize loudness. For OGG output, `process_audio` reports the levels measured on the encoded file.

## Development

This section is for developers. Install with the test tools and run the offline tests:

```bat
uv sync --extra tflite
uv run --extra tflite pytest -q
```

The offline tests use a fake backend, so they need neither the runtime nor the weights. The git repository also has `scripts\smoke_test.py`, a developer check that runs every tool once over stdio against the real model. It is not part of the distributed zip.

```
src\otomaker\
  server.py            MCP tools (backend-independent)
  prompts.py           prompt building and the instructions sent to clients
  post.py              post-processing and export
  download.py          otomaker-download (model files)
  backends\base.py     backend interface
  backends\sa3_tflite.py  Stable Audio 3 on the CPU (TFLite / LiteRT)
  backends\sa3_comfy.py   Stable Audio 3 through ComfyUI
```

## FAQ

**Does it work without an NVIDIA GPU?** Yes. The default backend runs on the CPU. Generation is slower than with a GPU and ComfyUI.

**Can it make songs with vocals?** No. Stable Audio 3 generates instrumental music and sound effects.

**Do I need a Hugging Face token?** No. The model files are public.

**My loop clicks at the seam.** Use WAV or OGG for loops. MP3 adds padding at the start and end. Try a longer `loop_crossfade_ms`, or ask for a cut on a bar line.

## License and notices

The full notices are in [NOTICE](NOTICE).

- **This project:** [MIT](LICENSE). Copyright (c) 2026 kanaworksai-hue (original code), Copyright (c) 2026 OG-3 (Windows additions and changes). Based on [kanaworksai-hue/audio-studio-mcp](https://github.com/kanaworksai-hue/audio-studio-mcp) (MIT).
- **Stable Audio 3 model weights:** not included. They are downloaded from Hugging Face and licensed under the [Stability AI Community License](https://stability.ai/community-license-agreement). If your annual revenue is US$1M or more, commercial use needs an Enterprise License from Stability AI. This Stability AI Model is licensed under the Stability AI Community License, Copyright © Stability AI Ltd. All Rights Reserved. Powered by Stability AI.
- **T5Gemma text encoder:** not included. It is downloaded with the models and subject to the [Gemma Terms of Use](https://ai.google.dev/gemma/terms).
- **Stable Audio 3 runtime code:** [Stability-AI/stable-audio-3](https://github.com/Stability-AI/stable-audio-3), MIT, Copyright (c) 2026 Stability AI. Not included. You clone it, and OtoMaker loads it at run time.
- **Built on:** [Stable Audio 3](https://github.com/Stability-AI/stable-audio-3) and the [Model Context Protocol](https://modelcontextprotocol.io).

This is an independent project. It is not affiliated with or endorsed by Stability AI, Google or Anthropic.
