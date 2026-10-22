# ゆんたくん 会話サーバー

StackChan のマイクで拾った声を PC に送り、文字起こし・返事の作成・音声合成をして、返事の音声を StackChan に返すサーバーです。
**複数台の StackChan を同時につなげられ、台ごとに性格と会話履歴を分けて持ちます。**

```
StackChan ──(録音WAV + 台のID)──▶ /talk
                                   1. Whisper (faster-whisper)    声 → 文字
                                   2. Ollama (Qwen / Gemma など)    文字 → 返事の文章
                                   3. Kokoro TTS                   文章 → 声
StackChan ◀──(返事WAV)──────────
```

## ファイル構成

プロジェクトは、**PC で動かすサーバー**と、**StackChan に書き込むプログラム**の2つに分かれています。置き場所は離れていてかまいません(通信でつながるだけです)。

### 全体

```
Documents\
├─ Yuntakun_server\                 ← PC で動かすサーバー(この README のフォルダ)
└─ PlatformIO\Projects\Yuntakun\    ← StackChan に書き込むプログラム(PlatformIO)

  StackChan ×N台 ──Wi-Fi──▶ PC(Yuntakun_server)
  StackChan ×1台 ──USB──▶ PC(bridge.py ─▶ Yuntakun_server)
```

### PC 側: Yuntakun_server\

```
Yuntakun_server\
├─ server.py          本体。API(/talk など)と、会話の流れ
├─ config.py          設定。モデル名・しきい値・保存数など(調整はここ)
├─ devices.py         台ごとの設定の読み込み
├─ devices.toml       ★ どの StackChan にどの性格を割り当てるか
├─ personas.py        性格ファイルの読み込み
├─ personas\
│   ├─ common.txt         ★ どの性格にも共通のルール
│   ├─ listener.toml      ★ やさしい聞き役(標準)
│   ├─ grandchild.toml    ★ 元気な孫
│   ├─ professor.toml     ★ 物知り博士
│   ├─ storyteller.toml   ★ のんびり昔話好き
│   └─ cheerleader.toml   ★ 励まし上手
├─ bridge.py          USB 接続のときだけ使う橋渡し
├─ requirements.txt   必要なライブラリの一覧
├─ README.md          この文書
├─ venv\              Python の仮想環境(自分で作る。移動やコピーはしない)
└─ recordings\        録音と返事の WAV(自動で作られる。直近のみ保持)
```

★ は、**普段、自分で編集するファイル**です。`.py` は、機能を変えたいとき以外は触らなくて大丈夫です。

| 変えたいこと | 編集するファイル |
|---|---|
| 台ごとの性格の割り当て | `devices.toml` |
| 性格の中身(口調・声・速さ) | `personas\<ID>.toml` |
| 全性格に共通のルール | `personas\common.txt` |
| 性格を増やす | `personas\` に `<ID>.toml` を追加 |
| モデル・しきい値・保存数 | `config.py` |

### StackChan 側: PlatformIO\Projects\Yuntakun\

```
Yuntakun\
├─ platformio.ini     環境の定義。env:wifi と env:usb の切り替え
├─ include\
│   └─ secrets.h      ★ Wi-Fi の SSID・パスワード・サーバーの URL(env:wifi 用)
├─ src\
│   └─ main.cpp       本体。待ち受け・録音・通信・再生
└─ .pio\              ビルドの出力(自動で作られる。触らない)
```

| 変えたいこと | 編集するファイル |
|---|---|
| Wi-Fi・サーバーの IP | `include\secrets.h` |
| 接続方式(Wi-Fi / USB) | ファイルは触らず、VS Code 下部で環境(env)を選ぶ |
| 反応しすぎ・しなさすぎ | `src\main.cpp` の `MIN_THRESHOLD` / `HOT_NEEDED` など |

`secrets.h` には Wi-Fi のパスワードが入ります。チャットや GitHub に貼らないでください。

## セットアップ(Windows)

**1. Python 3.12 を入れます。** Kokoro が新しすぎる Python(3.13 以降)に対応していない場合があるためです。

```
py -3.12 -m venv venv
venv\Scripts\activate
```

**2. PyTorch を先に入れます。** 環境に合うコマンドは https://pytorch.org/get-started/locally/ で確認してください(CPU のみなら `pip install torch`)。

**3. 残りのライブラリを入れます。**

```
pip install -r requirements.txt
```

日本語の読み解析 `pyopenjtalk` のビルドに失敗する場合は、Visual Studio Build Tools(「C++ によるデスクトップ開発」)を入れ、「x64 Native Tools Command Prompt」から、もう一度実行してください。

**4. Ollama を入れ、モデルを取得します。** https://ollama.com/download からインストールしたあと、次を実行します。

```
ollama pull qwen2.5:3b
```

`config.py` の `LLM_MODEL` を変えたときは、そのモデルも `ollama pull` してください。

## 起動

```
venv\Scripts\activate
uvicorn server:app --host 0.0.0.0 --port 8000
```

`warmup done` と `Uvicorn running on ...` が出るまで待ちます(初回はモデルのダウンロードで時間がかかります)。

> `--host 0.0.0.0` は、同じネットワークの誰でもアクセスできる設定です。自宅などの信頼できるネットワークで使ってください。

## 動作確認

録音した WAV(16kHz / 16bit / モノラル)を送り、返事の WAV を受け取ります。`X-Device-Id` は台のIDです(省略すると `unknown` の台として扱われます)。

```
curl.exe -X POST --data-binary "@test.wav" -H "Content-Type: audio/wav" -H "X-Device-Id: test" http://localhost:8000/talk -o reply.wav
```

サーバーのログに、台の名前・性格・各段階の時間が出ます。

```
[リビング|grandchild] User : 'こんにちは'   [Whisper 3.1s]
[リビング|grandchild] Reply: こんにちは。今日はどんな一日でしたか？   [LLM 3.6s]
[リビング|grandchild] [Kokoro 1.9s / total 8.6s]
```

`curl` の「Current Speed」が数十秒 0 になるのは、サーバーが処理中で、まだ何も返していないためです。故障ではありません。

## 複数台で使う

### 1. 各 StackChan の ID を調べる

StackChan(`env:wifi`)を起動すると、Wi-Fi につながったあと、画面に `ID xxxxxxxxxxxx` と12桁の ID が4秒ほど出ます(本体の MAC アドレスです)。
サーバーに最初につながったときも、ログに `new device: xxxxxxxxxxxx (未登録 -> listener)` と出ます。

### 2. devices.toml に性格を割り当てる

```toml
default_persona = "listener"          # 登録していない台の性格

