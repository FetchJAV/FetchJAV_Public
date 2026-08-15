<p align="center">
  <strong>English</strong> · <a href="#-繁體中文-traditional-chinese">繁體中文</a>
</p>

<h1 align="center">FetchJAV</h1>

<p align="center">
  <strong>The Ultimate All-in-One Desktop Downloader, Video Streamer & AI Subtitle Generator</strong><br />
  Supports <strong>JableTV</strong>, <strong>MissAV</strong>, and <strong>SupJav</strong> with automated speech recognition, instant preview proxy, and cross-site metadata matching.
</p>

<p align="center">
  <a href="https://github.com/DeepanshuK2002/FetchJAV/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/DeepanshuK2002/FetchJAV?style=flat-square&label=release&color=ff5263" /></a>
  <a href="https://github.com/DeepanshuK2002/FetchJAV/releases"><img alt="Total downloads" src="https://img.shields.io/github/downloads/DeepanshuK2002/FetchJAV/total?style=flat-square&label=downloads&color=2ea44f" /></a>
  <a href="https://github.com/DeepanshuK2002/FetchJAV"><img alt="GitHub stars" src="https://img.shields.io/github/stars/DeepanshuK2002/FetchJAV?style=flat-square&logo=github&color=f5b942" /></a>
  <a href="./LICENSE"><img alt="Apache 2.0 license" src="https://img.shields.io/github/license/DeepanshuK2002/FetchJAV?style=flat-square" /></a>
  <a href="https://github.com/DeepanshuK2002/FetchJAV/pkgs/container/jabletv"><img alt="Docker amd64 and arm64" src="https://img.shields.io/badge/Docker-amd64%20%7C%20arm64-2496ed?style=flat-square&logo=docker&logoColor=white" /></a>
</p>

<p align="center">
  <strong><a href="https://github.com/DeepanshuK2002/FetchJAV/releases/latest/download/FetchJAV.exe">⬇️ Download FetchJAV.exe (Windows Direct)</a></strong>
  ·
  <a href="https://github.com/DeepanshuK2002/FetchJAV/releases/latest">📦 View Latest Release</a>
</p>

---

## ⚡ What Makes FetchJAV Superior?
### Exclusive Features (Not in the Original JableTV Downloader)

| Feature | FetchJAV | Original JableTV |
|---|---|---|
| **Direct Standalone .exe** | ✅ **`FetchJAV.exe`** with bundled FFmpeg, SSL certs, zero setup | ❌ Requires manual Python environment |
| **Local AI Speech Recognition** | ✅ Built-in offline **ReazonSpeech** & **Whisper** ASR models | ❌ No speech-to-text |
| **Automated Multi-Lingual Subtitles** | ✅ Auto-generates `.ja.srt`, `.en.srt`, `.zh-TW.srt` without touching MP4 | ❌ No subtitle generation |
| **Cloud LLM Translation Option** | ✅ Supports OpenAI, Claude, DeepSeek, Ollama, Gemini API translation | ❌ None |
| **Instant Streaming Video Preview** | ✅ Built-in local HTTP proxy with on-the-fly TS segment header repair | ❌ Must download entire video first |
| **SupJav Multi-Server Support** | ✅ Instant TV server streaming + automatic mirror fallback | ❌ No SupJav or mirror failover |
| **Modern Dark Theme & Customization** | ✅ CustomTkinter UI with accent color selector & responsive cards | ❌ Basic legacy interface |
| **Persistent History & Queue** | ✅ Queue & completed history saved across restarts with 1-click re-download | ❌ Session lost on exit |
| **Cross-Site Metadata Matching** | ✅ Cross-searches MissAV & SupJav to fill actress, studio, director & tags | ❌ Single-site only |
| **System Tray Background Mode** | ✅ Minimize to tray via `pystray` with download completion alerts | ❌ No tray support |
| **Network & SSL Crash Prevention** | ✅ Shared SSLContext & `curl_cffi` engine fixing Windows OpenSSL crashes | ❌ Common native SSL crashes |

---

## 📸 Screenshots & Interface Showcase

<p align="center">
  <strong>Browse & Search Gallery (JableTV, MissAV, SupJav)</strong><br />
  <img src="./img/screenshots/browse_gallery.png" width="95%" alt="FetchJAV Browse Gallery" />
</p>

<p align="center">
  <strong>Real-Time Streaming Video Preview</strong><br />
  <img src="./img/screenshots/preview_player.png" width="95%" alt="FetchJAV Video Preview" />
</p>

<p align="center">
  <strong>Multi-Threaded Download Queue with Speed Meter</strong><br />
  <img src="./img/screenshots/download_queue.png" width="95%" alt="FetchJAV Download Queue" />
</p>

<p align="center">
  <strong>AI Subtitles & Translation Settings (Local & LLM)</strong><br />
  <img src="./img/screenshots/settings_subtitles.png" width="95%" alt="FetchJAV AI Subtitle Settings" />
</p>

<p align="center">
  <strong>Persistent Download History with Metadata & Tags</strong><br />
  <img src="./img/screenshots/history_tab.png" width="95%" alt="FetchJAV Download History" />
</p>

---

## 🚀 Windows: Quick Start in 30 Seconds

