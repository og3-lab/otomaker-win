# OtoMaker for Windows

**OtoMaker** は、Windows 向けの無料のローカル MCP サーバーです。Claude Code、Claude Desktop、Cursor など任意の [MCP](https://modelcontextprotocol.io) クライアントに、BGM や効果音を自然な言葉で頼めます。モデル（[Stable Audio 3](https://github.com/Stability-AI/stable-audio-3)）は手元の PC で生成します。生成したものはループ化、ラウドネス正規化を行い、ゲームエンジンや動画編集向けに WAV・OGG・FLAC で書き出せます。

- **対応環境:** Windows 10 / 11
- **既定では CPU で動作します。** NVIDIA GPU と ComfyUI があれば速くなります（任意）。
- **インストゥルメンタルのみ。** Stable Audio 3 は歌声や歌詞を明瞭に生成できません。

**日本語** | [English](README.md) | [简体中文](README.zh-CN.md)

**AI（Claude Code など）に入れてもらう場合:** [INSTALL_FOR_AI.md](INSTALL_FOR_AI.md) に従うよう頼んでください。

## ツール

| ツール | 内容 |
|---|---|
| `generate_audio` | テキストから BGM、楽器のループ・ステム、効果音を生成。1 回の呼び出しで 1〜4 候補、`bpm`、効果音の構造化フィールドに対応 |
| `edit_audio` | `variation`（全体の作風を変える）、`inpaint`（時間範囲を生成し直す）、`continue`（延長）。1〜4 候補 |
| `process_audio` | トリム、無音除去、モノラル化、リサンプル、ラウドネス（LUFS）またはピーク正規化、シームレスループ、フェード、WAV / OGG / FLAC 書き出し。入力は変更しない |
| `unload_models` | モデルのメモリをすぐに解放 |

生成ファイルは 44.1 kHz / 24 bit / ステレオの WAV で、OtoMaker のデータフォルダ（`install.cmd` なら OtoMaker フォルダ、`uvx` なら `%LOCALAPPDATA%\OtoMaker`）の `outputs\` に書き出されます。各ファイルには、プロンプト・シード・設定と関係するファイルのパスを記録した `<ファイル名>.json`（例: `rain.wav.json`）が付きます。ユーザープロファイル内のパスは `%USERPROFILE%` に置き換えて記録します。それ以外のパスはそのまま記録するため、出力先（`OTOMAKER_OUTPUT_DIR`）や入力ファイルを、プロファイルの外にある氏名入りのフォルダに置くと、その氏名が `.json` に残ります。

## 必要なもの

- Windows 10 または 11 とインターネット接続（インストールとモデルの取得に使用）
- [ffmpeg](https://ffmpeg.org)（リサンプルとラウドネス処理に使用）。例: `winget install --id Gyan.FFmpeg -e`。`ffmpeg` が `PATH` にない場合は、`OTOMAKER_FFMPEG` に `ffmpeg.exe` のフルパスを設定します。インストーラーは、見つからないときに知らせます。
- 任意: NVIDIA GPU と、起動済みの ComfyUI（`sa3-comfy` バックエンド用）。

Python、uv、Git を事前に入れる必要はありません（`install.cmd` が OtoMaker フォルダの中に用意します）。Stable Audio 3 のランタイムとモデルファイルはこのパッケージに含まれず、インストール時にダウンロードします。

日本語などを含むフォルダ（日本語のユーザー名の下など）にも置けます。TFLite ランタイムはそのようなパスを自分では開けないため、OtoMaker が英数字だけの形（8.3 形式の短い名前、またはランタイムのフォルダからの相対パス）にして渡します。

Hugging Face のアカウントやトークンは不要です。モデルのリポジトリは公開されています。

## インストール（install.cmd）

1. zip を展開します（例: `C:\Tools\OtoMaker`）。zip の中から直接は実行できません。
2. 展開したフォルダの `install.cmd` をダブルクリックします。次の順に進みます。
   1. **uv**: `PATH` にある uv を使います。無い場合は、固定したバージョンの公式配布物（[astral-sh/uv](https://github.com/astral-sh/uv) の GitHub Releases）をダウンロードし、SHA256 を照合して `runtime\uv\` に置きます。
   2. **Python 3.12 と依存パッケージ**: `uv sync --locked --extra tflite --no-dev` を実行します。Python は uv が管理するものを `runtime\python\` に入れます。
   3. **Stable Audio 3 のランタイム**: 動作を確認したコミット `77e0398` のアーカイブを GitHub からダウンロードし、SHA256 を照合して `stable-audio-3\optimized\tflite` に展開します。
   4. **モデル**: 取得するモデルを選びます（おすすめは `sfx` と `music`）。ファイルの一覧とライセンス条件が表示されるので、同意する場合は `y` を入力します。
   5. **MCP の登録**: Claude Desktop（`%APPDATA%\Claude\claude_desktop_config.json`）と Claude Code（`claude mcp add --scope user`）に `otomaker` を登録するか、それぞれ Y/N で聞きます。Claude Desktop の設定ファイルは、変更前に `.bak-日時` の名前でバックアップを取り、`mcpServers` に `otomaker` を足すだけで、他の設定はそのまま残します。
3. Claude を再起動します。Claude Desktop は、タスクトレイのアイコンから終了してから起動し直します。

インストーラーは `PATH` やシステムの設定を変えません。uv・Python・パッケージのキャッシュはすべて OtoMaker フォルダの中（`runtime\`、`.venv\`、`stable-audio-3\`）に置きます。モデルファイルだけは Hugging Face のキャッシュに入ります（後述）。もう一度 `install.cmd` を実行すると、足りない部分だけを用意し直します。

- **モデルを後から取得する:** `download-models.cmd` をダブルクリックします。取得していないモデルで生成すると、実行するコマンドを示して止まります。
- **登録を外す:** `uninstall.cmd` をダブルクリックします。Claude Desktop と Claude Code から `otomaker` の登録を外します（それぞれ Y/N で確認）。フォルダとモデルは消さないので、不要なら表示された場所を手で削除します。生成した音声（`outputs\`）もフォルダの中にあります。
- **他のクライアント（Cursor など）:** MCP 設定の `"command"` に `<OtoMaker フォルダ>\.venv\Scripts\otomaker-mcp.exe` のフルパスを書きます。

## 手動でのセットアップ（CPU、sa3-tflite）

`install.cmd` を使わない場合の手順です。[uv](https://docs.astral.sh/uv/) と [Git](https://git-scm.com) を使います。

1. OtoMaker フォルダの中に、Stable Audio 3 のランタイム（[Stability-AI/stable-audio-3](https://github.com/Stability-AI/stable-audio-3)、MIT）を取得します。OtoMaker はコミット `77e0398` で動作を確認しています。これより新しいコミットでは、OtoMaker が使う内部の仕組みが変わっている可能性があります。

   ```bat
   cd C:\Tools\OtoMaker
   git clone https://github.com/Stability-AI/stable-audio-3.git
   cd stable-audio-3
   git checkout 77e0398
   cd ..
   ```

   これでランタイムは、OtoMaker が既定で探す `<OtoMaker フォルダ>\stable-audio-3\optimized\tflite` に入ります。別の場所に置いた場合は、`OTOMAKER_SA3_TFLITE_DIR` にその `optimized\tflite` フォルダを設定します。

2. TFLite 用の追加依存を含めてインストールします。`--no-dev` を付けるとテスト用のツールを入れません。

   ```bat
   uv sync --extra tflite --no-dev
   ```

3. 使うモデルをダウンロードします。`sfx`（小型の効果音モデル）と `music`（小型の音楽モデル）はどちらも最大 120 秒、`medium`（大きめの音楽モデル）は最大 380 秒です。`all` で 3 つすべてを取得します。全モデル共通のテキストエンコーダーは 1 回だけ取得します。コマンドはファイルとサイズの一覧とライセンス条件を表示し、同意（`y`）を求めます。`--accept-licenses` を付けると確認を省略します（条件を読んで同意した場合だけ。付けずに端末の無い環境で実行すると、何もダウンロードしません）。`--models sfx,music` は名前を並べるのと同じです。`--dry-run` を付けると一覧の表示だけを行います。ランタイム（手順 1）が無いときは、`install.cmd` と同じ固定コミットと SHA256 照合で取得もします。

   ```bat
   .venv\Scripts\otomaker-download.exe sfx music
   ```

   この手順を省くと、生成は実行するコマンドを示して止まります。`OTOMAKER_SA3_AUTO_DOWNLOAD=1` にすると、代わりに初回の使用時にランタイムがファイルをダウンロードします。

4. Claude Code にサーバーを登録します（パスは自分の環境に合わせて置き換えてください）。

   ```bat
   claude mcp add --scope user otomaker -- "C:\Tools\OtoMaker\.venv\Scripts\otomaker-mcp.exe"
   ```

   ランタイムを既定の場所以外に置いた場合は、`-e OTOMAKER_SA3_TFLITE_DIR=<パス>` を足します。Claude Desktop、Cursor など他のクライアントでは、同じ実行ファイル（`otomaker-mcp.exe` のパス）を MCP 設定の `"command"` に書きます。

`otomaker-mcp.exe` は標準入出力（stdio）でクライアントとやり取りします。`--http ポート番号` を付けると、代わりに `http://127.0.0.1:ポート番号/mcp` で Streamable HTTP を提供します（この PC からのみ接続可能）。URL で接続するクライアント向けです。`--preload` を付けると起動時にモデルを読み込むため、最初の要求でモデルの読み込みを待ちません。

**モデルファイルの置き場所と必要な容量。** ファイルは Hugging Face のキャッシュ（`HF_HOME`、既定は `%USERPROFILE%\.cache\huggingface`）にダウンロードされ、ランタイムの `models\` フォルダから参照できるようにします。Windows の開発者モードが有効ならシンボリックリンク、無効なら同じドライブ上でハードリンク、それ以外はコピーになり、コピーのときは容量を 2 倍使います。コピーを避けるには、OtoMaker フォルダを `HF_HOME` と同じドライブに置くか、`HF_HOME` をそのドライブ上のフォルダに設定します。また、ランタイムは初回の使用時に、DiT とコーデックの各モデルの隣にモデルとほぼ同じ大きさの重みキャッシュ（`.xnnwc`）を書き出します。テスト PC（ハードリンク）での実測では、`music` だけで約 1.8 GB、小型モデルを 1 つ足すごとに約 1.0 GB、`medium` を足すと約 3.2 GB 増えます。コピーになる場合は、さらにダウンロードした分（`music` だけなら 1.25 GB）が増えます。

## セットアップ（GPU、sa3-comfy）

`sa3-comfy` は、利用者が起動した ComfyUI（`OTOMAKER_COMFY_HOST`、既定は ComfyUI 自体の既定と同じ `127.0.0.1:8188`）へ生成要求を送ります。このバックエンドはテキストからの生成だけに対応します（`edit_audio` は不可）。`OTOMAKER_BACKEND=sa3-comfy` を設定します。ComfyUI が起動していないときに CPU へ切り替えるには、`OTOMAKER_FALLBACK=sa3-tflite` も設定します。切り替えた結果は、生成結果とメタデータに記録されます。

1. ComfyUI 用のファイルを [Comfy-Org/stable-audio-3](https://huggingface.co/Comfy-Org/stable-audio-3) からダウンロードします。medium のチェックポイントは 9.2 GB、小型はそれぞれ 2.3 GB、テキストエンコーダーは 1.2 GB です。ファイルは `--comfy-dir` の下の `checkpoints\` と `text_encoders\` に入ります。

   ```bat
   .venv\Scripts\otomaker-download.exe sfx music --comfy --comfy-dir C:\path\to\ComfyUI\models
   ```

2. `--comfy-dir` に ComfyUI 自体の `models` フォルダを指定した場合は、これで完了です。別のフォルダを指定した場合は、`tools\comfy_extra_paths.yaml` を開き、`otomaker:` の部分を自分の ComfyUI の `extra_model_paths.yaml`（`main.py` と同じフォルダ。無ければ `extra_model_paths.yaml.example` をその名前でコピー）に追記します。`base_path` をそのフォルダに書き換え、ComfyUI を再起動します。

既定では、`unload_models` とアイドル時の解放は ComfyUI のメモリに触れません。ComfyUI の `/free` は、他のツールのものも含めてすべてのモデルを解放するためです。`/free` を送るには `OTOMAKER_COMFY_FREE=1` を設定します。

## 設定

| 変数 | 既定値 | 意味 |
|---|---|---|
| `OTOMAKER_BACKEND` | `sa3-tflite` | `sa3-tflite`（CPU）または `sa3-comfy`（ComfyUI） |
| `OTOMAKER_FALLBACK` | 無効 | ComfyUI に接続できないときに `generate_audio` を実行するバックエンド（例: `sa3-tflite`） |
| `OTOMAKER_HOME` | OtoMaker フォルダ（`uvx` で入れたときは `%LOCALAPPDATA%\OtoMaker`） | データフォルダ。ランタイムと `outputs\` を置く |
| `OTOMAKER_SA3_TFLITE_DIR` | `<データフォルダ>\stable-audio-3\optimized\tflite` | ランタイムの `optimized\tflite` フォルダ |
| `OTOMAKER_SA3_MODEL` | `sm-music` | `sm-music`、`sm-sfx`（最大 120 秒）、`medium`（最大 380 秒） |
| `OTOMAKER_SA3_PRECISION` | `w8a8` | `w8a8` または `fp32`（TFLite） |
| `OTOMAKER_SA3_DECODER` | 上流の組み合わせ | `same-s` または `same-l`（TFLite） |
| `OTOMAKER_SA3_AUTO_DOWNLOAD` | `0` | `1` にすると、足りないモデルファイルを初回の使用時にランタイムがダウンロードする（`otomaker-download` のライセンス確認を通らない） |
| `OTOMAKER_SA3_THREADS` | 物理コア数（最大 10） | TFLite ランタイムの CPU スレッド数。コア数は `tflite` 追加依存で入る psutil で数えます |
| `OTOMAKER_COMFY_HOST` | `127.0.0.1:8188` | ComfyUI のアドレス（`sa3-comfy`） |
| `OTOMAKER_COMFY_LENGTH_SUFFIX` | `1` | `1` は ComfyUI 向けに「Length: N seconds」をプロンプトへ追記。`0` はそのまま送る |
| `OTOMAKER_COMFY_FREE` | `0` | `1` にすると `unload_models` とアイドル時の解放で ComfyUI に `/free` を送る（ComfyUI の全モデルを解放） |
| `OTOMAKER_OUTPUT_DIR` | `<データフォルダ>\outputs` | 音声ファイルの出力先 |
| `OTOMAKER_IDLE_UNLOAD_MIN` | `10` | この分数アイドルしたらモデルを解放（`0` で解放しない） |
| `OTOMAKER_FFMPEG` | `PATH` 上の `ffmpeg` | `ffmpeg.exe` のフルパス |
| `HF_HOME` | `%USERPROFILE%\.cache\huggingface` | モデルのダウンロードに使う Hugging Face のキャッシュ |

`claude mcp add ... -e 名前=値` で渡すか、クライアントの MCP 設定の `env` に書きます。

## プロンプトのコツ

1. 英語で、1〜2 文、約 45 語以内。"vocals"、"singer"、"lyrics" などの歌詞に関わる語は避けます。
2. 音楽: ジャンルと形容詞、続けて主要な楽器、補助的な層、ドラム、雰囲気の順に書きます。テンポは `bpm` に入れます。
3. 効果音: `sound_source`、`sound_action`、`sound_material`、`sound_space` を埋めます。モデルが学習した接頭辞はサーバーが付けます。
4. 長さは内容に合わせます。インパクト 1〜3 秒、動作 3〜6 秒、環境音 6〜15 秒、ループ 6〜20 秒、曲全体 120〜300 秒。
5. 「15 秒でクライマックス」のような時間指定は確実には従いません。まず生成し、そのあと `edit_audio` の `inpaint` や `continue` を使います。
6. 結果はシードによって大きく変わります。`variations` を 2〜4 にして、良いものを選んでください。

ピーク正規化は安全上限を使います。`peak_ceiling_db`（既定 −1）は、それより大きいピークを下げますが、小さい音を持ち上げることはありません。ラウドネスを揃えるには `process_audio` を使います。OGG で書き出したときは、`process_audio` はエンコード後のファイルで測った音量を返します。

## 開発

開発者向けの説明です。テスト用のツールを含めてインストールし、オフラインのテストを実行します。

```bat
uv sync --extra tflite
uv run --extra tflite pytest -q
```

オフラインのテストはダミーのバックエンドを使うため、ランタイムもモデルの重みも不要です。git リポジトリには、実モデルを使って全ツールを stdio 経由で 1 回ずつ実行する開発者向けの確認用スクリプト `scripts\smoke_test.py` もあります。配布用の zip には含まれません。

```
src\otomaker\
  server.py            MCP ツール（バックエンドに依存しない）
  prompts.py           プロンプト生成とクライアントへ送る指示
  post.py              後処理と書き出し
  download.py          otomaker-download（モデルファイルの取得）
  backends\base.py     バックエンドの共通インターフェース
  backends\sa3_tflite.py  CPU 上の Stable Audio 3（TFLite / LiteRT）
  backends\sa3_comfy.py   ComfyUI 経由の Stable Audio 3
```

## よくある質問

**NVIDIA GPU がなくても動きますか？** はい。既定のバックエンドは CPU で動きます。GPU と ComfyUI を使う場合より生成に時間がかかります。

**歌入りの曲は作れますか？** いいえ。Stable Audio 3 はインストゥルメンタルの音楽と効果音を生成します。

**Hugging Face のトークンは要りますか？** いいえ。モデルファイルは公開されています。

**ループの継ぎ目でクリックが出ます。** ループには WAV か OGG を使ってください。MP3 は前後に余白を入れるため、シームレスにループしません。`loop_crossfade_ms` を長くするか、小節の区切りで切るように指示してください。

## ライセンスと注意事項

詳しい表示は [NOTICE](NOTICE) にあります。

- **このプロジェクト:** [MIT](LICENSE)。Copyright (c) 2026 kanaworksai-hue（元のコード）、Copyright (c) 2026 OG-3（Windows 版の追加と変更）。[kanaworksai-hue/audio-studio-mcp](https://github.com/kanaworksai-hue/audio-studio-mcp)（MIT）をもとにしています。
- **Stable Audio 3 のモデルの重み:** 含まれません。Hugging Face からダウンロードされ、[Stability AI Community License](https://stability.ai/community-license-agreement) の下で提供されています。年間売上が US$1M 以上の場合、商用利用には Stability AI の Enterprise License が必要です。This Stability AI Model is licensed under the Stability AI Community License, Copyright © Stability AI Ltd. All Rights Reserved. Powered by Stability AI.
- **T5Gemma テキストエンコーダー:** 含まれません。モデルと一緒にダウンロードされ、[Gemma Terms of Use](https://ai.google.dev/gemma/terms) が適用されます。
- **Stable Audio 3 のランタイムのコード:** [Stability-AI/stable-audio-3](https://github.com/Stability-AI/stable-audio-3)、MIT、Copyright (c) 2026 Stability AI。含まれません。利用者が clone し、OtoMaker が実行時に読み込みます。
- **基盤:** [Stable Audio 3](https://github.com/Stability-AI/stable-audio-3) と [Model Context Protocol](https://modelcontextprotocol.io)。

本プロジェクトは独立したものであり、Stability AI、Google、Anthropic とは提携・推奨の関係にありません。
