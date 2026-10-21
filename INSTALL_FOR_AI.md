# Installing OtoMaker: instructions for an AI assistant

You are an AI assistant (Claude Code or similar) and the user asked you to install OtoMaker, a local MCP server that generates music and sound effects with Stable Audio 3 on the CPU. Follow these steps in order. Run the commands yourself, show the user what they print, and stop where a step says to wait for the user.

**Source.** Every command below uses this package source. The repository is `og3-lab/otomaker-win`:

```
otomaker[tflite] @ git+https://github.com/og3-lab/otomaker-win
```

In the commands it appears as `SRC`. Always use exactly the same `SRC` string, so that uv reuses one cached environment. To pin a version, append `@<tag or commit>` to the URL.

## 1. Check the prerequisites

- **Windows 10 or 11.** OtoMaker does not support other systems. Stop and tell the user if this is not Windows.
- **Disk space:** about 3 GB for the two small models (`sfx` and `music`), plus about 0.2 GB for the Python packages. `medium` needs about 5 GB more.
- **uv:** run `uv --version` (0.6 or later). If it is missing, ask the user whether you may install it, then run:

  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

  The installer puts `uv.exe` and `uvx.exe` in `%USERPROFILE%\.local\bin`. Your current shell may not see them on `PATH` yet. Call them by their full path until the next restart.
- **Git:** run `git --version`. uv needs Git for a `git+https` source. If Git is missing, either ask the user to install it (`winget install --id Git.Git -e`), or use the source archive instead of Git: `otomaker[tflite] @ https://github.com/og3-lab/otomaker-win/archive/refs/heads/main.zip`.
- **ffmpeg** (optional): run `ffmpeg -version`. Without it, `process_audio` cannot resample audio or normalize loudness. Generation works without it. To install it: `winget install --id Gyan.FFmpeg -e`.

## 2. Show the files and licenses

```powershell
uvx --from "SRC" otomaker-download --models sfx,music --dry-run
```

This downloads nothing except the Python packages (the first run takes a minute or two). It lists the runtime and model files with their sizes, and prints the license terms. Models: `sfx` (small sound-effect model, up to 120 s), `music` (small music model, up to 120 s), `medium` (larger music model, up to 380 s, large download), `all`.

## 3. Get the user's consent. Never give it yourself

The model weights are not part of OtoMaker. Before you download them, show the user these terms and links, in the user's language:

- **Stable Audio 3 model weights: Stability AI Community License.** https://stability.ai/community-license-agreement. Free for research, non-commercial use, and for organizations or individuals with less than US$1M in annual revenue. Above that, an Enterprise License from Stability AI is required.
- **T5Gemma text encoder: Gemma Terms of Use.** https://ai.google.dev/gemma/terms. This includes the Gemma Prohibited Use Policy.

Then ask which models they want (`sfx,music` is the usual choice) and whether they agree to these terms. **Wait for an explicit answer.** A request such as "install OtoMaker" is not agreement to the license terms. Do not agree on the user's behalf, and do not pass `--accept-licenses` before the user has said yes.

## 4. Download the runtime and the models (only after the user agreed)

```powershell
uvx --from "SRC" otomaker-download --models sfx,music --accept-licenses
```

This fetches the Stable Audio 3 runtime (Stability-AI/stable-audio-3, MIT; a pinned commit checked against its SHA256) and the model files into `%LOCALAPPDATA%\OtoMaker`. The model files go through the Hugging Face cache, `%USERPROFILE%\.cache\huggingface`. No Hugging Face account or token is needed.

Exit codes: `0` done. `1` the user declined at the prompt. `2` error (read the message). `4` consent is missing: the command was run without `--accept-licenses` and had no terminal to ask in, so nothing was downloaded.

If the user declines, stop here. Without the models the server starts, but every generation fails until they are downloaded.

## 5. Register the MCP server

Use the full path of `uvx.exe` (`(Get-Command uvx).Source`, usually `%USERPROFILE%\.local\bin\uvx.exe`). The MCP client may not have the same `PATH` as your shell.

**Claude Code:**

```powershell
claude mcp add --scope user otomaker -- "C:\Users\<name>\.local\bin\uvx.exe" --from "SRC" otomaker-mcp
```

**Claude Desktop:** first copy `%APPDATA%\Claude\claude_desktop_config.json` to a backup file. Then add only this entry under `"mcpServers"`, and keep every other key as it is:

```json
"otomaker": {
  "command": "C:\\Users\\<name>\\.local\\bin\\uvx.exe",
  "args": ["--from", "SRC", "otomaker-mcp"]
}
```

**OpenAI Codex:** register it with `codex mcp add`, then set the timeouts in `%USERPROFILE%\.codex\config.toml` (or `%CODEX_HOME%\config.toml`). `codex mcp add` has no timeout option, and a generation takes 30-60 s, which the default tool timeout (60 s) does not safely cover.

```powershell
codex mcp add otomaker -- "C:\Users\<name>\.local\bin\uvx.exe" --from "SRC" otomaker-mcp
```

Then add the two timeout lines to the `[mcp_servers.otomaker]` table it wrote. Or edit `config.toml` by hand: back it up first, then add only this table and keep every other line and comment as it is:

```toml
[mcp_servers.otomaker]
command = 'C:\Users\<name>\.local\bin\uvx.exe'
args = ["--from", "SRC", "otomaker-mcp"]
startup_timeout_sec = 60
tool_timeout_sec = 300
```

ChatGPT on the web cannot use an MCP server that runs on this PC. Use Codex (CLI or app) instead.

Other MCP clients take the same `command` and `args`.

## 6. Restart the client

Tell the user to restart the MCP client:

- **Claude Code:** start a new session.
- **Codex:** start a new session.
- **Claude Desktop:** quit it from the tray icon, then start it again. Closing the window does not quit it.

## 7. Check that it works

- **Claude Code:** `claude mcp list` should show `otomaker` as connected.
- **Codex:** `codex mcp list` should show `otomaker`.
- After the restart, ask for a short test: "Generate a 2-second sound effect of a knock on a wooden door." A WAV path under `%LOCALAPPDATA%\OtoMaker\outputs\` should come back. The first generation also loads the model, so it takes longer than later ones.
- If a tool returns an error, it says what to run next, for example an `otomaker-download` command for a missing model. Get the user's consent again (step 3) before you download more models.

## Notes

- **Data folder:** `%LOCALAPPDATA%\OtoMaker` holds `stable-audio-3\` (the runtime and the model links) and `outputs\`. Set `OTOMAKER_HOME` to use another folder. If you set it, set the same value for `otomaker-download` and in the MCP registration (`claude mcp add -e OTOMAKER_HOME=...`). Folder names with non-ASCII characters (a Japanese user name, for example) are fine.
- **Settings:** see the environment variable table in [README.md](README.md), for example `OTOMAKER_SA3_MODEL=sm-sfx` to make the sound-effect model the default.
- **Uninstall:** run `claude mcp remove --scope user otomaker`, or remove the `otomaker` entry from the Claude Desktop config. For Codex, run `codex mcp remove otomaker`, or delete the `[mcp_servers.otomaker]` table from `config.toml`. Then delete `%LOCALAPPDATA%\OtoMaker`, and the folder `models--stabilityai--stable-audio-3-optimized` under `%USERPROFILE%\.cache\huggingface\hub`.