1. **Download**: Grab **[FetchJAV.exe](https://github.com/DeepanshuK2002/FetchJAV/releases/latest/download/FetchJAV.exe)**.
2. **Launch**: Place the file in any writable folder and double-click to run. (No Python or external dependencies required).
3. **Choose Language**: On first launch, select your language (English, 繁體中文, 简体中文, 日本語) and customize your dark/light theme and accent color.
4. **Browse & Download**:
   - Navigate to **Browse**, select a site (JableTV, MissAV, or SupJav), browse categories or search keywords.
   - Select multiple cards and click **Add to Queue** or **Download Selected**.
   - You can also paste URLs directly into the **Download** tab, or import batch URLs from `.txt` or `.csv` files.

---

## 🛠️ Run from Source (macOS / Linux / Developer)

Requires **Python 3.10+** and Tk:

```bash
# Clone the repository
git clone https://github.com/DeepanshuK2002/FetchJAV.git
cd FetchJAV

# Install dependencies
python -m pip install -r requirements.txt

# Run the complete GUI
python main.py

# Or run headlessly with CLI options
python main.py --nogui --url "https://jable.tv/videos/example/" --output "./download" --max-workers-per-video 4
```

---

## 🐳 Docker / NAS Headless Deployment

The public container image is available at `ghcr.io/deepanshuk2002/fetchjav:latest`:

```bash
# Download a single URL to /downloads folder
docker run --rm -v "/path/to/downloads:/downloads" \
  ghcr.io/deepanshuk2002/fetchjav:latest "https://jable.tv/videos/example/"

# Docker Compose: pass urls via urls.txt
docker compose run --rm jabletv
```

---

## 🤝 Contributing & Bug Reports

When opening a [GitHub Issue](https://github.com/DeepanshuK2002/FetchJAV/issues/new), please include:
- App version and operating system.
- Target website, reproducible URL, and error messages.
- If a crash occurred, attach `crash_log.txt` from beside the executable.

---

# 🇹🇼 繁體中文 (Traditional Chinese)

## FetchJAV
**JableTV、MissAV、SupJav 的終極桌面下載器、串流預覽與 AI 生成字幕工具。**

---

### 🌟 FetchJAV 獨家強大功能（相較原版 JableTV）

| 功能項目 | FetchJAV | 原版 JableTV |
|---|---|---|
| **免安裝單一執行檔** | ✅ **`FetchJAV.exe`** 內建 FFmpeg、SSL 憑證，雙擊即開即用 | ❌ 需手動配置 Python 環境與套件 |
| **本機 AI 語音辨識** | ✅ 內建離線 **ReazonSpeech** 與 **Whisper** 語音辨識模型 | ❌ 無字幕辨識功能 |
| **自動多語字幕生成** | ✅ 下載後自動生成 `.ja.srt`、`.en.srt`、`.zh-TW.srt`，不破壞原影片 | ❌ 無字幕生成 |
| **雲端 LLM 翻譯整合** | ✅ 支援接入 OpenAI、Claude、DeepSeek、Ollama、Gemini API | ❌ 無 |
| **影片即時串流預覽** | ✅ 內建本機串流代理，支援 HTTP Range 播放並自動修復分段檔頭 | ❌ 必須整部下載完成才能觀看 |
| **SupJav 多伺服器支援** | ✅ 優先選擇 TV 高速串流伺服器，遇阻斷自動切換備援鏡像 | ❌ 缺少多伺服器智慧容錯 |
| **現代深色 UI 與主題自訂** | ✅ CustomTkinter 現代介面、多種主題強調色、自適應卡片清單 | ❌ 傳統舊版介面 |
| **下載佇列與歷史記錄保存** | ✅ 重新開啟後保留佇列與已下載歷史，支援一鍵重新下載與開啟檔案 | ❌ 關閉軟體後狀態遺失 |
| **跨站影音元數據檢索** | ✅ 自動跨 MissAV 與 SupJav 檢索補齊女優、片商、導演與標籤資訊 | ❌ 僅限單站基本資訊 |
| **系統匣背景下載** | ✅ 支援縮小至系統匣背景下載與完成通知（使用 `pystray`） | ❌ 無系統匣功能 |
| **連線安全與閃退修復** | ✅ 整合 `curl_cffi` 與共用 SSLContext，徹底解決 Windows SSL 崩潰問題 | ❌ 常見 OpenSSL 原生崩潰 |

---

### 🚀 30 秒快速開始 (Windows)

1. **下載**：取得最新版 **[FetchJAV.exe](https://github.com/DeepanshuK2002/FetchJAV/releases/latest/download/FetchJAV.exe)**。
2. **執行**：將檔案放入任意可讀寫資料夾，**直接雙擊執行**（免安裝 Python、免額外配置）。
3. **選擇偏好**：首次啟動可選擇介面語言（繁體中文、English、简体中文、日本語）並自訂外觀主題。
4. **瀏覽與下載**：
   - 點擊「瀏覽」切換 JableTV、MissAV 或 SupJav，輸入關鍵字搜尋或依分類篩選。
   - 勾選多部影片加入佇列，或直接點擊開始下載。
   - 亦可直接在「下載」分頁貼上網址，或從 `.txt` / `.csv` 檔案批次匯入。

---

## 📜 授權與責任聲明

本專案採 [Apache License 2.0](./LICENSE) 授權開源。本工具僅供個人研究與合法備份使用，請遵守當地法規與各網站服務條款。
版本更新記錄請參閱 [GitHub Releases](https://github.com/DeepanshuK2002/FetchJAV/releases)。
