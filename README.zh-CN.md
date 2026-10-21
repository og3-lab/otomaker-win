# OtoMaker for Windows

**OtoMaker** 是一个免费的、在本地运行的 Windows MCP 服务器。你可以用自然语言向 Claude Code、Claude Desktop、Cursor 或任何其他 [MCP](https://modelcontextprotocol.io) 客户端请求背景音乐或音效。模型（[Stable Audio 3](https://github.com/Stability-AI/stable-audio-3)）在你自己的电脑上生成音频。随后可以循环、标准化响度，并导出为 WAV、OGG 或 FLAC，用于游戏引擎或视频编辑。

- **平台：** Windows 10 / 11
- **默认在 CPU 上运行。** 有 NVIDIA GPU 和 ComfyUI 时会更快（可选）。
- **仅限器乐。** Stable Audio 3 无法生成可听清的人声或歌词。

**简体中文** | [English](README.md) | [日本語](README.ja.md)

**让 AI 助手（Claude Code 等）来安装：** 请它按照 [INSTALL_FOR_AI.md](INSTALL_FOR_AI.md) 操作。

## 工具

| 工具 | 功能 |
|---|---|
| `generate_audio` | 从文本生成背景音乐、乐器循环/音轨或音效。每次调用可生成 1–4 个候选，支持 `bpm` 和结构化音效字段 |
| `edit_audio` | `variation`（重新设定整体风格）、`inpaint`（重新生成某个时间段）、`continue`（延长）。1–4 个候选 |
| `process_audio` | 裁剪、去除静音、转单声道、重采样、响度（LUFS）或峰值标准化、无缝循环、淡入淡出、导出 WAV / OGG / FLAC。不修改输入文件 |
| `unload_models` | 立即释放模型占用的内存 |

生成的文件为 44.1 kHz / 24 bit / 立体声 WAV，写入 OtoMaker 数据文件夹（使用 `install.cmd` 时为 OtoMaker 文件夹本身，使用 `uvx` 时为 `%LOCALAPPDATA%\OtoMaker`）下的 `outputs\`。每个文件旁边都有一个 `<文件名>.json`（例如 `rain.wav.json`），记录提示词、种子、设置以及相关文件的路径。用户配置文件夹（profile）内的路径会被写成 `%USERPROFILE%`；其他路径按原样记录。因此，如果输出文件夹（`OTOMAKER_OUTPUT_DIR`）或输入文件位于配置文件夹之外、且文件夹名包含你的姓名，该姓名会留在 `.json` 中。

## 运行要求

- Windows 10 或 11，以及网络连接（用于安装和下载模型）
- [ffmpeg](https://ffmpeg.org)（用于重采样和响度处理）。例如：`winget install --id Gyan.FFmpeg -e`。如果 `ffmpeg` 不在 `PATH` 中，请将 `OTOMAKER_FFMPEG` 设为 `ffmpeg.exe` 的完整路径。找不到时安装程序会提示。
- 可选：NVIDIA GPU 和已启动的 ComfyUI（用于 `sa3-comfy` 后端）。

无需事先安装 Python、uv 或 Git：`install.cmd` 会在 OtoMaker 文件夹内准备好它们。Stable Audio 3 的运行时和模型文件不包含在本软件包中，会在安装时下载。

文件夹名可以包含中文、日文等非 ASCII 字符（例如位于中文或日文用户名下）。TFLite 运行时自身无法打开这类路径，OtoMaker 会把它们转换成只含 ASCII 的形式（8.3 短文件名，或相对于运行时文件夹的路径）再交给它。

不需要 Hugging Face 账号或令牌。模型仓库是公开的。

## 安装（install.cmd）

1. 解压 zip（例如到 `C:\Tools\OtoMaker`）。不能在 zip 内直接运行。
2. 双击解压后文件夹中的 `install.cmd`。它按以下顺序进行：
   1. **uv**：使用 `PATH` 中的 uv。如果没有，则下载固定版本的官方发行版（[astral-sh/uv](https://github.com/astral-sh/uv) 的 GitHub Releases），校验 SHA256 后放入 `runtime\uv\`。
   2. **Python 3.12 和依赖**：运行 `uv sync --locked --extra tflite --no-dev`，使用 uv 管理的 Python（放在 `runtime\python\`）。
   3. **Stable Audio 3 运行时**：从 GitHub 下载已验证的提交 `77e0398` 的归档，校验 SHA256 后解压到 `stable-audio-3\optimized\tflite`。
   4. **模型**：选择要下载的模型（推荐 `sfx` 和 `music`）。会显示文件列表和许可条款，同意时输入 `y`。
   5. **注册 MCP**：分别询问（Y/N）是否在 Claude Desktop（`%APPDATA%\Claude\claude_desktop_config.json`）和 Claude Code（`claude mcp add --scope user`）中注册 `otomaker`。修改前会将 Claude Desktop 的配置文件备份为 `.bak-日期时间`，只在 `mcpServers` 中添加 `otomaker`，其他设置保持不变。
3. 重启 Claude。Claude Desktop 请从任务栏托盘图标退出后再重新启动。

安装程序不会修改 `PATH` 或任何系统设置。uv、Python 和软件包缓存都放在 OtoMaker 文件夹内（`runtime\`、`.venv\`、`stable-audio-3\`）。只有模型文件放在 Hugging Face 缓存中（见下文）。再次运行 `install.cmd` 只会补齐缺少的部分。

- **之后再下载模型：** 双击 `download-models.cmd`。模型下载之前，用它生成会停止并提示要运行的命令。
- **取消注册：** 双击 `uninstall.cmd`。它会从 Claude Desktop 和 Claude Code 中移除 `otomaker`（分别以 Y/N 确认）。不会删除文件夹和模型；不再需要时请手动删除它列出的位置。生成的音频（`outputs\`）也在该文件夹中。
- **其他客户端（Cursor 等）：** 在其 MCP 配置的 `"command"` 中填写 `<OtoMaker 文件夹>\.venv\Scripts\otomaker-mcp.exe` 的完整路径。

## 手动安装（CPU，sa3-tflite）

不使用 `install.cmd` 时的步骤。需要 [uv](https://docs.astral.sh/uv/) 和 [Git](https://git-scm.com)。

1. 在 OtoMaker 文件夹中获取 Stable Audio 3 运行时（[Stability-AI/stable-audio-3](https://github.com/Stability-AI/stable-audio-3)，MIT）。OtoMaker 已在提交 `77e0398` 上验证。之后的提交可能会改变 OtoMaker 所使用的内部接口。

   ```bat
   cd C:\Tools\OtoMaker
   git clone https://github.com/Stability-AI/stable-audio-3.git
   cd stable-audio-3
   git checkout 77e0398
   cd ..
   ```

   这样运行时就位于 OtoMaker 默认查找的 `<OtoMaker 文件夹>\stable-audio-3\optimized\tflite`。如果放在其他位置，请将 `OTOMAKER_SA3_TFLITE_DIR` 设置为其中的 `optimized\tflite` 文件夹。

2. 安装依赖（包括 TFLite 附加依赖）。`--no-dev` 表示不安装测试工具：

   ```bat
   uv sync --extra tflite --no-dev
   ```

3. 下载需要的模型：`sfx`（小型音效模型）和 `music`（小型音乐模型）最长均为 120 秒，`medium`（较大的音乐模型）最长 380 秒。`all` 表示下载全部三个。所有模型共用的文本编码器只下载一次。该命令会列出文件及大小、显示许可条款并请求你同意（`y`）。`--accept-licenses` 表示不询问直接同意（仅在你已阅读并同意条款时使用；不加此选项且没有终端时，不会下载任何内容）。`--models sfx,music` 与直接列出名称相同。`--dry-run` 只列出文件。如果缺少运行时（第 1 步），该命令也会下载它（与 `install.cmd` 相同的固定提交和 SHA256 校验）。

   ```bat
   .venv\Scripts\otomaker-download.exe sfx music
   ```

   如果跳过这一步，生成会停止并提示要运行的命令。设置 `OTOMAKER_SA3_AUTO_DOWNLOAD=1` 则改为由运行时在首次使用时下载这些文件。

4. 在 Claude Code 中注册服务器（请替换为你的路径）：

   ```bat
   claude mcp add --scope user otomaker -- "C:\Tools\OtoMaker\.venv\Scripts\otomaker-mcp.exe"
   ```

   如果运行时不在默认位置，请加上 `-e OTOMAKER_SA3_TFLITE_DIR=<路径>`。Claude Desktop、Cursor 等其他客户端在 MCP 配置中使用同一个命令，即把 `otomaker-mcp.exe` 的路径写在 `"command"` 中。

`otomaker-mcp.exe` 通过标准输入输出（stdio）与客户端通信。加上 `--http 端口` 时，改为在 `http://127.0.0.1:端口/mcp` 提供 Streamable HTTP（仅本机可访问），适用于通过 URL 连接的客户端。`--preload` 会在启动时加载模型，这样第一个请求无需等待模型加载。

**模型文件的位置和所需磁盘空间。** 文件会下载到 Hugging Face 缓存（`HF_HOME`，默认 `%USERPROFILE%\.cache\huggingface`），并在运行时的 `models\` 文件夹中可见。开启 Windows 开发者模式时使用符号链接；未开启时，若两者在同一驱动器上则使用硬链接，否则完整复制一份，占用两倍空间。要避免复制，请把 OtoMaker 文件夹放在与 `HF_HOME` 相同的驱动器上，或把 `HF_HOME` 设置为该驱动器上的文件夹。此外，运行时首次使用时会在每个 DiT 和编解码器模型旁写入一个权重缓存（`.xnnwc`），大小与模型本身相近。在测试电脑（硬链接）上实测：仅 `music` 约 1.8 GB，每增加一个小型模型约增加 1.0 GB，增加 `medium` 约增加 3.2 GB。若发生复制，还要再加上下载量（仅 `music` 为 1.25 GB）。

## 安装（GPU，sa3-comfy）

`sa3-comfy` 会把每个生成请求发送到你自己启动的 ComfyUI（地址为 `OTOMAKER_COMFY_HOST`，默认 `127.0.0.1:8188`，与 ComfyUI 自身的默认值相同）。该后端仅支持文本生成音频（不支持 `edit_audio`）。设置 `OTOMAKER_BACKEND=sa3-comfy`。如果 ComfyUI 未运行时要改用 CPU，还需设置 `OTOMAKER_FALLBACK=sa3-tflite`。切换的情况会记录在生成结果和元数据中。

1. 从 [Comfy-Org/stable-audio-3](https://huggingface.co/Comfy-Org/stable-audio-3) 下载 ComfyUI 用的文件。medium 检查点为 9.2 GB，每个小型检查点 2.3 GB，文本编码器 1.2 GB。文件会放入 `--comfy-dir` 下的 `checkpoints\` 和 `text_encoders\`：

   ```bat
   .venv\Scripts\otomaker-download.exe sfx music --comfy --comfy-dir C:\path\to\ComfyUI\models
   ```

2. 如果 `--comfy-dir` 指定的是 ComfyUI 自己的 `models` 文件夹，就完成了。如果是其他文件夹，请打开 `tools\comfy_extra_paths.yaml`，把其中的 `otomaker:` 部分追加到你自己 ComfyUI 的 `extra_model_paths.yaml`（与 `main.py` 在同一文件夹；如果该文件不存在，先把 `extra_model_paths.yaml.example` 复制为这个名字）。把 `base_path` 改为该文件夹，然后重启 ComfyUI。

默认情况下，`unload_models` 和空闲释放不会触碰 ComfyUI 的内存，因为 ComfyUI 的 `/free` 会卸载其中的所有模型，包括其他工具的模型。如需发送 `/free`，请设置 `OTOMAKER_COMFY_FREE=1`。

## 配置

| 变量 | 默认值 | 含义 |
|---|---|---|
| `OTOMAKER_BACKEND` | `sa3-tflite` | `sa3-tflite`（CPU）或 `sa3-comfy`（ComfyUI） |
| `OTOMAKER_FALLBACK` | 关闭 | 无法连接 ComfyUI 时用于 `generate_audio` 的后端，例如 `sa3-tflite` |
| `OTOMAKER_HOME` | OtoMaker 文件夹（使用 `uvx` 安装时为 `%LOCALAPPDATA%\OtoMaker`） | 数据文件夹：运行时和 `outputs\` 放在这里 |
| `OTOMAKER_SA3_TFLITE_DIR` | `<数据文件夹>\stable-audio-3\optimized\tflite` | 运行时的 `optimized\tflite` 文件夹 |
| `OTOMAKER_SA3_MODEL` | `sm-music` | `sm-music`、`sm-sfx`（最长 120 秒）或 `medium`（最长 380 秒） |
| `OTOMAKER_SA3_PRECISION` | `w8a8` | `w8a8` 或 `fp32`（TFLite） |
| `OTOMAKER_SA3_DECODER` | 上游的默认搭配 | `same-s` 或 `same-l`（TFLite） |
| `OTOMAKER_SA3_AUTO_DOWNLOAD` | `0` | `1` 表示由运行时在首次使用时下载缺少的模型文件（不经过 `otomaker-download` 的许可确认） |
| `OTOMAKER_SA3_THREADS` | 物理核心数，最多 10 | TFLite 运行时的 CPU 线程数。核心数通过 `tflite` 附加依赖安装的 psutil 统计 |
| `OTOMAKER_COMFY_HOST` | `127.0.0.1:8188` | ComfyUI 地址（`sa3-comfy`） |
| `OTOMAKER_COMFY_LENGTH_SUFFIX` | `1` | `1` 会为 ComfyUI 在提示词后追加 “Length: N seconds”；`0` 则原样发送 |
| `OTOMAKER_COMFY_FREE` | `0` | `1` 表示 `unload_models` 和空闲释放会向 ComfyUI 发送 `/free`（卸载其全部模型） |
| `OTOMAKER_OUTPUT_DIR` | `<数据文件夹>\outputs` | 音频文件的输出位置 |
| `OTOMAKER_IDLE_UNLOAD_MIN` | `10` | 空闲这么多分钟后释放模型（`0` 表示从不释放） |
| `OTOMAKER_FFMPEG` | `PATH` 中的 `ffmpeg` | `ffmpeg.exe` 的完整路径 |
| `HF_HOME` | `%USERPROFILE%\.cache\huggingface` | 下载模型所用的 Hugging Face 缓存 |

可通过 `claude mcp add ... -e 名称=值` 传入，或写在客户端 MCP 配置的 `env` 中。

## 提示词技巧

1. 使用英语，1–2 句，约 45 个词以内。避免 “vocals”、“singer”、“lyrics” 等与歌声相关的词。
2. 音乐：先写风格和形容词，然后是主奏乐器、辅助层次、鼓点，最后是情绪。节奏写入 `bpm`。
3. 音效：填写 `sound_source`、`sound_action`、`sound_material` 和 `sound_space`。模型训练时使用的前缀由服务器自动添加。
4. 长度要与内容匹配：冲击声 1–3 秒，动作 3–6 秒，环境声 6–15 秒，循环 6–20 秒，完整曲目 120–300 秒。
5. “15 秒处达到高潮”之类的时间指令不能可靠地被遵循。先生成，再用 `edit_audio` 的 `inpaint` 或 `continue`。
6. 结果随种子变化很大。请设置 2–4 个 `variations` 并挑选最好的一个。

峰值标准化使用安全上限：`peak_ceiling_db`（默认 −1）会降低超过上限的峰值，且绝不会提升较小的音量。如需统一响度，请使用 `process_audio`。导出 OGG 时，`process_audio` 返回的是在编码后的文件上测得的电平。

## 开发

本节面向开发者。安装时包含测试工具，并运行离线测试：

```bat
uv sync --extra tflite
uv run --extra tflite pytest -q
```

离线测试使用假的后端，因此既不需要运行时，也不需要模型权重。git 仓库中还有 `scripts\smoke_test.py`，这是面向开发者的检查脚本，会通过 stdio 对真实模型把所有工具各运行一次。它不包含在分发的 zip 中。

```
src\otomaker\
  server.py            MCP 工具（与后端无关）
  prompts.py           提示词构建及发送给客户端的说明
  post.py              后处理与导出
  download.py          otomaker-download（下载模型文件）
  backends\base.py     后端接口
  backends\sa3_tflite.py  CPU 上的 Stable Audio 3（TFLite / LiteRT）
  backends\sa3_comfy.py   通过 ComfyUI 运行的 Stable Audio 3
```

## 常见问题

**没有 NVIDIA GPU 能用吗？** 能。默认后端在 CPU 上运行。与使用 GPU 和 ComfyUI 相比，生成会更慢。

**能生成带人声的歌曲吗？** 不能。Stable Audio 3 只生成器乐和音效。

**需要 Hugging Face 令牌吗？** 不需要。模型文件是公开的。

**循环的接缝处有咔嗒声。** 循环请使用 WAV 或 OGG。MP3 会在首尾添加填充，因此无法无缝循环。可以加大 `loop_crossfade_ms`，或要求在小节线处切分。

## 许可与声明

完整的声明见 [NOTICE](NOTICE)。

- **本项目：** [MIT](LICENSE)。Copyright (c) 2026 kanaworksai-hue（原始代码），Copyright (c) 2026 OG-3（Windows 版的新增与修改）。基于 [kanaworksai-hue/audio-studio-mcp](https://github.com/kanaworksai-hue/audio-studio-mcp)（MIT）。
- **Stable Audio 3 模型权重：** 不包含在内。从 Hugging Face 下载，采用 [Stability AI Community License](https://stability.ai/community-license-agreement)。年收入达到 100 万美元（US$1M）或以上时，商业使用需要 Stability AI 的 Enterprise License。This Stability AI Model is licensed under the Stability AI Community License, Copyright © Stability AI Ltd. All Rights Reserved. Powered by Stability AI.
- **T5Gemma 文本编码器：** 不包含在内。随模型一起下载，适用 [Gemma Terms of Use](https://ai.google.dev/gemma/terms)。
- **Stable Audio 3 运行时代码：** [Stability-AI/stable-audio-3](https://github.com/Stability-AI/stable-audio-3)，MIT，Copyright (c) 2026 Stability AI。不包含在内，由你自行 clone，OtoMaker 在运行时加载。
- **基于：** [Stable Audio 3](https://github.com/Stability-AI/stable-audio-3) 和 [Model Context Protocol](https://modelcontextprotocol.io)。

本项目为独立项目，与 Stability AI、Google 或 Anthropic 不存在隶属或背书关系。