[devices.a1b2c3d4e5f6]                # ← 調べたID
label = "リビング"                     # ログに出す名前
persona = "grandchild"                # ← personas/ のファイル名(.toml を除く)
```

書き換えたら、サーバーを再起動するか、次で読み直します。

```
curl.exe -X POST http://localhost:8000/personas/reload
```

### 3. 確認する

```
curl.exe http://localhost:8000/devices
```

台ごとの割り当て、いまの性格、最後に話した時刻が出ます。

### 一時的に性格を変える

ブラウザで **http://localhost:8000/docs** を開くと、ボタンで操作できます。コマンドなら次のとおりです。

```
curl.exe -X POST http://localhost:8000/devices/a1b2c3d4e5f6/persona/professor   # その台だけ切り替え
curl.exe -X POST http://localhost:8000/devices/a1b2c3d4e5f6/reset               # その台の会話履歴だけリセット
curl.exe http://localhost:8000/personas                                         # 性格の一覧
```

- 一時的な切り替えは、`devices.toml` を書き換えません。**`reload` や再起動で、割り当てどおりに戻ります。**
- 性格を変えると、その台の会話履歴はリセットされます。
- `reload` では、全台の会話履歴がリセットされます。

### 複数台で使うときの注意

- **処理は1件ずつ順番に行います。** Whisper・LLM・Kokoro のモデルを全台で共有するためです。同時に話しかけると、後の台は順番待ち(ログに `順番待ち ○s` と出ます)になります。
  - CPU(1回あたり約10〜35秒)だと、2台が重なるだけでかなり待たされます。
  - GPU(1回あたり数秒)なら、5台でもほとんど気になりません。
- **近くに置いた台どうしは、お互いの返事を拾って反応します。** 離して置くか、StackChan 側のしきい値(`MIN_THRESHOLD` / `HOT_NEEDED`)を上げてください。
- **全台に同じ `SERVER_URL` を書きます。** PC の IP が変わると全台を書き換えることになるので、ルーターで PC の IP を固定するのがおすすめです。
- **USB 接続(`bridge.py`)の台は、`bridge.py` の `DEVICE_ID`(既定は `usb`)が台のIDです。** `devices.toml` に `[devices.usb]` を書けば、性格を割り当てられます。複数台は Wi-Fi 接続を推奨します。
- **`recordings` に残るファイル数(`KEEP_FILES`)は、台数に合わせて増やしてください。** ファイル名は `日時_台のID_in.wav` です。

## 性格の追加・編集

`personas/` に `<好きなID>.toml` を置くだけで、性格が増えます(ファイル名がIDになります。半角英数字と `_` `-` にしてください)。

```toml
name = "表示名"                   # 必須
description = "一言の説明"
voice = "jf_alpha"                # Kokoro の声(省略時は config.py の DEFAULT_VOICE)
speed = 1.0                       # 話す速さ(省略時は DEFAULT_SPEED)
temperature = 0.7                 # 大きいほど自由な返事(省略時は config.py の値)
prompt = """
この性格だけの指示を書く。
"""                               # 必須
```

- どの性格にも共通のルール(1〜2文で答える、絵文字禁止、緊急時の対応など)は、`personas/common.txt` に書きます。**性格ごとに書き直す必要はありません。**
- 実際にLLMへ渡るのは、`common.txt` の内容と、性格の `prompt` をつなげたものです。
- ID(ファイル名)を変えたら、`devices.toml` の `persona = "..."` と、`config.py` の `DEFAULT_PERSONA` も合わせてください。`personas.py` は変えなくて大丈夫です。
- 編集したら、`curl.exe -X POST http://localhost:8000/personas/reload` で、再起動せずに反映できます。書き方を間違えたファイルは、警告を出して読み飛ばします。
- Kokoro の日本語の声は、`jf_alpha` `jf_gongitsune` `jf_nezumi` `jf_tebukuro` `jm_kumo` などです。**声の名前は Kokoro のバージョンで増減する**ので、存在しない名前だとエラーになります。

## 設定(config.py)

| 項目 | 内容 |
|---|---|
| `USE_GPU` | GPU の PC では `True`。Whisper が kotoba-whisper(GPU向け)に切り替わる |
| `WHISPER_MODEL` / `BEAM_SIZE` | 認識精度と速度のバランス。`small` → `medium` で精度向上(遅くなる) |
| `VAD_PARAMS` | 声かどうかの判定。雑音に反応するなら `threshold` を 0.6〜0.7 に |
| `IGNORE_TEXTS` | 幻聴として無視する文章 |
| `LLM_MODEL` / `LLM_OPTIONS` | 使うモデルと、返事の長さ(`num_predict`) |
| `MAX_HISTORY_TURNS` | 台ごとに覚えておく往復の数 |
| `DEFAULT_PERSONA` | `devices.toml` が無い・壊れているときの既定の性格 |
| `KEEP_FILES` | `recordings` に残すWAVの数 |

## StackChan との接続

StackChan 側のプロジェクト(`Yuntakun/`)は、PlatformIO の環境で接続方式を選びます。

| 環境 | 方式 | PC 側で必要なもの |
|---|---|---|
| `env:wifi` | Wi-Fi(HTTP) | この server.py のみ。`include/secrets.h` に Wi-Fi と PC の IP を書く |
| `env:usb` | USB ケーブル | server.py と `python bridge.py`(`pip install pyserial requests`) |

- 複数台は、**全台に同じファームウェア(`env:wifi`)を書き込めば**よく、台ごとの書き換えは要りません。台のIDは本体の MAC アドレスから自動で作られます。
- Wi-Fi は **2.4GHz** のみ対応です。学校・会社の WPA2-Enterprise のネットワークにはつなげないので、その場合はスマホのテザリングを使ってください。

## トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| `Failed to connect to localhost:8000` | サーバーが起動していない、または起動の途中。`Uvicorn running on ...` を待つ |
| `reply.wav` が開けない | サーバーが 500 を返し、中身がエラー文になっている。サーバーのログの Traceback を見る |
| `model '...' not found` | `ollama pull <モデル名>` を実行する |
| `open() got an unexpected keyword argument 'metadata_errors'` | `av` が新しすぎる。`pip install "av<17"` |
| `ignored (noise / too short)` が出続ける | 声が小さい、または短い。`recordings` の `_in.wav` を聴いて確認 |
| 何にでも反応する | StackChan 側のしきい値と、`VAD_PARAMS` の `threshold` を上げる |
| 返事が遅い | ログの Whisper / LLM / Kokoro の秒数で重い段階を確認。LLM は小さいモデルや `num_predict` を短く |
| `new device: ... (未登録)` が出る | その台のIDが `devices.toml` に無い。IDを書き足して `reload` |
| 台の性格が割り当てと違う | `/devices` で `assigned_persona` と `current_persona` を確認。一時切り替えは `reload` で戻る |
| `warning: 性格 '...' がありません` | `devices.toml` の `persona` が、`personas/` のファイル名と合っていない |
| `404 その性格はありません` | `/personas` で ID を確認(ファイル名から `.toml` を除いたもの) |
